from pathlib import Path
import json
import os
import signal
import socket
import subprocess

import pytest

from desktopforge.launcher_runtime import LauncherError, RecoveryRequired
from desktopforge.session_launcher import (cancellation_handlers, check_environment,
    config_text, launch_environment, main, run_session, shell_status, validate_config)
from desktopforge.transient_session import TransientSession, cgroup_empty, cgroup_path

TOKEN = 'a' * 32


def reply(stdout='', returncode=0, stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class Manager:
    def __init__(self):
        self.calls = []
        self.loaded = False
        self.active = True
        self.invocation = 'b' * 32
        self.fail_start = False
        self.fail_stop = False
        self.wrong_identity = False

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == '/usr/bin/systemd-run':
            self.unit = next(arg.split('=', 1)[1] for arg in argv if arg.startswith('--unit='))
            self.description = next(arg.split('=', 1)[1] for arg in argv if arg.startswith('--description='))
            self.loaded = True
            return reply(returncode=1 if self.fail_start else 0)
        if 'stop' in argv:
            if self.fail_stop:
                return reply(returncode=1)
            self.active = False
            return reply()
        if not self.loaded:
            return reply('LoadState=not-found\n', returncode=1)
        if '--property=LoadState' in argv:
            return reply('LoadState=loaded\n')
        return reply('\n'.join(f'{k}={v}' for k,v in {
            'Id': self.unit, 'LoadState': 'loaded',
            'Description': 'foreign' if self.wrong_identity else self.description,
            'Transient': 'yes', 'InvocationID': self.invocation,
            'ActiveState': 'active' if self.active else 'inactive',
            'SubState': 'running' if self.active else 'dead',
            'MainPID': '42' if self.active else '0', 'ExecMainStatus': '0',
            'ControlGroup': f'/user.slice/user-1000.slice/user@1000.service/app.slice/{self.unit}',
        }.items()))


def test_unique_unit_uses_cgroup_shutdown_and_no_shared_units():
    manager = Manager()
    service = TransientSession(TOKEN, runner=manager, empty_probe=lambda *args: True)
    service.start(['/usr/bin/env', '-i', 'KEY=$literal', '/usr/bin/dbus-run-session', '--', '/usr/bin/niri'])
    assert service.invocation == 'b' * 32
    launch = next(call for call in manager.calls if call[0] == '/usr/bin/systemd-run')
    assert '--expand-environment=no' in launch
    assert '--property=KillMode=control-group' in launch
    assert '--property=RemainAfterExit=yes' in launch
    assert '--collect' not in launch
    service.stop()
    assert not service.requested
    assert all('niri.service' not in call for call in manager.calls)
    assert [call for call in manager.calls if 'stop' in call] == [
        ['/usr/bin/systemctl', '--user', 'stop', service.unit]]


@pytest.mark.parametrize('kind', ['description', 'invocation'])
def test_identity_changes_never_stop_foreign_unit(kind):
    manager = Manager()
    service = TransientSession(TOKEN, runner=manager)
    service.start(['/fixture'])
    if kind == 'description':
        manager.wrong_identity = True
    else:
        manager.invocation = 'c' * 32
    with pytest.raises(RecoveryRequired):
        service.stop()
    assert not any('stop' in call for call in manager.calls)
    assert service.requested


def test_partial_start_failure_still_stops_identified_owned_service():
    manager = Manager()
    manager.fail_start = True
    service = TransientSession(TOKEN, runner=manager, empty_probe=lambda *args: True)
    with pytest.raises(LauncherError):
        service.start(['/fixture'])
    service.stop()
    assert any('stop' in call for call in manager.calls)


@pytest.mark.parametrize('failure', ['stop', 'populated'])
def test_incomplete_shutdown_cannot_release_ownership(failure):
    manager = Manager()
    service = TransientSession(TOKEN, runner=manager, empty_probe=lambda *args: failure != 'populated')
    service.start(['/fixture'])
    manager.fail_stop = failure == 'stop'
    with pytest.raises(RecoveryRequired):
        service.stop()
    assert service.requested


def test_cgroup_paths_reject_traversal_and_unrelated_units():
    unit = f'desktopforge-{TOKEN}.service'
    for path in ('/system.slice/sshd.service', '/user.slice/../system.slice/' + unit,
                 '/user.slice/another.service', 'relative/' + unit):
        with pytest.raises(RecoveryRequired):
            cgroup_path(path, unit)


def test_cgroup_population_requires_explicit_zero(tmp_path, monkeypatch):
    monkeypatch.setattr('desktopforge.transient_session.cgroup_path', lambda *args: tmp_path)
    assert cgroup_empty('fixture', 'fixture')
    (tmp_path / 'cgroup.events').write_text('populated 1\nfrozen 0\n')
    assert not cgroup_empty('fixture', 'fixture')
    (tmp_path / 'cgroup.events').write_text('populated 0\n')
    assert cgroup_empty('fixture', 'fixture')
    (tmp_path / 'cgroup.events').write_text('frozen 0\n')
    with pytest.raises(RecoveryRequired):
        cgroup_empty('fixture', 'fixture')


@pytest.fixture
def env(tmp_path):
    return {'HOME': str(tmp_path), 'XDG_RUNTIME_DIR': str(tmp_path), 'WAYLAND_DISPLAY': 'wayland-test',
            'DBUS_SESSION_BUS_ADDRESS': 'host-bus', 'GH_TOKEN': 'must-not-propagate',
            'NIRI_CONFIG': '/host/config', 'NOTIFY_SOCKET': 'host-notify', 'PATH': '/untrusted'}


def versions(argv, **kwargs):
    if argv == ['/usr/bin/niri', '--version']:
        return reply('niri 26.04\n')
    if argv == ['/usr/bin/noctalia', '--version']:
        return reply('Noctalia v5.4.1\n')
    if argv[:2] == ['/usr/bin/loginctl', 'show-session']:
        return reply(f'Type=tty\nActive=yes\nRemote=no\nUser={os.getuid()}\n')
    if 'niri.service' in argv:
        return reply('ActiveState=inactive\n')
    return reply('Version=260\n')


def test_nested_check_is_read_only_and_uses_launch_accounts_socket(env, tmp_path):
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(tmp_path / 'wayland-test'))
    before = set(tmp_path.iterdir())
    try:
        result = check_environment(env, nested=True, runner=versions, executable=lambda _: True)
        assert result['status'] == 'ready_for_trial'
        assert set(tmp_path.iterdir()) == before
    finally:
        sock.close()


def test_missing_graphical_context_blocks_nested_launch(env):
    env.pop('WAYLAND_DISPLAY')
    result = check_environment(env, nested=True, runner=versions, executable=lambda _: True)
    assert result['status'] == 'blocked'
    assert any('logged-in Wayland' in text for text in result['blockers'])


def test_standalone_refuses_active_graphical_environment(env):
    env['XDG_SESSION_ID'] = 'fixture'
    result = check_environment(env, nested=False, runner=versions, executable=lambda _: True)
    assert result['status'] == 'blocked'
    env.pop('WAYLAND_DISPLAY')
    assert check_environment(env, nested=False, runner=versions, executable=lambda _: True)['status'] == 'ready_for_trial'


def test_child_environment_is_allowlisted_and_ephemeral(env, tmp_path):
    before = dict(env)
    result = launch_environment(env, tmp_path / 'launch', nested=True)
    for key in ('GH_TOKEN', 'DBUS_SESSION_BUS_ADDRESS', 'NIRI_CONFIG', 'NOTIFY_SOCKET'):
        assert key not in result
    assert result['WAYLAND_DISPLAY'] == 'wayland-test'
    assert result['PATH'] == '/usr/local/bin:/usr/bin:/bin'
    assert result['XDG_CONFIG_HOME'] == str(tmp_path / 'launch/config')
    assert result['XDG_STATE_HOME'] == str(tmp_path / 'launch/state')
    assert result['NIRI_DISABLE_SYSTEM_MANAGER_NOTIFY'] == '1'
    assert env == before
    assert 'WAYLAND_DISPLAY' not in launch_environment(env, tmp_path / 'launch', nested=False)


def test_config_validation_uses_sealed_anonymous_file():
    def parser(argv, **kwargs):
        fd = kwargs['pass_fds'][0]
        text = os.pread(fd, 65536, 0).decode()
        assert 'desktopforge.session_worker' in text
        assert 'niri-session' not in text and '--session' not in text
        assert 'spawn-sh' not in text
        with pytest.raises(OSError):
            os.write(fd, b'changed')
        return reply()
    validate_config(config_text(Path('/tmp/fixture'), TOKEN), parser)


@pytest.mark.parametrize('content', [[], {'token': TOKEN, 'ready': True, 'exit_code': 1},
    {'token': 'other', 'ready': True, 'exit_code': 0}, {'token': TOKEN, 'ready': 1, 'exit_code': 0}])
def test_invalid_readiness_records_are_rejected(tmp_path, content):
    (tmp_path / 'shell.json').write_text(json.dumps(content))
    with pytest.raises(LauncherError):
        shell_status(tmp_path, TOKEN)


class TrialUnit:
    instances = []
    fail_stop = False
    def __init__(self, token):
        self.unit = f'desktopforge-{token}.service'
        self.group = '/user.slice/' + self.unit
        self.calls = 0
        self.stopped = False
        self.instances.append(self)
    def start(self, argv):
        self.argv = argv
    def observe(self):
        self.calls += 1
        return {'ActiveState': 'active', 'SubState': 'running' if self.calls == 1 else 'exited', 'ExecMainStatus': '0'}
    def stop(self):
        self.stopped = True
        if self.fail_stop:
            raise RecoveryRequired('fixture unknown cgroup')


def trial(env, **kwargs):
    return run_session(env, nested=True, runner=lambda *args, **kwargs: reply(), session_factory=TrialUnit,
                       sleep=lambda _: None, **kwargs)


def test_runnable_supervisor_cleans_only_after_verified_shutdown(env, tmp_path):
    original = dict(env)
    assert trial(env, readiness=lambda *args: True, alive=lambda *args: True) == 0
    unit = TrialUnit.instances[-1]
    assert unit.stopped
    assert '/usr/bin/niri' in unit.argv
    assert '/usr/bin/niri-session' not in unit.argv and '--session' not in unit.argv
    assert '/usr/bin/dbus-run-session' in unit.argv
    assert not any('GH_TOKEN' in item or 'must-not-propagate' in item for item in unit.argv)
    assert not (tmp_path / 'desktopforge/attempt.json').exists()
    assert not list((tmp_path / 'desktopforge').glob('launch-*'))
    assert env == original


def test_shutdown_failure_preserves_attempt_and_diagnostics(env, tmp_path, monkeypatch):
    monkeypatch.setattr(TrialUnit, 'fail_stop', True)
    with pytest.raises(RecoveryRequired):
        trial(env, readiness=lambda *args: True, alive=lambda *args: True)
    assert (tmp_path / 'desktopforge/attempt.json').exists()
    assert list((tmp_path / 'desktopforge').glob('launch-*'))


@pytest.mark.parametrize('failure', ['shell_failed', 'shell_missing', 'timeout'])
def test_shell_failure_and_timeout_stop_owned_session(env, tmp_path, failure):
    clock_values = iter([0, 10])
    with pytest.raises(LauncherError):
        trial(env, readiness=lambda *args: False if failure == 'shell_failed' else None if failure == 'timeout' else True,
              alive=lambda *args: False, clock=lambda: next(clock_values), startup_timeout=5)
    assert TrialUnit.instances[-1].stopped
    assert not (tmp_path / 'desktopforge/attempt.json').exists()


def test_cancellation_stops_owned_session(env, tmp_path):
    count = len(TrialUnit.instances)
    assert trial(env, cancelled=lambda: True) == 130
    assert len(TrialUnit.instances) == count
    assert not (tmp_path / 'desktopforge/attempt.json').exists()


def test_signal_handlers_are_restored():
    original = signal.getsignal(signal.SIGTERM)
    with cancellation_handlers() as cancelled:
        assert not cancelled()
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert cancelled()
    assert signal.getsignal(signal.SIGTERM) == original


def test_check_entrypoint_never_launches(monkeypatch, capsys):
    monkeypatch.setattr('desktopforge.session_launcher.check_environment', lambda *args, **kwargs:
        {'status': 'ready_for_trial', 'notice': 'fixture', 'blockers': []})
    monkeypatch.setattr('desktopforge.session_launcher.validate_config', lambda *args: None)
    monkeypatch.setattr('desktopforge.session_launcher.run_session', lambda *args, **kwargs: pytest.fail('check launched'))
    assert main(['--nested', '--check', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'ready_for_trial'


def test_inactive_unloaded_invocation_can_finish_cleanup():
    manager = Manager()
    service = TransientSession(TOKEN, runner=manager, empty_probe=lambda *args: True)
    service.start(['/fixture'])
    actual = manager.__call__
    def inactive_without_invocation(argv, **kwargs):
        result = actual(argv, **kwargs)
        if not manager.active and 'show' in argv:
            lines = [line for line in result.stdout.splitlines() if not line.startswith(('InvocationID=', 'ControlGroup='))]
            return reply('\n'.join(lines + ['InvocationID=', 'ControlGroup=']))
        return result
    service.runner = inactive_without_invocation
    service.stop()
    assert not service.requested


def test_user_manager_loss_does_not_attempt_unverified_stop():
    manager = Manager()
    service = TransientSession(TOKEN, runner=manager)
    service.start(['/fixture'])
    service.runner = lambda *args, **kwargs: reply(returncode=1, stderr='No user manager')
    with pytest.raises(RecoveryRequired):
        service.stop()
    assert not any('stop' in argv for argv in manager.calls)


def test_successful_source_config_passes_installed_niri_parser():
    if not Path('/usr/bin/niri').exists():
        pytest.skip('Niri parser is not installed')
    validate_config(config_text(Path('/tmp/desktopforge-parser-fixture'), TOKEN))


def test_shell_worker_publishes_ready_atomically(tmp_path, monkeypatch):
    from desktopforge import session_worker
    calls = []
    def daemon(argv, **kwargs):
        calls.append((argv, kwargs))
        assert not (tmp_path / 'shell.json').exists()
        return reply()
    monkeypatch.setattr(session_worker.subprocess, 'run', daemon)
    assert session_worker.main([str(tmp_path), TOKEN]) == 0
    assert shell_status(tmp_path, TOKEN) is True
    assert calls[0][0] == ['/usr/bin/noctalia', '--daemon']
    assert calls[0][1]['shell'] is False
    assert not list(tmp_path.glob('*.pending'))
    original = (tmp_path / 'shell.json').read_bytes()
    with pytest.raises(FileExistsError):
        session_worker.main([str(tmp_path), TOKEN])
    assert (tmp_path / 'shell.json').read_bytes() == original


def test_shell_worker_failure_is_published(tmp_path, monkeypatch):
    from desktopforge import session_worker
    monkeypatch.setattr(session_worker.subprocess, 'run', lambda *args, **kwargs: reply(returncode=1))
    assert session_worker.main([str(tmp_path), TOKEN]) == 1
    assert shell_status(tmp_path, TOKEN) is False


def test_no_spawn_occurs_when_checks_are_blocked(monkeypatch, capsys):
    monkeypatch.setattr('desktopforge.session_launcher.check_environment', lambda *args, **kwargs:
        {'status': 'blocked', 'notice': 'fixture', 'blockers': ['No GUI account context']})
    monkeypatch.setattr('desktopforge.session_launcher.run_session', lambda *args, **kwargs: pytest.fail('blocked launch'))
    assert main(['--nested']) == 1
    assert 'No GUI account context' in capsys.readouterr().out


def test_trial_cancellation_after_start_verifies_shutdown(env, tmp_path):
    values = iter([False, False, False, True])
    assert trial(env, cancelled=lambda: next(values), readiness=lambda *args: True,
                 alive=lambda *args: True) == 130
    assert TrialUnit.instances[-1].stopped
    assert not (tmp_path / 'desktopforge/attempt.json').exists()


def test_precheck_reports_stale_marker_without_modifying_it(env, tmp_path):
    namespace = tmp_path / 'desktopforge'
    namespace.mkdir(mode=0o700)
    marker = namespace / 'attempt.json'
    marker.write_text('unfinished fixture')
    result = check_environment(env, nested=True, runner=versions, executable=lambda _: True)
    assert result['status'] == 'blocked'
    assert any('unfinished DesktopForge attempt' in item for item in result['blockers'])
    assert marker.read_text() == 'unfinished fixture'


def test_trial_skips_first_run_setup_without_touching_normal_profile(env, tmp_path):
    # Fresh temporary trials should open the shell, not an onboarding flow that
    # cannot persist across attempts. Disabling onboarding must not opt into telemetry.
    normal = tmp_path / '.config/noctalia/config.toml'
    normal.parent.mkdir(parents=True)
    normal.write_text('[shell]\nsetup_wizard_enabled = true\n')
    observed = []
    def validate(argv, **kwargs):
        if argv[:2] == ['/usr/bin/niri', 'validate']:
            profiles = list((tmp_path / 'desktopforge').glob('launch-*/config/noctalia/config.toml'))
            assert len(profiles) == 1
            observed.append(profiles[0].read_text())
        return reply()
    assert run_session(env, nested=True, runner=validate, session_factory=TrialUnit,
                       readiness=lambda *args: True, alive=lambda *args: True, sleep=lambda _: None) == 0
    assert 'setup_wizard_enabled = false' in observed[0]
    assert 'telemetry_enabled = false' in observed[0]
    assert normal.read_text() == '[shell]\nsetup_wizard_enabled = true\n'


def test_generated_config_binds_native_noctalia_app_launcher():
    text = config_text(Path('/tmp/fixture'), TOKEN)
    assert 'Mod+D { spawn "/usr/bin/noctalia" "msg" "panel-toggle" "launcher"; }' in text
    assert 'Mod+Space { spawn "/usr/bin/noctalia" "msg" "panel-toggle" "launcher"; }' in text
    assert 'spawn-sh' not in text


def test_diagnostics_read_only_captures_own_attempt_and_logs(env, tmp_path):
    from desktopforge.launcher_runtime import SessionLease
    from desktopforge.session_launcher import diagnose_session
    with SessionLease(tmp_path, 'desktopforge-niri-noctalia') as lease:
        profile = tmp_path / 'desktopforge' / ('launch-' + lease.attempt_id + '-fixture')
        (profile / 'cache/noctalia').mkdir(parents=True)
        (profile / 'shell.json').write_text(json.dumps({'token': lease.attempt_id, 'ready': True, 'exit_code': 0}))
        (profile / 'cache/noctalia/noctalia.log').write_text('fixture graphics initialization error')
        marker = tmp_path / 'desktopforge/attempt.json'
        before = marker.read_bytes()
        calls = []
        def readonly(argv, **kwargs):
            calls.append(argv)
            assert argv[0] in ('/usr/bin/systemctl', '/usr/bin/journalctl')
            assert 'start' not in argv and 'stop' not in argv
            return reply('LoadState=not-found\n') if 'show' in argv else reply('fixture journal')
        result = diagnose_session(env, runner=readonly)
        assert result['status'] == 'observed'
        assert result['unit'] == f'desktopforge-{lease.attempt_id}.service'
        assert result['profiles'][0]['noctalia_log'] == 'fixture graphics initialization error'
        assert result['journal'] == 'fixture journal'
        assert marker.read_bytes() == before
        lease.clean_after_verified_shutdown()


def test_diagnostics_does_not_borrow_another_account_context():
    from desktopforge.session_launcher import diagnose_session
    assert diagnose_session({})['status'] == 'unavailable'


def test_diagnostic_logs_do_not_follow_symlinks(env, tmp_path):
    from desktopforge.launcher_runtime import SessionLease
    from desktopforge.session_launcher import diagnose_session
    secret = tmp_path / 'not-a-log'
    secret.write_text('outside-file-must-not-be-read')
    with SessionLease(tmp_path, 'desktopforge-niri-noctalia') as lease:
        profile = tmp_path / 'desktopforge' / ('launch-' + lease.attempt_id + '-fixture')
        profile.mkdir()
        (profile / 'cache').symlink_to(tmp_path, target_is_directory=True)
        (profile / 'shell.json').symlink_to(secret)
        result = diagnose_session(env, runner=lambda *args, **kwargs: reply('LoadState=not-found\n'))
        assert 'outside-file-must-not-be-read' not in str(result)
        assert 'shell_record_error' in result['profiles'][0]
        lease.clean_after_verified_shutdown()


def test_diagnostics_entrypoint_never_runs_precheck_or_launcher(monkeypatch, capsys):
    monkeypatch.setattr('desktopforge.session_launcher.diagnose_session', lambda *args: {'status': 'fixture'})
    monkeypatch.setattr('desktopforge.session_launcher.check_environment', lambda *args, **kwargs: pytest.fail('precheck'))
    assert main(['--diagnose']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'fixture'
