"""Login-session launcher: environment allowlist, unit wiring and ownership-aware cleanup."""
import json

import pytest

from desktopforge import loginsession as ls

PROFILE = ls.PROFILES['niri-noctalia']
LOGIN_ENV = {'XDG_SESSION_ID': '13', 'XDG_SEAT': 'seat0', 'XDG_VTNR': '2', 'XDG_SESSION_TYPE': 'wayland',
             'XDG_SESSION_CLASS': 'user', 'GDMSESSION': 'desktopforge-niri-noctalia', 'LANG': 'en_US.UTF-8',
             'LC_TIME': 'en_GB.UTF-8', 'XDG_RUNTIME_DIR': '/run/user/1000', 'HOME': '/home/u',
             'SSH_AUTH_SOCK': '/tmp/agent', 'LD_PRELOAD': '/tmp/evil.so', 'PATH': '/home/u/bin:/usr/bin',
             'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus', 'XDG_CURRENT_DESKTOP': 'GNOME'}


def test_only_allowlisted_login_variables_reach_the_compositor():
    chosen = ls.select_environment(LOGIN_ENV, PROFILE)
    assert chosen == {'GDMSESSION': 'desktopforge-niri-noctalia', 'LANG': 'en_US.UTF-8', 'LC_TIME': 'en_GB.UTF-8',
                      'XDG_CURRENT_DESKTOP': 'niri', 'XDG_SEAT': 'seat0', 'XDG_SESSION_CLASS': 'user',
                      'XDG_SESSION_ID': '13', 'XDG_SESSION_TYPE': 'wayland', 'XDG_VTNR': '2'}


def test_values_with_control_characters_are_dropped():
    chosen = ls.select_environment({'LANG': 'C\nEvil=1', 'XDG_SEAT': 'seat0'}, PROFILE)
    assert 'LANG' not in chosen and chosen['XDG_SEAT'] == 'seat0'


def test_unit_is_wired_like_niri_service_without_the_shared_unit_name():
    argv = ls.unit_argv(PROFILE, {'XDG_SESSION_ID': '13'})
    assert argv[:3] == ['/usr/bin/systemd-run', '--user', '--unit=desktopforge-niri-noctalia.service']
    for prop in ('BindsTo=graphical-session.target', 'Before=graphical-session.target',
                 'Wants=xdg-desktop-autostart.target', 'Slice=session.slice'):
        assert f'--property={prop}' in argv
    assert '--service-type=notify' in argv and '--setenv=XDG_SESSION_ID=13' in argv
    assert argv[argv.index('--') + 1:] == ['/usr/bin/niri', '--session', '--config',
                                          '/etc/desktopforge/sessions/niri-noctalia.kdl']
    assert 'niri.service' not in ' '.join(argv)


NAMES = ('WAYLAND_DISPLAY', 'DISPLAY', 'NIRI_SOCKET', 'XDG_CURRENT_DESKTOP')


def test_cleanup_unsets_new_values_and_restores_previous_ones():
    before = {'XDG_CURRENT_DESKTOP': 'GNOME'}
    published = {'WAYLAND_DISPLAY': 'wayland-1', 'NIRI_SOCKET': '/run/s', 'XDG_CURRENT_DESKTOP': 'niri'}
    unset, restore, left = ls.cleanup_plan(NAMES, before, published, dict(published))
    assert unset == ['WAYLAND_DISPLAY', 'NIRI_SOCKET'] and restore == {'XDG_CURRENT_DESKTOP': 'GNOME'} and left == []


def test_cleanup_leaves_values_someone_else_changed():
    published = {'WAYLAND_DISPLAY': 'wayland-1', 'DISPLAY': ':0'}
    current = {'WAYLAND_DISPLAY': 'wayland-0'}  # another session took over; DISPLAY removed
    unset, restore, left = ls.cleanup_plan(NAMES, {}, published, current)
    assert unset == [] and restore == {} and left == ['WAYLAND_DISPLAY', 'DISPLAY']


def test_runtime_files_removed_only_when_lock_is_free(tmp_path):
    for name in ('wayland-1', 'wayland-1.lock', 'noctalia-wayland-1.lock', 'wayland-0', 'wayland-0.lock'):
        (tmp_path / name).write_text('')
    free = ls.stale_runtime_files(str(tmp_path), 'wayland-1', PROFILE, lock_free=lambda p: True)
    assert sorted(p.rsplit('/', 1)[1] for p in free) == ['noctalia-wayland-1.lock', 'wayland-1', 'wayland-1.lock']
    assert ls.stale_runtime_files(str(tmp_path), 'wayland-1', PROFILE, lock_free=lambda p: False) == []
    assert ls.stale_runtime_files(str(tmp_path), '../etc', PROFILE, lock_free=lambda p: True) == []


def test_real_flock_detects_a_held_lock(tmp_path):
    import fcntl
    lock = tmp_path / 'wayland-1.lock'
    lock.write_text('')
    assert ls.lock_is_free(str(lock))
    with open(lock) as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert not ls.lock_is_free(str(lock))


class FakeManager:
    """Fake systemd user manager plus a niri that publishes variables when started."""

    def __init__(self, before=None, outputs=True, start_status=0, graphical_active=False, run_for=2):
        self.env = dict(before or {})
        self.outputs, self.start_status = outputs, start_status
        self.graphical_active, self.run_for = graphical_active, run_for
        self.unit, self.calls = 'inactive', []
        self.failed = {'old-broken.service'}
        self.part_of = {'xdg-desktop-portal-gnome.service': 'graphical-session.target',
                        'old-broken.service': 'graphical-session.target', 'backup.service': ''}

    def __call__(self, argv, timeout=60, env=None):
        self.calls.append(argv)
        if argv[0] == ls.SYSTEMD_RUN:
            if self.start_status:
                self.unit = 'failed'
                return self.start_status, ''
            self.unit = 'active'
            self.env.update({'WAYLAND_DISPLAY': 'wayland-1', 'DISPLAY': ':0', 'XDG_CURRENT_DESKTOP': 'niri',
                             'XDG_SESSION_TYPE': 'wayland', 'NIRI_SOCKET': '/run/user/1000/niri.sock'})
            return 0, ''
        if argv[0] == '/usr/bin/niri':
            return 0, json.dumps({'Virtual-1': {}} if self.outputs else {})
        verb = argv[2]
        if verb == 'show-environment':
            return 0, ''.join(f'{k}={v}\n' for k, v in self.env.items())
        if verb == 'is-active':
            unit = argv[-1]
            if unit == ls.GRAPHICAL:
                return (0 if self.graphical_active else 3), ''
            return (0 if self.unit == 'active' else 3), ''
        if verb == 'list-units':
            return 0, ''.join(f'{u} loaded failed failed x\n' for u in sorted(self.failed))
        if verb == 'reset-failed':
            self.failed -= set(argv[3:])
            return 0, ''
        if verb == 'show' and argv[3] == '--property=PartOf':
            return 0, self.part_of.get(argv[-1], '') + '\n'
        if verb == 'show':
            if self.unit == 'active':
                self.run_for -= 1
                if self.run_for < 0:
                    self.unit = 'inactive'  # user logged out of niri
            return 0, self.unit + '\n'
        if verb == 'stop':
            if PROFILE['unit'] in argv:
                self.unit = 'inactive'
            if ls.GRAPHICAL in argv:  # portals lost their compositor and failed
                self.failed |= {'xdg-desktop-portal-gnome.service', 'backup.service'}
            return 0, ''
        if verb == 'unset-environment':
            for name in argv[3:]:
                self.env.pop(name, None)
            return 0, ''
        if verb == 'set-environment':
            for item in argv[3:]:
                k, _, v = item.partition('=')
                self.env[k] = v
            return 0, ''
        raise AssertionError(argv)


def launcher(manager, tmp_path, **kwargs):
    logs = []
    lf = ls.Launcher(PROFILE, LOGIN_ENV, run=manager, sleep=lambda s: None, log=logs.append,
                     runtime_dir=str(tmp_path), lock_free=lambda p: True, **kwargs)
    return lf, logs


def test_full_session_cleans_exactly_what_it_published(tmp_path):
    for name in ('wayland-1', 'wayland-1.lock', 'noctalia-wayland-1.lock'):
        (tmp_path / name).write_text('')
    manager = FakeManager(before={'PATH': '/usr/bin', 'XDG_CURRENT_DESKTOP': 'GNOME'})
    lf, logs = launcher(manager, tmp_path)
    assert lf.launch() == 0
    assert manager.env == {'PATH': '/usr/bin', 'XDG_CURRENT_DESKTOP': 'GNOME'}
    assert list(tmp_path.iterdir()) == []
    assert any(c[2] == 'stop' and ls.GRAPHICAL in c for c in manager.calls)


def test_refuses_when_another_graphical_session_is_active(tmp_path):
    manager = FakeManager(graphical_active=True)
    lf, _ = launcher(manager, tmp_path)
    with pytest.raises(ls.LaunchRefused, match='another graphical session'):
        lf.launch()
    assert not any(c[0] == ls.SYSTEMD_RUN for c in manager.calls)


def test_no_display_ends_the_session_and_cleans_up(tmp_path):
    manager = FakeManager(outputs=False)
    lf, logs = launcher(manager, tmp_path)
    assert lf.launch() == 1
    assert manager.unit == 'inactive' and 'WAYLAND_DISPLAY' not in manager.env
    assert any('no usable display' in m for m in logs)


def test_failed_start_returns_to_login_screen_without_touching_environment(tmp_path):
    manager = FakeManager(before={'WAYLAND_DISPLAY': 'wayland-0'}, start_status=1)
    lf, _ = launcher(manager, tmp_path)
    assert lf.launch() == 1
    assert manager.env == {'WAYLAND_DISPLAY': 'wayland-0'}


def test_logout_signal_stops_the_compositor_unit(tmp_path):
    manager = FakeManager(run_for=10**6)
    lf, _ = launcher(manager, tmp_path)
    original = manager.__call__

    def run(argv, **kw):
        if argv[2:3] == ['show'] and manager.unit == 'active':
            lf.request_stop()  # SIGTERM from the display manager at logout
        return original(argv, **kw)
    lf.run = run
    assert lf.launch() == 0
    assert any(c[2] == 'stop' and PROFILE['unit'] in c for c in manager.calls)
    assert 'NIRI_SOCKET' not in manager.env


def test_main_rejects_unknown_profiles(capsys):
    assert ls.main(['../../bin/sh'], {}) == 2
    assert ls.main([], {}) == 2


def test_launcher_is_self_contained_for_root_owned_install():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(ls.__file__).read_text())
    stdlib = {'fcntl', 'json', 'os', 're', 'signal', 'subprocess', 'sys', 'time'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {a.name for a in node.names} <= stdlib
        elif isinstance(node, ast.ImportFrom):
            raise AssertionError('launcher must not import from packages')


def test_only_graphical_session_units_that_failed_during_the_session_are_reset(tmp_path):
    manager = FakeManager()
    lf, logs = launcher(manager, tmp_path)
    assert lf.launch() == 0
    # The pre-existing failure and an unrelated unit stay visible as failed.
    assert manager.failed == {'old-broken.service', 'backup.service'}
    assert "reset failed graphical-session units: ['xdg-desktop-portal-gnome.service']" in logs


# ---- per-user launch outcomes (option A: report, never reset the remembered session) ----

def test_launch_outcomes_are_recorded_privately_and_bounded(tmp_path):
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}
    for i in range(12):
        assert ls.record_launch(env, 'niri-noctalia', 'no-display', f'attempt {i}', now=1794800000 + i)
    path = tmp_path / 'state/desktopforge/launches/niri-noctalia.json'
    data = json.loads(path.read_text())
    assert data['session_id'] == 'desktopforge-niri-noctalia'
    assert len(data['events']) == ls.MAX_EVENTS and data['events'][-1]['detail'] == 'attempt 11'
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    assert oct((tmp_path / 'state/desktopforge/launches').stat().st_mode & 0o777) == '0o700'


def test_launch_record_never_follows_symlinks_or_relative_paths(tmp_path):
    directory = tmp_path / 'state/desktopforge/launches'
    directory.mkdir(parents=True)
    victim = tmp_path / 'victim'
    victim.write_text('keep')
    (directory / 'niri-noctalia.json').symlink_to(victim)
    assert ls.record_launch({'XDG_STATE_HOME': str(tmp_path / 'state')}, 'niri-noctalia', 'started', 'x')
    assert victim.read_text() == 'keep' and not (directory / 'niri-noctalia.json').is_symlink()
    assert not ls.record_launch({'XDG_STATE_HOME': 'relative', 'HOME': 'also-relative'}, 'niri-noctalia', 'x', 'y')
    assert not ls.record_launch({'XDG_STATE_HOME': str(tmp_path)}, '../../evil', 'x', 'y')


def test_launcher_reports_outcomes(tmp_path):
    seen = []
    for manager, expected in ((FakeManager(), 'started'), (FakeManager(outputs=False), 'no-display'),
                              (FakeManager(start_status=1), 'start-failed')):
        lf, _ = launcher(manager, tmp_path, record=lambda result, detail: seen.append(result))
        lf.launch()
        assert seen[-1] == expected


def test_launcher_never_touches_the_remembered_login_session():
    source = open(ls.__file__).read()
    assert 'Accounts' not in source and 'SetSession' not in source
