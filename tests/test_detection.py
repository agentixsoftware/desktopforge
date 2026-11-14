from pathlib import Path

from desktopforge.detection import detect_system, parse_os_release


def test_parse_os_release_quotes_and_comments():
    result = parse_os_release('ID=fedora\nPRETTY_NAME="Fedora Linux 45"\n# comment\nID_LIKE="rhel fedora"\n')
    assert result["ID"] == "fedora"
    assert result["PRETTY_NAME"] == "Fedora Linux 45"
    assert result["ID_LIKE"] == "rhel fedora"


def test_os_release_is_not_executed():
    result = parse_os_release('ID="$(touch /tmp/desktopforge-should-not-exist)"\n')
    assert result["ID"] == "$(touch /tmp/desktopforge-should-not-exist)"


def test_detect_fixture(tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/os-release").write_text('ID=fedora\nPRETTY_NAME="Fedora Linux 45"\nVERSION_ID=45\n')
    session_dir = tmp_path / "usr/share/wayland-sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "niri.desktop").write_text("[Desktop Entry]\nName=Niri\nExec=niri-session\n")
    dm_dir = tmp_path / "etc/systemd/system"
    dm_dir.mkdir(parents=True)
    (dm_dir / "display-manager.service").symlink_to("/usr/lib/systemd/system/gdm.service")
    inventory = detect_system(
        root=tmp_path,
        environ={"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"},
        which=lambda executable: "/usr/bin/" + executable if executable in ("dnf5", "niri") else None,
    )
    assert inventory["distribution"]["id"] == "fedora"
    assert inventory["display_manager"]["name"] == "gdm"
    assert inventory["sessions"]["wayland"][0]["name"] == "Niri"
    assert inventory["compositor_executables"]["niri"]["found"] is True
    assert inventory["shell_executables"]["noctalia"]["found"] is False
    assert inventory["current_session"]["desktop"] == "GNOME"


def test_missing_data_is_graceful(tmp_path: Path):
    result = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    assert result["distribution"]["id"] is None
    assert result["display_manager"]["confidence"] == "unknown"
    assert result["sessions"]["wayland"] == []


def test_unrelated_display_manager_name_is_not_classified(tmp_path):
    directory = tmp_path / 'etc/systemd/system'
    directory.mkdir(parents=True)
    (directory / 'display-manager.service').symlink_to('/usr/lib/systemd/system/not-sddm.service')
    result = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    assert result['display_manager']['name'] == 'not-sddm'
