import os

from desktopforge.session_analysis import session_analysis


def test_ryoku_user_service_is_evidence_not_session_proof():
    process = {
        "pid": 367408,
        "executable": "ryoku-shell",
        "uid": os.getuid(),
        "cgroup": "0::/user.slice/user-1001.slice/user@1001.service/session.slice/ryoku-shell.service",
        "shell_candidates": ["ryoku"],
        "compositor_candidates": [],
    }
    result = session_analysis([], {"XDG_CURRENT_DESKTOP": "niri"}, [process])
    assert result["current_user_service_shell_candidates"] == ["ryoku"]
    assert result["active_shell"]["name"] is None


def test_other_users_service_not_attributed_to_current_user():
    process = {
        "pid": 42,
        "executable": "ryoku-shell",
        "uid": os.getuid() + 1,
        "cgroup": "0::/user.slice/user-1002.slice/user@1002.service/session.slice/ryoku-shell.service",
        "shell_candidates": ["ryoku"],
        "compositor_candidates": [],
    }
    result = session_analysis([], {}, [process])
    assert result["current_user_service_shell_candidates"] == []
