import os

from desktopforge.session_analysis import session_analysis


def test_correlation_requires_compositor_service_and_matching_session(tmp_path):
    session = tmp_path / "niri.desktop"
    session.write_text("[Desktop Entry]\nName=Niri (Ryoku)\nExec=niri-session\n")
    sessions = [{"id": "niri", "name": "Niri (Ryoku)", "path": str(session)}]
    processes = [
        {"pid": 10, "uid": os.getuid(), "executable": "niri",
         "cgroup": "0::/user.slice/user-1001.slice/user@1001.service/session.slice/niri.service",
         "compositor_candidates": ["niri"], "shell_candidates": []},
        {"pid": 11, "uid": os.getuid(), "executable": "ryoku-shell",
         "cgroup": "0::/user.slice/user-1001.slice/user@1001.service/session.slice/ryoku-shell.service",
         "compositor_candidates": [], "shell_candidates": ["ryoku"]},
    ]
    result = session_analysis(sessions, {"XDG_CURRENT_DESKTOP": "niri"}, processes)
    assert result["shell_correlation"]["shell_candidates"] == ["ryoku"]
    assert result["shell_correlation"]["confidence"] == "corroborated_hints"
    assert result["active_shell"]["name"] is None


def test_no_correlation_without_matching_registered_session():
    result = session_analysis([], {"XDG_CURRENT_DESKTOP": "niri"}, [])
    assert result["shell_correlation"]["shell_candidates"] == []
