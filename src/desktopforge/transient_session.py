"""Own a unique transient user service; never touch shared desktop units."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Callable

from .launcher_runtime import LauncherError, RecoveryRequired


def run_command(argv: list[str], *, timeout: float = 15, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, shell=False, check=False, text=True, capture_output=True,
                          timeout=timeout, **kwargs)


def cgroup_path(group: str, unit: str) -> Path:
    path = PurePosixPath(group)
    if (not path.is_absolute() or '..' in path.parts or path.name != unit
            or not group.startswith('/user.slice/')):
        raise RecoveryRequired('Unexpected session cgroup path')
    return Path('/sys/fs/cgroup') / group.lstrip('/')


def cgroup_empty(group: str, unit: str) -> bool:
    path = cgroup_path(group, unit) / 'cgroup.events'
    try:
        values = dict(line.split() for line in path.read_text().splitlines())
    except FileNotFoundError:
        return True  # Removed cgroup cannot contain remaining processes.
    except (OSError, ValueError) as exc:
        raise RecoveryRequired('Cannot verify session cgroup cleanup') from exc
    if values.get('populated') not in ('0', '1'):
        raise RecoveryRequired('Unknown cgroup population state')
    return values['populated'] == '0'


class TransientSession:
    def __init__(self, token: str, *, runner: Callable = run_command,
                 empty_probe: Callable = cgroup_empty):
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise LauncherError('Invalid session attempt token')
        self.unit = f'desktopforge-{token}.service'
        self.description = f'DesktopForge session {token}'
        self.runner = runner
        self.empty_probe = empty_probe
        self.requested = False
        self.invocation: str | None = None
        self.group: str | None = None

    def observe(self) -> dict[str, str]:
        reply = self.runner(['/usr/bin/systemctl', '--user', 'show', self.unit, '--no-pager',
                             '--property=Id,LoadState,ActiveState,SubState,InvocationID,Description,Transient,ControlGroup,MainPID,ExecMainStatus'])
        values = dict(line.split('=', 1) for line in reply.stdout.splitlines() if '=' in line)
        if values.get('LoadState') == 'not-found':
            return values
        if reply.returncode or not values:
            raise RecoveryRequired(f'Cannot inspect {self.unit}; preserve the attempt for review')
        required = {'Id', 'Description', 'Transient', 'InvocationID', 'ActiveState', 'SubState',
                    'ControlGroup', 'MainPID', 'ExecMainStatus'}
        if (not required.issubset(values) or values.get('Id') != self.unit
                or values.get('Description') != self.description or values.get('Transient') != 'yes'):
            raise RecoveryRequired('Transient unit identity does not match this attempt')
        invocation = values['InvocationID']
        quiescent = (values['ActiveState'] in ('inactive', 'failed')
                     and values['MainPID'] == '0' and not values['ControlGroup'])
        if invocation:
            if not re.fullmatch('[0-9a-f]{32}', invocation):
                raise RecoveryRequired('Invalid transient invocation identity')
            if self.invocation is not None and self.invocation != invocation:
                raise RecoveryRequired('Transient unit invocation changed; control refused')
            self.invocation = invocation
        elif not quiescent:
            raise RecoveryRequired('Active unit has no invocation identity')
        group = values.get('ControlGroup')
        if group:
            cgroup_path(group, self.unit)
            if self.group is not None and group != self.group:
                raise RecoveryRequired('Transient unit cgroup changed')
            self.group = group
        return values

    def start(self, argv: list[str]) -> None:
        before = self.runner(['/usr/bin/systemctl', '--user', 'show', self.unit, '--property=LoadState'])
        if before.stdout.strip() != 'LoadState=not-found':
            raise RecoveryRequired('Generated transient unit name is not demonstrably unused')
        self.requested = True  # A timed-out client may still have started the unit.
        reply = self.runner([
            '/usr/bin/systemd-run', '--user', f'--unit={self.unit}',
            f'--description={self.description}', '--expand-environment=no',
            '--property=Type=exec', '--property=RemainAfterExit=yes',
            '--property=KillMode=control-group', '--property=TimeoutStopSec=5s',
            '--property=SendSIGKILL=yes', '--property=Restart=no',
            '--property=StandardOutput=journal', '--property=StandardError=journal',
            '--', *argv])
        if reply.returncode:
            raise LauncherError(f'Session start failed: {reply.stderr.strip()[:500]}')
        self.observe()

    def stop(self) -> None:
        if not self.requested:
            return
        state = self.observe()
        if state.get('LoadState') != 'not-found':
            reply = self.runner(['/usr/bin/systemctl', '--user', 'stop', self.unit], timeout=15)
            if reply.returncode:
                raise RecoveryRequired(f'Could not stop owned unit {self.unit}')
            state = self.observe()
            if (state.get('LoadState') != 'not-found'
                    and (state.get('ActiveState') not in ('inactive', 'failed')
                         or state.get('MainPID', '0') != '0')):
                raise RecoveryRequired('Session unit shutdown is unconfirmed')
        if self.group is not None and not self.empty_probe(self.group, self.unit):
            raise RecoveryRequired('Processes remain in the owned session cgroup')
        self.requested = False
