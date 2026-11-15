from desktopforge.planner import list_targets, plan


def inventory():
    return {
        "distribution": {"id": "fedora", "version_id": "45"},
        "compositor_executables": {"niri": {"found": True}},
        "shell_executables": {"ryoku": {"found": True}},
        "session_analysis": {"registered_sessions": [
            {"name": "Niri (Ryoku)", "compositor_candidates": ["niri"],
             "shell_candidates": ["ryoku"]}]},
    }


def test_catalog_never_claims_unverified_install_support():
    result = list_targets(inventory())
    assert any(t["shell"] == "ryoku" for t in result["targets"])
    assert all(not t["eligible_for_install"] for t in result["targets"])
    assert result["supported_for_install"] == []


def test_plan_is_deterministic_and_never_executes():
    first = plan(inventory(), "niri", "ryoku")
    assert first == plan(inventory(), "niri", "ryoku")
    assert first["status"] == "blocked"
    assert first["executable"] is False
    assert first["writes"] == []
    assert first["package_commands"] == []
    assert first["evidence"]["matching_registered_sessions"] == ["Niri (Ryoku)"]


def test_unknown_combination_is_blocked():
    result = plan(inventory(), "sway", "noctalia")
    assert result["status"] == "blocked"
    assert result["blockers"]


def test_compatibility_api_uses_shared_version_constraints_without_mutation():
    from copy import deepcopy

    data = inventory()
    data['display_manager'] = {'name': 'sddm'}
    before = deepcopy(data)
    result = plan(data, 'niri', 'ryoku')
    assert result['compatibility_resolution']['recipe_ids'] == ['fedora45-niri-ryoku']
    assert data == before
    data['distribution']['version_id'] = '46'
    assert plan(data, 'niri', 'ryoku')['compatibility'] == 'unsupported'


def test_both_catalog_apis_have_same_target_scope():
    from desktopforge.planning import compatibility_catalog

    expected = [entry for entry in compatibility_catalog() if entry['distribution'] == 'fedora']
    actual = list_targets(inventory())['targets']
    assert [(entry['compositor'], entry['shell']) for entry in actual] == [
        (entry['compositor'], entry['shell']) for entry in expected]
