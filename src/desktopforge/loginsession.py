#!/usr/bin/python3 -Is
"""DesktopForge login-session launcher (runs as the user, started by the display manager).

Usage: desktopforge-session PROFILE

Starts the profile's compositor as a uniquely named transient systemd user
service bound to graphical-session.target (so portals and XDG autostart work),
passing only an allowlist of login variables. It waits for the compositor to
exit or for logout, then stops the graphical session and cleans up exactly the
user-manager environment and runtime files the session introduced, leaving
anything that changed since then untouched.

Standard library only and no package imports, so it can be installed
root-owned and run in isolated mode.
"""
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time

PROFILES = {
    'niri-noctalia': {
        'unit': 'desktopforge-niri-noctalia.service',
        'argv': ['/usr/bin/niri', '--session', '--config', '/etc/desktopforge/sessions/niri-noctalia.kdl'],
        'desktop': 'niri',
        # Variables niri --session imports into the user manager.
        'published': ('WAYLAND_DISPLAY', 'DISPLAY', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'NIRI_SOCKET'),
        'socket_variable': 'NIRI_SOCKET',
        'outputs': ['/usr/bin/niri', 'msg', '--json', 'outputs'],
        'runtime_locks': ('noctalia-{display}.lock',),
    },
}
PASSED = ('XDG_SESSION_ID', 'XDG_SEAT', 'XDG_VTNR', 'XDG_SESSION_TYPE', 'XDG_SESSION_CLASS',
          'XDG_SESSION_DESKTOP', 'DESKTOP_SESSION', 'GDMSESSION', 'LANG', 'LANGUAGE')
LOCALE = re.compile(r'LC_[A-Z_]{1,20}')
VALUE = re.compile(r'[^\x00-\x1f\x7f]{0,512}')
SYSTEMCTL = '/usr/bin/systemctl'
SYSTEMD_RUN = '/usr/bin/systemd-run'
GRAPHICAL = 'graphical-session.target'


class LaunchRefused(Exception):
    pass


def select_environment(env, profile):
    """Allowlisted, validated login variables for the compositor unit."""
    chosen = {}
    for name, value in env.items():
        if (name in PASSED or LOCALE.fullmatch(name)) and VALUE.fullmatch(value):
            chosen[name] = value
    chosen['XDG_CURRENT_DESKTOP'] = profile['desktop']
    chosen['XDG_SESSION_TYPE'] = 'wayland'
    return dict(sorted(chosen.items()))


def unit_argv(profile, environment):
    """systemd-run invocation mirroring niri.service's graphical-session wiring."""
    argv = [SYSTEMD_RUN, '--user', f'--unit={profile["unit"]}', '--collect', '--quiet',
            '--service-type=notify', '--property=Slice=session.slice']
    for prop in (f'BindsTo={GRAPHICAL}', f'Before={GRAPHICAL}',
                 'Wants=graphical-session-pre.target', 'After=graphical-session-pre.target',
                 'Wants=xdg-desktop-autostart.target', 'Before=xdg-desktop-autostart.target'):
        argv.append(f'--property={prop}')
    argv += [f'--setenv={name}={value}' for name, value in environment.items()]
    return argv + ['--', *profile['argv']]


def parse_environment(text):
    values = {}
    for line in text.splitlines():
        name, sep, value = line.partition('=')
        if sep and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            values[name] = value
    return values


def cleanup_plan(names, before, published, current):
    """Decide per variable: unset, restore the pre-session value, or leave alone.

    Only values that still equal what this session published are touched.
    """
    unset, restore, left = [], {}, []
    for name in names:
        if name not in published:
            continue
        if current.get(name) != published[name]:
            left.append(name)  # changed or removed since: not ours any more
        elif name in before and before[name] != published[name]:
            restore[name] = before[name]
        elif name not in before:
            unset.append(name)
    return unset, restore, left


def lock_is_free(path):
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def stale_runtime_files(runtime_dir, display, profile, lock_free=lock_is_free):
    """Socket and lock files of this session's display whose locks nobody holds."""
    if not re.fullmatch(r'wayland-[0-9]{1,4}', display or ''):
        return []
    candidates = []
    lock = os.path.join(runtime_dir, display + '.lock')
    if os.path.lexists(lock) and lock_free(lock):
        candidates += [p for p in (os.path.join(runtime_dir, display), lock) if os.path.lexists(p)]
    for pattern in profile['runtime_locks']:
        path = os.path.join(runtime_dir, pattern.format(display=display))
        if os.path.lexists(path) and lock_free(path):
            candidates.append(path)
    return candidates


class Launcher:
    def __init__(self, profile, env, run=None, sleep=time.sleep, log=None, runtime_dir=None,
                 lock_free=lock_is_free, remove=os.unlink):
        self.profile, self.env = profile, env
        self.run = run or self._run
        self.sleep, self.log = sleep, log or (lambda m: print(f'desktopforge-session: {m}', flush=True))
        self.runtime_dir = runtime_dir or env.get('XDG_RUNTIME_DIR', '')
        self.lock_free, self.remove = lock_free, remove
        self.stop_requested = False

    @staticmethod
    def _run(argv, timeout=60, env=None):
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=timeout, env=env)
        return result.returncode, result.stdout

    def manager_environment(self):
        code, out = self.run([SYSTEMCTL, '--user', 'show-environment'])
        if code != 0:
            raise LaunchRefused('cannot read the user manager environment')
        return parse_environment(out)

    def unit_state(self):
        _code, out = self.run([SYSTEMCTL, '--user', 'show', '--property=ActiveState', '--value',
                               self.profile['unit']])
        return out.strip() or 'inactive'

    def is_active(self, unit):
        code, _out = self.run([SYSTEMCTL, '--user', 'is-active', '--quiet', unit])
        return code == 0

    def failed_units(self):
        code, out = self.run([SYSTEMCTL, '--user', 'list-units', '--state=failed', '--plain',
                              '--no-legend', '--no-pager'])
        return {line.split()[0] for line in out.splitlines() if line.strip()} if code == 0 else set()

    def belongs_to_graphical_session(self, unit):
        _code, out = self.run([SYSTEMCTL, '--user', 'show', '--property=PartOf', '--value', unit])
        return GRAPHICAL in out.split()

    def request_stop(self, *_args):
        self.stop_requested = True

    def has_outputs(self, published):
        socket = published.get(self.profile['socket_variable'])
        if not socket:
            return False
        env = {'PATH': '/usr/bin', self.profile['socket_variable']: socket}
        for _attempt in range(10):
            code, out = self.run(self.profile['outputs'], env=env)
            if code == 0:
                try:
                    if json.loads(out):
                        return True
                except ValueError:
                    pass
            self.sleep(0.5)
        return False

    def wait_published(self, before):
        names = self.profile['published']
        for _attempt in range(20):
            current = self.manager_environment()
            published = {n: current[n] for n in names if n in current and current.get(n) != before.get(n)}
            if 'WAYLAND_DISPLAY' in published:
                return published
            self.sleep(0.25)
        return {n: current[n] for n in names if n in current and current.get(n) != before.get(n)}

    def launch(self):
        unit = self.profile['unit']
        if self.is_active(unit):
            raise LaunchRefused(f'{unit} is already running')
        if self.is_active(GRAPHICAL):
            raise LaunchRefused('another graphical session is active for this user')
        before = self.manager_environment()
        self.failed_before = self.failed_units()
        environment = select_environment(self.env, self.profile)
        self.log(f'starting {unit} with {", ".join(environment)}')
        code, _out = self.run(unit_argv(self.profile, environment), timeout=90)
        published = {}
        try:
            if code != 0:
                self.log(f'{unit} failed to start (status {code})')
                return 1
            published = self.wait_published(before)
            if not self.has_outputs(published):
                self.log('the compositor has no usable display (no hardware-accelerated renderer?); '
                         'ending the session so the login screen returns')
                return 1
            self.log('session ready; published ' + ', '.join(sorted(published)))
            while not self.stop_requested and self.unit_state() in ('active', 'activating', 'reloading'):
                self.sleep(1)
            return 0
        finally:
            self.cleanup(before, published)

    def cleanup(self, before, published):
        unit = self.profile['unit']
        if self.unit_state() not in ('inactive', 'failed'):
            self.run([SYSTEMCTL, '--user', 'stop', unit], timeout=60)
        if not self.is_active(unit):
            self.run([SYSTEMCTL, '--user', 'stop', GRAPHICAL, 'graphical-session-pre.target'], timeout=60)
        else:
            self.log(f'{unit} did not stop; environment cleanup skipped')
            return
        # Graphical-session services (e.g. portals) often exit with an error when the
        # compositor goes away before the target stops them. Reset only those that
        # failed during this session; the journal keeps their messages.
        new = sorted(u for u in self.failed_units() - getattr(self, 'failed_before', set())
                     if self.belongs_to_graphical_session(u))
        if new:
            self.run([SYSTEMCTL, '--user', 'reset-failed', *new])
        self.log(f'reset failed graphical-session units: {new or "none"}')
        try:
            current = self.manager_environment()
        except LaunchRefused:
            self.log('user manager unavailable; nothing to clean in it')
            current = None
        if current is not None:
            unset, restore, left = cleanup_plan(self.profile['published'], before, published, current)
            if unset:
                self.run([SYSTEMCTL, '--user', 'unset-environment', *unset])
            if restore:
                self.run([SYSTEMCTL, '--user', 'set-environment', *[f'{k}={v}' for k, v in restore.items()]])
            self.log(f'environment: unset {unset or "none"}, restored {sorted(restore) or "none"}, '
                     f'left changed values {left or "none"}')
        removed = []
        for path in stale_runtime_files(self.runtime_dir, published.get('WAYLAND_DISPLAY'), self.profile,
                                        self.lock_free):
            try:
                self.remove(path)
                removed.append(os.path.basename(path))
            except OSError:
                pass
        self.log(f'removed runtime files: {removed or "none"}')


def main(argv=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ) if env is None else env
    if len(argv) != 1 or argv[0] not in PROFILES:
        print(f'usage: desktopforge-session {{{",".join(PROFILES)}}}', file=sys.stderr)
        return 2
    launcher = Launcher(PROFILES[argv[0]], env)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, launcher.request_stop)
    try:
        return launcher.launch()
    except (LaunchRefused, subprocess.SubprocessError, OSError) as exc:
        launcher.log(f'not started: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
