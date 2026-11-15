"""Pure launcher lifecycle simulation; no process, filesystem or systemd access.

Environment revisions and session guards are modeled ownership primitives, not
facilities provided by systemd. A future runtime needs separately reviewed,
atomic ownership and crash-recovery mechanisms before using this design.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import PurePosixPath
import re


class LifecycleError(ValueError):
    """Invalid model input or event transition."""


class Phase(str, Enum):
    BLOCKED = 'blocked'
    STARTING = 'starting'
    WAITING_FOR_SHELL = 'waiting_for_shell'
    RUNNING = 'running'
    STOPPING = 'stopping'
    CLEANUP_PENDING = 'cleanup_pending'
    FINISHED = 'finished'
    MANUAL_RECOVERY = 'manual_recovery'


class Event(str, Enum):
    READY = 'compositor_ready'
    SHELL_READY = 'shell_ready'
    SHELL_FAILED = 'shell_failed'
    STARTUP_FAILED = 'startup_failed'
    EXITED = 'exited'
    INTERRUPTED = 'interrupted'
    STOP_FAILED = 'stop_failed'
    RETRY_CLEANUP = 'retry_cleanup'


@dataclass(frozen=True)
class EnvironmentSlot:
    """Only NIRI_CONFIG is modeled. None means absent; '' means present but empty."""
    value: str | None = None
    revision: int = 0
    owner: str | None = None


@dataclass(frozen=True)
class Runtime:
    manager_available: bool = True
    guard_owner: str | None = None
    compositor: str = 'inactive'
    compositor_owner: str | None = None
    environment: EnvironmentSlot = EnvironmentSlot()


@dataclass(frozen=True)
class Request:
    session_id: str
    attempt_id: str
    config_path: str
    config_validated: bool = False
    hooks_reviewed: bool = False


@dataclass(frozen=True)
class State:
    request: Request
    phase: Phase
    before: EnvironmentSlot | None = None
    published: EnvironmentSlot | None = None
    outcome: str | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    state: State
    runtime: Runtime
    # Symbolic effects for a simulated runtime, never commands to execute.
    effects: tuple[str, ...] = ()


def _validate(request: Request, runtime: Runtime) -> None:
    if not re.fullmatch(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+)*', request.session_id):
        raise LifecycleError('Invalid session ID')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', request.attempt_id):
        raise LifecycleError('Invalid attempt ID')
    path = PurePosixPath(request.config_path)
    if (not path.is_absolute() or '..' in path.parts or '\x00' in request.config_path
            or path.parts[-4:] != ('desktopforge', 'sessions', request.session_id, 'niri.kdl')):
        raise LifecycleError('Config must be an absolute isolated session config path')
    if runtime.compositor not in ('inactive', 'starting', 'running', 'stopping', 'unknown'):
        raise LifecycleError('Invalid compositor observation')
    if type(runtime.environment.revision) is not int or runtime.environment.revision < 0:
        raise LifecycleError('Invalid environment revision')


def begin(request: Request, runtime: Runtime) -> Result:
    """Simulate a guarded start only with explicit reviewed-input assertions."""
    _validate(request, runtime)
    issues = []
    if not request.config_validated:
        issues.append('Complete isolated configuration has not been validated.')
    if not request.hooks_reviewed:
        issues.append('Effective session hooks have not been reviewed.')
    if not runtime.manager_available:
        issues.append('User manager is unavailable.')
    if runtime.environment.owner is not None:
        issues.append('Environment ownership is already claimed; stale state requires review.')
    if runtime.guard_owner is not None:
        issues.append('A session guard is already held.')
    if runtime.compositor != 'inactive' or runtime.compositor_owner is not None:
        issues.append('An existing or uncertain compositor must not be reused or stopped.')
    if issues:
        return Result(State(request, Phase.BLOCKED, issues=tuple(issues)), runtime)
    published = EnvironmentSlot(request.config_path, runtime.environment.revision + 1, request.attempt_id)
    state = State(request, Phase.STARTING, before=runtime.environment, published=published)
    simulated = replace(runtime, guard_owner=request.attempt_id, compositor='starting',
                        compositor_owner=request.attempt_id, environment=published)
    return Result(state, simulated, ('acquire_guard', 'snapshot_niri_config',
                                    'publish_niri_config', 'request_compositor_start'))


def _recover(state: State, runtime: Runtime, issue: str) -> Result:
    return Result(replace(state, phase=Phase.MANUAL_RECOVERY, issues=state.issues + (issue,)), runtime)


def _cleanup(state: State, runtime: Runtime) -> Result:
    if runtime.guard_owner != state.request.attempt_id:
        return _recover(state, runtime, 'Session guard ownership changed; cleanup refused.')
    if runtime.compositor != 'inactive' or runtime.compositor_owner is not None:
        return _recover(state, runtime, 'Compositor stop is unconfirmed; environment cleanup refused.')
    if not runtime.manager_available:
        return Result(replace(state, phase=Phase.CLEANUP_PENDING), runtime)
    if runtime.environment != state.published:
        return _recover(state, runtime, 'NIRI_CONFIG ownership, revision or value changed; restoration refused.')
    if state.before is None:
        return _recover(state, runtime, 'Original environment snapshot is unavailable.')
    restored = replace(state.before, revision=runtime.environment.revision + 1)
    simulated = replace(runtime, environment=restored, guard_owner=None)
    effect = 'unset_niri_config' if state.before.value is None else 'restore_niri_config'
    return Result(replace(state, phase=Phase.FINISHED), simulated, (effect, 'release_guard'))


def advance(result: Result, event: Event, *, observed: Runtime | None = None) -> Result:
    """Apply a simulated lifecycle event, optionally injecting external changes.

    READY and EXITED model authoritative observations of our own compositor,
    not real probes. STARTUP_FAILED requires a subsequent EXITED event before
    restoration. No adapter or signal handler exists.
    """
    state = result.state
    runtime = result.runtime if observed is None else observed
    _validate(state.request, runtime)
    if not isinstance(event, Event):
        raise LifecycleError('Expected a typed lifecycle event')
    if state.phase == Phase.FINISHED and event == Event.RETRY_CLEANUP:
        return Result(state, runtime)  # Never repeat restore/unset effects.
    if state.phase == Phase.CLEANUP_PENDING and event == Event.RETRY_CLEANUP:
        return _cleanup(state, runtime)
    allowed = {
        Phase.STARTING: {Event.READY, Event.STARTUP_FAILED, Event.EXITED, Event.INTERRUPTED},
        Phase.WAITING_FOR_SHELL: {Event.SHELL_READY, Event.SHELL_FAILED, Event.EXITED, Event.INTERRUPTED},
        Phase.RUNNING: {Event.SHELL_FAILED, Event.EXITED, Event.INTERRUPTED},
        Phase.STOPPING: {Event.EXITED, Event.STOP_FAILED, Event.INTERRUPTED},
    }
    if event not in allowed.get(state.phase, set()):
        raise LifecycleError(f'Event {event.value} is invalid in phase {state.phase.value}')
    owner = state.request.attempt_id
    if runtime.guard_owner != owner or runtime.compositor_owner != owner:
        return _recover(state, runtime, 'Owned compositor or session guard changed; no stop or cleanup attempted.')
    if event == Event.READY:
        if runtime.compositor not in ('starting', 'running'):
            return _recover(state, runtime, 'Readiness conflicts with compositor observation.')
        return Result(replace(state, phase=Phase.WAITING_FOR_SHELL), replace(runtime, compositor='running'))
    if event == Event.SHELL_READY:
        if runtime.compositor != 'running':
            return _recover(state, runtime, 'Shell readiness conflicts with compositor observation.')
        return Result(replace(state, phase=Phase.RUNNING), runtime)
    if event in (Event.INTERRUPTED, Event.SHELL_FAILED, Event.STARTUP_FAILED):
        if runtime.compositor not in ('starting', 'running', 'stopping'):
            return _recover(state, runtime, 'Cannot confirm an owned compositor to stop.')
        if state.phase == Phase.STOPPING:
            return Result(state, runtime)  # Do not send duplicate modeled stop requests.
        outcome = {Event.SHELL_FAILED: 'shell_failed', Event.STARTUP_FAILED: 'startup_failed',
                   Event.INTERRUPTED: 'interrupted'}[event]
        return Result(replace(state, phase=Phase.STOPPING, outcome=outcome),
                      replace(runtime, compositor='stopping'), ('request_owned_compositor_stop',))
    if event == Event.STOP_FAILED:
        return _recover(state, runtime, 'Owned compositor did not stop; environment and guard retained.')
    # Explicit owned EXITED event confirms this modeled compositor has stopped.
    outcome = state.outcome or ('startup_failed' if state.phase in
                               (Phase.STARTING, Phase.WAITING_FOR_SHELL) else 'completed')
    stopped = replace(runtime, compositor='inactive', compositor_owner=None)
    return _cleanup(replace(state, outcome=outcome), stopped)


def lifecycle_contract() -> dict:
    """Public static contract for plan previews, without any runtime values."""
    return {
        'status': 'simulation_only', 'executable': False,
        'owned_environment_keys': ['NIRI_CONFIG'],
        'phases': [phase.value for phase in Phase],
        'cleanup_policy': 'Restore the prior value or absence only after owned compositor exit and exact ownership/revision checks.',
        'concurrency_policy': 'Require an exclusive per-user session guard; do not reuse or stop an existing compositor.',
        'limitations': [
            'Ownership tokens and revisions are model assumptions; no atomic runtime adapter exists.',
            'niri-session environment imports, D-Bus, attempt-correlated shell readiness and stop acknowledgements remain unvalidated.',
            'Hard termination and machine crashes require durable recovery outside this in-memory model.',
        ],
    }
