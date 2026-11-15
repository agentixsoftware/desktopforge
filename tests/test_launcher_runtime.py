import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from desktopforge.launcher_runtime import (LauncherError, OwnedChild, PinnedConfig, RecoveryRequired,
                                          SessionLease, child_environment)

CHILD = Path(__file__).parent / 'fixtures/launcher_child.py'
SRC = Path(__file__).parents[1] / 'src'
SESSION = 'desktopforge-niri-noctalia'


def wait_ready(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(.01)
    pytest.fail('Fixture child did not become ready')


def test_real_user_lease_is_global_and_lock_inode_persists(tmp_path):
    with SessionLease(tmp_path, SESSION) as lease:
        marker = tmp_path / 'desktopforge/attempt.json'
        info = json.loads(marker.read_text())
        assert info['session_id'] == SESSION
        assert info['attempt_id'] == lease.attempt_id
        assert info['launcher_pid'] == os.getpid()
        with pytest.raises(LauncherError, match='holds the user lock'):
            with SessionLease(tmp_path, 'desktopforge-niri-ryoku'):
                pytest.fail('Concurrent session acquired a global user lease')
        lock_inode = (tmp_path / 'desktopforge/session.lock').stat().st_ino
        lease.clean_after_verified_shutdown()
        assert not marker.exists()
    with SessionLease(tmp_path, SESSION) as lease:
        assert (tmp_path / 'desktopforge/session.lock').stat().st_ino == lock_inode
        lease.clean_after_verified_shutdown()


def test_lock_is_enforced_between_processes(tmp_path):
    code = '''
from pathlib import Path
import sys
from desktopforge.launcher_runtime import LauncherError, SessionLease
try:
    with SessionLease(Path(sys.argv[1]), 'desktopforge-niri-ryoku'):
        raise SystemExit(8)
except LauncherError:
    raise SystemExit(0)
'''
    with SessionLease(tmp_path, SESSION) as lease:
        result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                                env={'PYTHONPATH': str(SRC)}, timeout=5)
        assert result.returncode == 0
        lease.clean_after_verified_shutdown()


def test_crashed_launcher_leaves_marker_and_refuses_takeover(tmp_path):
    code = '''
from pathlib import Path
import os, sys
from desktopforge.launcher_runtime import SessionLease
lease = SessionLease(Path(sys.argv[1]), 'desktopforge-niri-noctalia')
lease.__enter__()
os._exit(7)
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            env={'PYTHONPATH': str(SRC)}, timeout=5)
    assert result.returncode == 7
    marker = tmp_path / 'desktopforge/attempt.json'
    before = marker.read_bytes()
    with pytest.raises(RecoveryRequired):
        with SessionLease(tmp_path, SESSION):
            pytest.fail('Unfinished marker was ignored')
    assert marker.read_bytes() == before


def test_exception_does_not_silently_clear_marker(tmp_path):
    with pytest.raises(ValueError):
        with SessionLease(tmp_path, SESSION):
            raise ValueError('fixture failure')
    with pytest.raises(RecoveryRequired):
        with SessionLease(tmp_path, SESSION):
            pass


@pytest.mark.parametrize('location', ['runtime', 'namespace', 'lock', 'marker'])
def test_symlink_targets_are_never_written(tmp_path, location):
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    target = tmp_path / 'target'
    target.write_text('untouched')
    if location == 'runtime':
        alias = tmp_path / 'alias'
        alias.symlink_to(runtime, target_is_directory=True)
        runtime = alias
    elif location == 'namespace':
        (runtime / 'desktopforge').symlink_to(target)
    else:
        namespace = runtime / 'desktopforge'
        namespace.mkdir(mode=0o700)
        (namespace / ('session.lock' if location == 'lock' else 'attempt.json')).symlink_to(target)
    with pytest.raises((OSError, LauncherError)):
        with SessionLease(runtime, SESSION):
            pytest.fail('Symlink should not be followed')
    assert target.read_text() == 'untouched'


def test_runtime_must_be_private_and_path_must_not_traverse(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(LauncherError, match='private'):
        with SessionLease(tmp_path, SESSION):
            pass
    with pytest.raises(LauncherError, match='absolute'):
        with SessionLease(Path('relative'), SESSION):
            pass


def test_hardlinked_lock_is_rejected(tmp_path):
    namespace = tmp_path / 'desktopforge'
    namespace.mkdir(mode=0o700)
    original = tmp_path / 'original'
    original.write_text('untouched')
    original.chmod(0o600)
    os.link(original, namespace / 'session.lock')
    with pytest.raises(LauncherError, match='hard-linked'):
        with SessionLease(tmp_path, SESSION):
            pass
    assert original.read_text() == 'untouched'


def test_marker_replacement_refuses_cleanup(tmp_path):
    with SessionLease(tmp_path, SESSION) as lease:
        marker = tmp_path / 'desktopforge/attempt.json'
        marker.rename(marker.with_name('retained-original'))
        marker.write_text('replacement')
        with pytest.raises(RecoveryRequired, match='identity changed'):
            lease.clean_after_verified_shutdown()
        assert marker.read_text() == 'replacement'


def test_real_child_receives_isolated_environment_without_changing_parent(tmp_path):
    ready = tmp_path / 'ready'
    original = dict(os.environ)
    parent = {'NIRI_CONFIG': '/prior/config', 'UNRELATED': 'preserved'}
    env = child_environment(parent, tmp_path / 'niri.kdl')
    child = OwnedChild.start([sys.executable, str(CHILD), 'exit', str(ready)], env)
    try:
        assert child.wait(5) == 7
        info = wait_ready(ready)
        assert info['pid'] == info['sid'] == child.pid
        assert info['config'] == str(tmp_path / 'niri.kdl')
        assert info['unrelated'] == 'preserved'
        assert parent['NIRI_CONFIG'] == '/prior/config'
        assert dict(os.environ) == original
        assert child.stop() == 7  # Bound handle never signals another PID after exit.
    finally:
        child.stop()
        child.close()


@pytest.mark.parametrize('mode,expected', [('sleep', -signal.SIGTERM), ('ignore-term', -signal.SIGKILL)])
def test_real_child_stop_uses_bound_handle_and_escalation(tmp_path, mode, expected):
    ready = tmp_path / 'ready'
    child = OwnedChild.start([sys.executable, str(CHILD), mode, str(ready)], {})
    try:
        wait_ready(ready)
        with pytest.raises(RecoveryRequired, match='running child'):
            child.close()
        assert child.stop(grace=.1, kill_timeout=5) == expected
    finally:
        child.stop(kill_timeout=5)
        child.close()
    child.close()  # Closing a reaped handle is idempotent.


def test_terminating_one_child_does_not_touch_another(tmp_path):
    one = OwnedChild.start([sys.executable, str(CHILD), 'sleep', str(tmp_path / 'one')], {})
    two = OwnedChild.start([sys.executable, str(CHILD), 'sleep', str(tmp_path / 'two')], {})
    try:
        wait_ready(tmp_path / 'one')
        wait_ready(tmp_path / 'two')
        one.stop()
        with pytest.raises(subprocess.TimeoutExpired):
            two.wait(.05)
    finally:
        one.stop()
        two.stop()
        one.close()
        two.close()


def test_lease_and_child_integration_uses_only_fixture_runtime(tmp_path):
    with SessionLease(tmp_path, SESSION) as lease:
        child = OwnedChild.start([sys.executable, str(CHILD), 'exit', str(tmp_path / 'ready')],
                                 child_environment({}, tmp_path / 'niri.kdl'))
        try:
            assert child.wait(5) == 7
        finally:
            child.stop()
            child.close()
        # This known fixture has no descendants; no desktop/session claim is made.
        lease.clean_after_verified_shutdown()
    assert not (tmp_path / 'desktopforge/attempt.json').exists()


@pytest.mark.parametrize('argv', ['echo unsafe', ['relative'], [], ['/bin/echo', '\x00']])
def test_invalid_argv_is_rejected_before_spawn(argv):
    with pytest.raises(LauncherError):
        OwnedChild.start(argv, {})


def test_pidfd_failure_is_detected_before_spawn(monkeypatch):
    def unsupported(*args):
        raise OSError('fixture: pidfd unavailable')
    def forbidden(*args, **kwargs):
        pytest.fail('Child was spawned despite unsupported pidfd')
    monkeypatch.setattr(os, 'pidfd_open', unsupported)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with pytest.raises(OSError):
        OwnedChild.start([sys.executable, '-c', 'pass'], {})


def test_cli_still_exposes_no_launch_command(capsys):
    from desktopforge.cli import main
    with pytest.raises(SystemExit) as exc:
        main(['launch'])
    assert exc.value.code == 2
    assert 'invalid choice' in capsys.readouterr().err


def test_in_place_marker_edit_is_not_deleted(tmp_path):
    with SessionLease(tmp_path, SESSION) as lease:
        marker = tmp_path / 'desktopforge/attempt.json'
        marker.write_text('{"attempt_id": "another-attempt"}')
        with pytest.raises(RecoveryRequired, match='content changed'):
            lease.clean_after_verified_shutdown()
        assert marker.exists()


def test_nonprivate_namespace_is_not_repaired(tmp_path):
    namespace = tmp_path / 'desktopforge'
    namespace.mkdir(mode=0o755)
    with pytest.raises(LauncherError, match='private'):
        with SessionLease(tmp_path, SESSION):
            pass
    assert namespace.stat().st_mode & 0o777 == 0o755
    assert not (namespace / 'attempt.json').exists()


def test_fifo_lock_is_rejected_without_blocking(tmp_path):
    namespace = tmp_path / 'desktopforge'
    namespace.mkdir(mode=0o700)
    os.mkfifo(namespace / 'session.lock', mode=0o600)
    with pytest.raises(LauncherError, match='private'):
        with SessionLease(tmp_path, SESSION):
            pass


def test_pidfd_acquisition_failure_reaps_only_new_child(tmp_path, monkeypatch):
    actual = os.pidfd_open
    calls = 0
    spawned_pid = None
    def fail_for_child(pid, flags=0):
        nonlocal calls, spawned_pid
        calls += 1
        if calls == 2:
            spawned_pid = pid
            raise OSError('fixture post-spawn failure')
        return actual(pid, flags)
    monkeypatch.setattr(os, 'pidfd_open', fail_for_child)
    with pytest.raises(OSError, match='post-spawn'):
        OwnedChild.start([sys.executable, str(CHILD), 'sleep', str(tmp_path / 'ready')], {})
    assert spawned_pid is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(spawned_pid, os.WNOHANG)


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan'), True])
def test_invalid_stop_timeouts_never_signal_child(tmp_path, value):
    child = OwnedChild.start([sys.executable, str(CHILD), 'sleep', str(tmp_path / 'ready')], {})
    try:
        wait_ready(tmp_path / 'ready')
        with pytest.raises(LauncherError, match='Timeout'):
            child.stop(grace=value)
        with pytest.raises(subprocess.TimeoutExpired):
            child.wait(.02)
    finally:
        child.stop()
        child.close()


def test_runtime_markers_never_capture_environment_or_command(tmp_path, monkeypatch):
    monkeypatch.setenv('DESKTOPFORGE_RUNTIME_SECRET_FIXTURE', 'never-record-this')
    with SessionLease(tmp_path, SESSION) as lease:
        text = (tmp_path / 'desktopforge/attempt.json').read_text()
        assert 'never-record-this' not in text
        assert set(json.loads(text)) == {'schema_version', 'session_id', 'attempt_id', 'launcher_pid'}
        lease.clean_after_verified_shutdown()


def test_model_and_runtime_are_separate_from_read_only_cli(monkeypatch, capsys):
    from desktopforge.cli import main
    def forbidden(*args, **kwargs):
        pytest.fail('Read-only CLI invoked launcher runtime')
    monkeypatch.setattr(SessionLease, '__enter__', forbidden)
    monkeypatch.setattr(OwnedChild, 'start', forbidden)
    assert main(['detect', '--json']) == 0
    capsys.readouterr()
    assert main(['list', '--json']) == 0
    capsys.readouterr()
    assert main(['plan', '--compositor', 'niri', '--shell', 'noctalia', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['executable'] is False



def config_fixture(tmp_path):
    base = tmp_path / 'config'
    base.mkdir(mode=0o755)
    folder = base
    for name in ('desktopforge', 'sessions', SESSION):
        folder = folder / name
        folder.mkdir(mode=0o700)
    config = folder / 'niri.kdl'
    config.write_text('original-fixture-content')
    config.chmod(0o600)
    return base, config


def test_child_reads_pinned_inode_after_path_replacement(tmp_path):
    base, path = config_fixture(tmp_path)
    with PinnedConfig(base, SESSION) as config:
        path.rename(path.with_name('original.kdl'))
        path.write_text('replacement-must-not-be-read')
        child = OwnedChild.start([sys.executable, str(CHILD), 'read-config', str(tmp_path / 'ready')],
                                 {'UNRELATED': 'preserved'}, config=config)
        try:
            assert child.wait(5) == 7
            info = wait_ready(tmp_path / 'ready')
            assert info['config_content'] == 'original-fixture-content'
            assert info['unrelated'] == 'preserved'
            assert info['config'].startswith('/proc/self/fd/')
        finally:
            child.stop()
            child.close()
    with pytest.raises(LauncherError, match='not pinned'):
        config.fileno()


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'hardlink', 'nonprivate'])
def test_unsafe_config_files_are_rejected_without_changes(tmp_path, kind):
    base, path = config_fixture(tmp_path)
    target = path.with_name('target')
    if kind == 'nonprivate':
        path.chmod(0o644)
    else:
        path.rename(target)
        if kind == 'symlink':
            path.symlink_to(target)
        elif kind == 'hardlink':
            os.link(target, path)
        else:
            os.mkfifo(path, mode=0o600)
    with pytest.raises((OSError, LauncherError)):
        with PinnedConfig(base, SESSION):
            pytest.fail('Unsafe config was accepted')
    if target.exists():
        assert target.read_text() == 'original-fixture-content'


def test_missing_config_is_not_created(tmp_path):
    base = tmp_path / 'missing'
    with pytest.raises(OSError):
        with PinnedConfig(base, SESSION):
            pass
    assert not base.exists()
