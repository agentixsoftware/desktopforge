from dataclasses import replace

import pytest

from desktopforge.lifecycle import (EnvironmentSlot, Event, LifecycleError, Phase,
                                    Request, Runtime, advance, begin, lifecycle_contract)


@pytest.fixture
def session_request():
    return Request('desktopforge-niri-noctalia', 'attempt-one',
                   '/home/test/.config/desktopforge/sessions/desktopforge-niri-noctalia/niri.kdl',
                   config_validated=True, hooks_reviewed=True)


def running(session_request, runtime=Runtime()):
    return advance(advance(begin(session_request, runtime), Event.READY), Event.SHELL_READY)


@pytest.mark.parametrize('prior', [None, '', '/home/test/.config/niri/previous.kdl'])
def test_success_restores_prior_value_or_absence_without_mutating_inputs(session_request, prior):
    original = Runtime(environment=EnvironmentSlot(prior, 7))
    started = begin(session_request, original)
    assert started.state.phase == Phase.STARTING
    assert original.environment == EnvironmentSlot(prior, 7)
    assert started.runtime.environment.value == session_request.config_path
    assert started.runtime.environment.revision == 8
    ready = advance(started, Event.READY)
    assert ready.state.phase == Phase.WAITING_FOR_SHELL
    active = advance(ready, Event.SHELL_READY)
    assert active.state.phase == Phase.RUNNING
    exited = advance(active, Event.EXITED)
    assert exited.state.phase == Phase.FINISHED
    assert exited.state.outcome == 'completed'
    assert exited.runtime.environment == EnvironmentSlot(prior, 9)
    assert exited.runtime.guard_owner is None
    assert exited.runtime.compositor == 'inactive'
    assert exited.effects == (('unset_niri_config' if prior is None else 'restore_niri_config'), 'release_guard')


@pytest.mark.parametrize('event', [Event.STARTUP_FAILED, Event.EXITED])
def test_failure_before_readiness_cleans_only_owned_state(session_request, event):
    result = advance(begin(session_request, Runtime()), event)
    if event == Event.STARTUP_FAILED:
        assert result.state.phase == Phase.STOPPING
        assert result.runtime.environment.value == session_request.config_path
        result = advance(result, Event.EXITED)
    assert result.state.phase == Phase.FINISHED
    assert result.state.outcome == 'startup_failed'
    assert result.runtime.environment.value is None


@pytest.mark.parametrize('prepare', [lambda result: result,
                                     lambda result: advance(result, Event.READY),
                                     lambda result: advance(advance(result, Event.READY), Event.SHELL_READY)])
def test_interrupt_waits_for_exit_before_restoring(session_request, prepare):
    started = prepare(begin(session_request, Runtime()))
    stopping = advance(started, Event.INTERRUPTED)
    assert stopping.state.phase == Phase.STOPPING
    assert stopping.runtime.environment.value == session_request.config_path
    assert stopping.effects == ('request_owned_compositor_stop',)
    repeated = advance(stopping, Event.INTERRUPTED)
    assert repeated.effects == ()
    result = advance(repeated, Event.EXITED)
    assert result.state.phase == Phase.FINISHED
    assert result.state.outcome == 'interrupted'
    assert result.runtime.environment.value is None


def test_manager_outage_defers_cleanup_and_can_retry(session_request):
    active = running(session_request)
    unavailable = replace(active.runtime, manager_available=False)
    pending = advance(active, Event.EXITED, observed=unavailable)
    assert pending.state.phase == Phase.CLEANUP_PENDING
    assert pending.effects == ()
    assert pending.runtime.guard_owner == session_request.attempt_id
    assert pending.runtime.environment.value == session_request.config_path
    assert advance(pending, Event.RETRY_CLEANUP).state.phase == Phase.CLEANUP_PENDING
    available = replace(pending.runtime, manager_available=True)
    finished = advance(pending, Event.RETRY_CLEANUP, observed=available)
    assert finished.state.phase == Phase.FINISHED
    assert finished.runtime.environment.value is None
    repeated = advance(finished, Event.RETRY_CLEANUP)
    assert repeated.effects == () and repeated.runtime == finished.runtime


@pytest.mark.parametrize('change', [
    lambda slot: replace(slot, value='/other/session/config.kdl'),
    lambda slot: replace(slot, revision=slot.revision + 1),  # ABA: same value, later writer
    lambda slot: replace(slot, owner='another-attempt'),
])
def test_changed_environment_is_never_clobbered(session_request, change):
    active = running(session_request)
    changed = replace(active.runtime, environment=change(active.runtime.environment))
    result = advance(active, Event.EXITED, observed=changed)
    assert result.state.phase == Phase.MANUAL_RECOVERY
    assert result.effects == ()
    assert result.runtime.environment == changed.environment
    assert result.runtime.guard_owner == session_request.attempt_id


@pytest.mark.parametrize('runtime', [Runtime(compositor='running', compositor_owner='foreign'),
    Runtime(compositor='unknown'), Runtime(guard_owner='foreign'), Runtime(manager_available=False),
    Runtime(environment=EnvironmentSlot('/stale', 1, 'stale-owner'))])
def test_start_refuses_existing_uncertain_or_unavailable_runtime(session_request, runtime):
    result = begin(session_request, runtime)
    assert result.state.phase == Phase.BLOCKED
    assert result.runtime == runtime and result.effects == ()


@pytest.mark.parametrize('field', ['config_validated', 'hooks_reviewed'])
def test_unreviewed_inputs_cannot_begin(session_request, field):
    result = begin(replace(session_request, **{field: False}), Runtime())
    assert result.state.phase == Phase.BLOCKED
    assert result.effects == ()


def test_second_attempt_cannot_start_or_stop_first_attempt(session_request):
    first = running(session_request)
    second = begin(replace(session_request, attempt_id='attempt-two'), first.runtime)
    assert second.state.phase == Phase.BLOCKED
    assert second.runtime == first.runtime and second.effects == ()
    with pytest.raises(LifecycleError):
        advance(second, Event.INTERRUPTED)


@pytest.mark.parametrize('field', ['guard_owner', 'compositor_owner'])
def test_lost_ownership_never_stops_other_session(session_request, field):
    active = running(session_request)
    observed = replace(active.runtime, **{field: 'someone-else'})
    result = advance(active, Event.INTERRUPTED, observed=observed)
    assert result.state.phase == Phase.MANUAL_RECOVERY
    assert result.effects == () and result.runtime == observed


def test_stop_failure_keeps_environment_and_guard_for_recovery(session_request):
    stopping = advance(running(session_request), Event.INTERRUPTED)
    failed = advance(stopping, Event.STOP_FAILED)
    assert failed.state.phase == Phase.MANUAL_RECOVERY
    assert failed.runtime == stopping.runtime and failed.effects == ()


def test_shell_failure_is_not_success_and_requires_compositor_exit(session_request):
    ready = advance(begin(session_request, Runtime()), Event.READY)
    failed = advance(ready, Event.SHELL_FAILED)
    assert failed.state.phase == Phase.STOPPING
    assert failed.runtime.environment.value == session_request.config_path
    result = advance(failed, Event.EXITED)
    assert result.state.outcome == 'shell_failed'
    assert result.runtime.environment.value is None


def test_exit_before_shell_ready_is_startup_failure(session_request):
    result = advance(advance(begin(session_request, Runtime()), Event.READY), Event.EXITED)
    assert result.state.outcome == 'startup_failed'


def test_pending_cleanup_refuses_foreign_compositor_or_lost_guard(session_request):
    active = running(session_request)
    pending = advance(active, Event.EXITED, observed=replace(active.runtime, manager_available=False))
    for observed in (replace(pending.runtime, guard_owner='foreign', manager_available=True),
                     replace(pending.runtime, compositor='running', compositor_owner='foreign', manager_available=True)):
        result = advance(pending, Event.RETRY_CLEANUP, observed=observed)
        assert result.state.phase == Phase.MANUAL_RECOVERY
        assert result.effects == () and result.runtime == observed


@pytest.mark.parametrize('path', ['relative/config', '/tmp/../desktopforge/sessions/desktopforge-niri-noctalia/niri.kdl',
                                  '/home/test/.config/niri/config.kdl', '/tmp/config\x00'])
def test_invalid_config_paths_rejected_before_model_start(session_request, path):
    with pytest.raises(LifecycleError):
        begin(replace(session_request, config_path=path), Runtime())


def test_invalid_and_out_of_order_events_rejected(session_request):
    result = begin(session_request, Runtime())
    for event in (Event.SHELL_READY, Event.RETRY_CLEANUP, 'ready'):
        with pytest.raises(LifecycleError):
            advance(result, event)
    with pytest.raises(LifecycleError):
        begin(session_request, Runtime(environment=EnvironmentSlot(revision=True)))


def test_plan_contract_exposes_only_static_simulation_metadata():
    contract = lifecycle_contract()
    assert contract['status'] == 'simulation_only' and not contract['executable']
    assert contract['owned_environment_keys'] == ['NIRI_CONFIG']
    assert 'waiting_for_shell' in contract['phases']
    assert any('no atomic runtime adapter' in item for item in contract['limitations'])


def test_model_is_deterministic_and_does_not_touch_process_environment(session_request, monkeypatch):
    import os

    monkeypatch.setenv('NIRI_CONFIG', '/unchanged/host/config.kdl')
    monkeypatch.setenv('DESKTOPFORGE_TEST_UNRELATED', 'unchanged')
    before = dict(os.environ)
    first = advance(running(session_request), Event.EXITED)
    second = advance(running(session_request), Event.EXITED)
    assert first == second
    assert dict(os.environ) == before


def test_default_request_never_inherits_planner_review_approval(session_request):
    unreviewed = Request(session_request.session_id, session_request.attempt_id, session_request.config_path)
    result = begin(unreviewed, Runtime())
    assert result.state.phase == Phase.BLOCKED
    assert len(result.state.issues) == 2
    assert result.effects == ()


def test_session_layout_exposes_contract_without_runtime_values():
    from desktopforge.session_layout import session_layout_preview

    layout = session_layout_preview('niri-noctalia-v5', 'desktopforge-niri-noctalia', 'niri', 'noctalia')
    model = layout['launch_contract']['lifecycle_model']
    assert model == lifecycle_contract()
    assert model['status'] == 'simulation_only'
    assert layout['complete'] is False and layout['executable'] is False
    assert 'before' not in model and 'published' not in model
