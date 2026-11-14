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
