from pathlib import Path

from desktopforge.detection import detect_system
from desktopforge.session_analysis import session_analysis, describe_sessions


def test_multi_shell_fedora_reference(tmp_path: Path):
    """Synthetic session definitions based on user's observed session names."""
    folder = tmp_path / "usr/share/wayland-sessions"
    folder.mkdir(parents=True)
    for slug, title, command in [
        ("cosmic", "COSMIC", "cosmic-session"),
        ("niri-dms", "Niri (DMS)", "niri-session --session dms"),
        ("niri-noctalia", "Niri (Noctalia)", "niri-session --session noctalia"),
        ("niri-ryoku", "Niri (Ryoku)", "niri-session --session ryoku"),
    ]:
        (folder / (slug + ".desktop")).write_text(
            "[Desktop Entry]\nName=" + title + "\nExec=" + command + "\n")
    inventory = detect_system(root=tmp_path,
                              environ={"XDG_CURRENT_DESKTOP": "niri", "XDG_SESSION_TYPE": "wayland"},
                              which=lambda exe: "/usr/bin/" + exe if exe in ("niri", "dms", "dnf5") else None)
    analysis = inventory["session_analysis"]
    assert len(analysis["registered_sessions"]) == 4
    assert sorted({name for entry in analysis["registered_sessions"]
                   for name in entry["shell_candidates"]}) == ["dms", "noctalia", "ryoku"]
    assert analysis["active_shell"]["name"] is None
    assert inventory["shell_executables"]["noctalia"]["found"] is False


def test_explicit_session_shell_is_hint_not_proof():
    result = session_analysis([], {"DESKTOP_SESSION": "niri-ryoku"}, [])
    assert result["active_shell"] == {
        "name": "ryoku", "confidence": "environment_hint",
        "reason": "Session environment names the shell; not runtime verification"}


def test_process_is_not_assumed_to_belong_to_current_session():
    result = session_analysis([], {"XDG_CURRENT_DESKTOP": "niri"},
                              [{"pid": 123, "executable": "ryoku",
                                "shell_candidates": ["ryoku"], "compositor_candidates": []}])
    assert result["active_shell"]["name"] is None
    assert result["running_shell_process_candidates"] == ["ryoku"]
