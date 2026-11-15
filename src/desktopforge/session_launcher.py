"""Runnable experimental Niri/Noctalia launcher; no installation or shared units.

--check is read-only. Actual starts are explicit and use a unique transient user
service, private D-Bus/configuration, and direct Niri without --session imports.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping

from .launcher_runtime import LauncherError, RecoveryRequired, SessionLease, _open_directory
from .transient_session import TransientSession, cgroup_path, run_command

SESSION_ID = 'desktopforge-niri-noctalia'
TOOLS = ('niri', 'noctalia', 'systemctl', 'systemd-run', 'dbus-run-session', 'env')


def _safe(value: str) -> str:
    if any(ord(char) < 32 for char in value) or '%' in value:
        raise LauncherError('Control characters and percent specifiers are not accepted in launch paths/environment')
    return value


def config_text(directory: Path, token: str, terminal: str | None = None) -> str:
    def quote(text: str) -> str:
        return json.dumps(_safe(text), ensure_ascii=False)
    worker = f'spawn-at-startup {quote(sys.executable)} "-m" "desktopforge.session_worker" {quote(str(directory))} {quote(token)}'
    terminal_bind = '' if terminal is None else f'Mod+Return {{ spawn {quote(terminal)}; }}'
    return f'''// Generated DesktopForge trial configuration; existing configs are not included.
input {{
    mod-key "Super"
    mod-key-nested "Alt"
    keyboard {{ xkb {{ }}; }}
    touchpad {{ tap; natural-scroll; }}
}}
layout {{ gaps 8; default-column-width {{ proportion 0.5; }}; }}
hotkey-overlay {{ skip-at-startup; }}
xwayland-satellite {{ off; }}
{worker}
binds {{
    Mod+Shift+E {{ quit; }}
    Mod+Q {{ close-window; }}
    Mod+D {{ spawn "/usr/bin/noctalia" "msg" "panel-toggle" "launcher"; }}
    Mod+Space {{ spawn "/usr/bin/noctalia" "msg" "panel-toggle" "launcher"; }}
    Mod+Left {{ focus-column-left; }}
    Mod+Right {{ focus-column-right; }}
    Mod+Up {{ focus-window-up; }}
    Mod+Down {{ focus-window-down; }}
    Mod+F {{ maximize-column; }}
    Mod+Shift+F {{ fullscreen-window; }}
    {terminal_bind}
}}
'''


def validate_config(text: str, runner: Callable = run_command) -> None:
    fd = os.memfd_create('desktopforge-config', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, text.encode())
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL)
        reply = runner(['/usr/bin/niri', 'validate', '--config', f'/proc/self/fd/{fd}'], pass_fds=(fd,))
        if reply.returncode:
            raise LauncherError(f'Generated Niri config is invalid: {reply.stderr.strip()[:500]}')
    finally:
        os.close(fd)


def check_environment(env: Mapping[str, str], *, nested: bool, runner: Callable = run_command,
                      executable: Callable = lambda path: os.access(path, os.X_OK)) -> dict:
    blockers = []
    versions = {}
    for name in TOOLS:
        if not executable('/usr/bin/' + name):
            blockers.append(f'Missing /usr/bin/{name}; install dependencies separately before launching.')
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        blockers.append('Launch as an ordinary logged-in user, without sudo.')
    runtime = env.get('XDG_RUNTIME_DIR', '')
    home = env.get('HOME', '')
    for label, value in (('XDG_RUNTIME_DIR', runtime), ('HOME', home)):
        if not value or not Path(value).is_absolute():
            blockers.append(f'{label} must identify the actual launch account using an absolute path.')
        else:
            _safe(value)
    if home and Path(home).is_absolute():
        try:
            fd = _open_directory(Path(home), private=False)
            os.close(fd)
        except (OSError, LauncherError):
            blockers.append('HOME must belong to the launch account and must not be writable by other users.')
    if runtime:
        try:
            fd = _open_directory(Path(runtime))
            os.close(fd)
        except (OSError, LauncherError):
            blockers.append('XDG_RUNTIME_DIR must be private, owned by the launch user and free of symlink components.')
        try:
            directory = _open_directory(Path(runtime) / 'desktopforge')
        except FileNotFoundError:
            pass
        except (OSError, LauncherError):
            blockers.append('Existing DesktopForge runtime namespace is not safely inspectable.')
        else:
            try:
                os.stat('attempt.json', dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                blockers.append('An unfinished DesktopForge attempt exists; review its diagnostic unit before retrying.')
            finally:
                os.close(directory)
    if nested:
        display = env.get('WAYLAND_DISPLAY', '')
        if not display or not runtime:
            blockers.append('Nested mode requires the logged-in Wayland account and its WAYLAND_DISPLAY.')
        else:
            _safe(display)
            path = Path(display) if Path(display).is_absolute() else Path(runtime) / display
            try:
                info = path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError('not an owned socket')
            except OSError:
                blockers.append('The parent Wayland socket is missing, not owned by this user, or not a socket.')
    else:
        if env.get('WAYLAND_DISPLAY') or env.get('DISPLAY'):
            blockers.append('Standalone mode requires a fresh local TTY login, outside any graphical session.')
        session = env.get('XDG_SESSION_ID', '')
        if not re.fullmatch('[A-Za-z0-9_-]+', session):
            blockers.append('Standalone mode requires a logind session ID from a local TTY login.')
        else:
            reply = runner(['/usr/bin/loginctl', 'show-session', session, '--property=Type,Active,Remote,User'])
            fields = dict(line.split('=', 1) for line in reply.stdout.splitlines() if '=' in line)
            if reply.returncode or any(fields.get(k) != v for k, v in
                {'Type': 'tty', 'Active': 'yes', 'Remote': 'no', 'User': str(os.getuid())}.items()):
                blockers.append('Standalone launch requires an active local TTY session owned by this account.')
    if not blockers:
        for tool, pattern in (('niri', r'\bniri\s+(26\.04)(?:\D|$)'), ('noctalia', r'\b(?:noctalia\s+v?|v)(5\.[0-9]+(?:\.[0-9]+)?)')):
            reply = runner(['/usr/bin/' + tool, '--version'])
            version = (reply.stdout + reply.stderr).strip()
            versions[tool] = version[:100]
            if reply.returncode or not re.search(pattern, version, re.IGNORECASE):
                blockers.append(f'{tool} version is outside the reviewed Niri 26.04 / Noctalia 5.x launcher scope.')
        reply = runner(['/usr/bin/systemctl', '--user', 'show', '--property=Version'])
        if reply.returncode or not re.search(r'^Version=([2-9][0-9]{2})', reply.stdout):
            blockers.append('The current account must have a reachable systemd user manager (version 254+).')
        else:
            version = int(re.search(r'^Version=([0-9]+)', reply.stdout).group(1))
            if version < 254:
                blockers.append('systemd 254+ is required for literal environment-free command arguments.')
        if not nested:
            reply = runner(['/usr/bin/systemctl', '--user', 'show', 'niri.service', '--property=ActiveState'])
            if reply.returncode not in (0, 1) or 'ActiveState=inactive' not in reply.stdout:
                blockers.append('An existing or uncertain niri.service must not be reused for standalone launch.')
    return {'mode': 'nested' if nested else 'standalone', 'status': 'blocked' if blockers else 'ready_for_trial',
            'blockers': blockers, 'versions': versions,
            'notice': 'Experimental launcher; installation compatibility and real login/logout are not certified.'}


def launch_environment(env: Mapping[str, str], directory: Path, *, nested: bool) -> dict[str, str]:
    keep = ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'XDG_RUNTIME_DIR',
            'XDG_SESSION_ID', 'XDG_SEAT', 'XDG_VTNR')
    result = {key: _safe(env[key]) for key in keep if key in env}
    if nested:
        result['WAYLAND_DISPLAY'] = _safe(env['WAYLAND_DISPLAY'])
    result.update({
        'PATH': '/usr/local/bin:/usr/bin:/bin',
        'XDG_CURRENT_DESKTOP': 'niri', 'XDG_SESSION_TYPE': 'wayland',
        'NIRI_DISABLE_SYSTEM_MANAGER_NOTIFY': '1',
        'XDG_CONFIG_HOME': str(directory / 'config'), 'XDG_STATE_HOME': str(directory / 'state'),
        'XDG_CACHE_HOME': str(directory / 'cache'), 'XDG_DATA_HOME': str(directory / 'data'),
        'XDG_CONFIG_DIRS': str(directory / 'defaults'), 'XDG_DATA_DIRS': '/usr/local/share:/usr/share',
        'NOCTALIA_CONFIG_HOME': str(directory / 'config'), 'NOCTALIA_STATE_HOME': str(directory / 'state'),
        'NOCTALIA_DATA_HOME': str(directory / 'data'),
        'PYTHONPATH': _safe(str(Path(__file__).resolve().parent.parent)),
    })
    return {key: _safe(value) for key, value in result.items()}


def shell_status(directory: Path, token: str) -> bool | None:
    path = directory / 'shell.json'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 4096:
            raise LauncherError('Invalid shell readiness record')
        data = json.loads(os.read(fd, 4097))
    except (ValueError, OSError) as exc:
        raise LauncherError('Unreadable shell readiness record') from exc
    finally:
        os.close(fd)
    if (not isinstance(data, dict) or data.get('token') != token
            or type(data.get('ready')) is not bool or type(data.get('exit_code')) is not int
            or (data['ready'] and data['exit_code'] != 0)):
        raise LauncherError('Shell readiness record does not match this attempt')
    return data['ready']


def shell_alive(group: str, unit: str) -> bool:
    try:
        pids = (cgroup_path(group, unit) / 'cgroup.procs').read_text().split()
        expected = os.stat('/usr/bin/noctalia')
        for pid in pids:
            if not pid.isdecimal():
                raise RecoveryRequired('Invalid cgroup process listing')
            try:
                observed = os.stat(f'/proc/{pid}/exe')
            except FileNotFoundError:
                continue
            if (observed.st_dev, observed.st_ino) == (expected.st_dev, expected.st_ino):
                return True
    except OSError as exc:
        raise RecoveryRequired('Cannot verify shell membership in the owned session cgroup') from exc
    return False


@contextmanager
def cancellation_handlers():
    cancelled = [False]
    saved = {}
    def cancel(number, frame):
        cancelled[0] = True
    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            saved[number] = signal.signal(number, cancel)
        yield lambda: cancelled[0]
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)


def run_session(env: Mapping[str, str], *, nested: bool, runner: Callable = run_command,
                session_factory: Callable = TransientSession, cancelled: Callable = lambda: False,
                readiness: Callable = shell_status, alive: Callable = shell_alive,
                sleep: Callable = time.sleep, clock: Callable = time.monotonic,
                startup_timeout: float = 40) -> int:
    if cancelled():
        return 130
    terminal = next((path for path in ('/usr/bin/foot', '/usr/bin/alacritty', '/usr/bin/cosmic-term',
                                     '/usr/bin/konsole', '/usr/bin/gnome-terminal') if os.access(path, os.X_OK)), None)
    with SessionLease(Path(env['XDG_RUNTIME_DIR']), SESSION_ID) as lease:
        directory = Path(tempfile.mkdtemp(prefix=f'launch-{lease.attempt_id}-', dir=Path(env['XDG_RUNTIME_DIR']) / 'desktopforge'))
        unit = session_factory(lease.attempt_id)
        try:
            for name in ('config', 'state', 'cache', 'data', 'defaults'):
                (directory / name).mkdir(mode=0o700)
            (directory / 'config/noctalia').mkdir(mode=0o700)
            # Avoid shell-selected commands and application escapes into unrelated user units.
            shell_config = ('[shell]\nsetup_wizard_enabled = false\ntelemetry_enabled = false\n'
                            'launch_apps_as_systemd_services = false\nlaunch_apps_custom_command = ""\n')
            _write_new(directory / 'config/noctalia/config.toml', shell_config)
            text = config_text(directory, lease.attempt_id, terminal)
            validate_config(text, runner)
            _write_new(directory / 'niri.kdl', text)
            child_env = launch_environment(env, directory, nested=nested)
            command = ['/usr/bin/env', '-i', *[f'{key}={value}' for key, value in sorted(child_env.items())],
                       '/usr/bin/dbus-run-session', '--', '/usr/bin/niri', '--config', str(directory / 'niri.kdl')]
            print(f'Starting DesktopForge Niri + Noctalia ({"nested window" if nested else "standalone"}).')
            print(f'Diagnostic unit: {unit.unit}')
            if cancelled():
                return 130
            unit.start(command)
            deadline = clock() + startup_timeout
            ready = False
            result = 1
            while not cancelled():
                state = unit.observe()
                if state.get('LoadState') == 'not-found' or state.get('ActiveState') in ('inactive', 'failed') or state.get('SubState') == 'exited':
                    result = int(state.get('ExecMainStatus', '1')) if ready else 1
                    break
                status = readiness(directory, lease.attempt_id)
                if status is False:
                    raise LauncherError('Noctalia initialization failed; stopping this session.')
                if status is True:
                    if not unit.group or not alive(unit.group, unit.unit):
                        raise LauncherError('Noctalia exited or is outside the owned session; stopping this session.')
                    if not ready:
                        ready = True
                        modifier = 'Alt' if nested else 'Super'
                        print(f'Noctalia initialized. {modifier}+D: applications; {modifier}+Return: terminal (if available); {modifier}+Shift+E: quit.')
                        print('This opens a desktop trial. DesktopForge does not yet have an installer GUI.')
                if not ready and clock() >= deadline:
                    raise LauncherError('Timed out waiting for Noctalia initialization.')
                sleep(.2)
            else:
                result = 130
            return result
        finally:
            # No generated files/markers are removed until owned service/cgroup shutdown is verified.
            unit.stop()
            shutil.rmtree(directory)
            lease.clean_after_verified_shutdown()


def _write_new(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())



def _diagnostic_text(directory_fd: int, relative: str, *, tail: bool = False) -> str:
    """Read fixed relative diagnostic paths without following any component links."""
    parts = Path(relative).parts
    if Path(relative).is_absolute() or '..' in parts:
        raise LauncherError('Invalid diagnostic path')
    current = os.dup(directory_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=current)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise LauncherError('Diagnostic file is not an owned regular file')
            limit = 16384 if tail else 4096
            if not tail and info.st_size > limit:
                raise LauncherError('Diagnostic record is unexpectedly large')
            if tail:
                os.lseek(fd, max(0, info.st_size - limit), os.SEEK_SET)
            text = os.read(fd, limit).decode('utf-8', errors='replace')
            return '\n'.join(text.splitlines()[-40:]) if tail else text
        finally:
            os.close(fd)
    finally:
        os.close(current)


def diagnose_session(env: Mapping[str, str], *, runner: Callable = run_command) -> dict:
    """Read this account's attempt records and logs. No start, stop or writes."""
    result = {'status': 'unavailable', 'uid': os.getuid(), 'unit': None,
              'notice': 'Read-only diagnostics for this execution account; no other user is inspected.'}
    runtime = env.get('XDG_RUNTIME_DIR', '')
    if not runtime or not Path(runtime).is_absolute():
        return {**result, 'reason': 'Run diagnostics in the same desktop-account terminal used to launch.'}
    try:
        directory = _open_directory(Path(runtime) / 'desktopforge')
    except (OSError, LauncherError) as exc:
        return {**result, 'reason': f'Runtime namespace is unavailable: {exc}'}
    try:
        record = json.loads(_diagnostic_text(directory, 'attempt.json'))
        token = record.get('attempt_id') if isinstance(record, dict) else None
        if (not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
                or record.get('session_id') != SESSION_ID or record.get('schema_version') != 1):
            raise LauncherError('Unrecognized attempt record')
        unit = TransientSession(token, runner=runner)
        result.update(status='observed', unit=unit.unit)
        try:
            state = unit.observe()
            result['service'] = {key: state.get(key) for key in
                ('LoadState', 'ActiveState', 'SubState', 'MainPID', 'ExecMainStatus', 'ControlGroup')}
        except (LauncherError, OSError, subprocess.SubprocessError) as exc:
            result['service_error'] = str(exc)
        profiles = []
        for name in sorted(os.listdir(directory)):
            if not re.fullmatch(f'launch-{token}-[A-Za-z0-9_-]+', name):
                continue
            profile = {'directory': name}
            for relative, field, tail in (
                ('shell.json', 'shell_record', False),
                ('cache/noctalia/noctalia.log', 'noctalia_log', True)):
                try:
                    profile[field] = _diagnostic_text(directory, name + '/' + relative, tail=tail)
                except (OSError, LauncherError) as exc:
                    profile[field + '_error'] = str(exc)
            profiles.append(profile)
        result['profiles'] = profiles
        try:
            journal = runner(['/usr/bin/journalctl', '--user', '-u', unit.unit, '-b',
                              '--no-pager', '-n', '40', '--output=cat'])
            result['journal'] = (journal.stdout if journal.returncode == 0 else journal.stderr)[-16384:]
        except (OSError, subprocess.SubprocessError) as exc:
            result['journal_error'] = str(exc)
        return result
    except (OSError, LauncherError, ValueError) as exc:
        return {**result, 'reason': f'No readable current attempt: {exc}'}
    finally:
        os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='desktopforge-session', description='Experimental isolated Niri + Noctalia launcher')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--nested', action='store_true', help='Open a nested window inside the current Wayland session')
    modes.add_argument('--standalone', action='store_true', help='Start from a fresh local TTY login (test VM recommended)')
    parser.add_argument('--diagnose', action='store_true', help='Read the current attempt and logs without changing the session')
    parser.add_argument('--check', action='store_true', help='Check prerequisites without starting or writing anything')
    parser.add_argument('--json', action='store_true', help='JSON output for --check')
    args = parser.parse_args(argv)
    if args.diagnose and (args.nested or args.standalone or args.check):
        parser.error('--diagnose cannot be combined with a launch mode or --check')
    if not args.diagnose and not (args.nested or args.standalone):
        parser.error('Choose --nested, --standalone, or --diagnose')
    if args.json and not (args.check or args.diagnose):
        parser.error('--json requires --check or --diagnose')
    try:
        env = dict(os.environ)
        if args.diagnose:
            print(json.dumps(diagnose_session(env), sort_keys=True, indent=2))
            return 0
        result = check_environment(env, nested=args.nested)
        # Parser-only validation uses an anonymous sealed memory file, not a desktop process.
        if not result['blockers']:
            validate_config(config_text(Path('/run/user/preview/desktopforge/preview'), '0' * 32))
        if args.json:
            print(json.dumps(result, sort_keys=True, indent=2))
        else:
            print(result['notice'])
            for blocker in result['blockers']:
                print(f'Blocked: {blocker}')
        if result['blockers']:
            return 1
        if args.check:
            if not args.json:
                print('Prerequisites passed. No session started and no configuration written.')
            return 0
        with cancellation_handlers() as cancelled:
            return run_session(env, nested=args.nested, cancelled=cancelled)
    except (LauncherError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f'Launcher stopped: {exc}', file=sys.stderr)
        print('If an attempt marker remains, keep it for review; no automatic takeover will occur.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
