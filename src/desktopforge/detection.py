"""Read-only Linux desktop detection.

No shell execution, package installation, privilege escalation, or filesystem writes.
Inputs are injectable to make the detector testable with fixtures.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping


def parse_os_release(content: str) -> dict[str, str]:
    """Parse os-release key/value pairs without executing shell content."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = re.sub(r'\\(["\\$`])', r'\1', value)
        result[key] = value
    return result


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _session_entries(directory: Path) -> list[dict[str, str]]:
    """List session launchers, without executing or trusting their contents."""
    try:
        entries = sorted(directory.glob("*.desktop"))
    except OSError:
        return []
    output = []
    for path in entries:
        if not path.is_file():
            continue
        name = path.stem
        data = _read_text(path)
        if data:
            in_entry = False
            for line in data.splitlines():
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_entry = True
                elif line.startswith("[") and line.endswith("]"):
                    in_entry = False
                elif in_entry and line.startswith("Name="):
                    name = line.split("=", 1)[1].strip() or name
                    break
        output.append({"id": path.stem, "name": name, "path": str(path)})
    return output


def _detect_display_manager(root: Path) -> dict[str, Any]:
    """Report best-effort DM evidence; never claim active DM without reliable evidence."""
    service = root / "etc/systemd/system/display-manager.service"
    try:
        target = os.readlink(service)
    except OSError:
        return {"name": None, "source": None, "confidence": "unknown"}
    basename = Path(target).name.lower()
    for marker in ("gdm", "sddm", "lightdm", "ly"):
        if marker in basename:
            return {"name": marker, "source": str(service), "confidence": "configured"}
    return {"name": basename.removesuffix(".service"), "source": str(service), "confidence": "configured"}


def detect_system(
    root: Path = Path("/"),
    environ: Mapping[str, str] | None = None,
    which: Any = None,
) -> dict[str, Any]:
    """Return an inventory of available evidence; all operations are read-only.

    root can point to a fixture directory. which is an injectable executable lookup.
    Current-session environment variables are hints, not proof of installed sessions.
    """
    env = os.environ if environ is None else environ
    lookup = shutil.which if which is None else which
    os_text = _read_text(root / "etc/os-release")
    if os_text is None:
        os_text = _read_text(root / "usr/lib/os-release")
    distro = parse_os_release(os_text or "")
    package_managers = [name for name in ("dnf5", "dnf", "pacman", "apt-get") if lookup(name)]
    compositor_bins = {"niri": "niri", "hyprland": "Hyprland", "sway": "sway"}
    compositor_evidence = {
        name: {"executable": executable, "found": bool(lookup(executable))}
        for name, executable in compositor_bins.items()
    }
    shell_bins = {"noctalia": "noctalia-shell", "dms": "dms"}
    shell_evidence = {
        name: {"executable": executable, "found": bool(lookup(executable))}
        for name, executable in shell_bins.items()
    }
    return {
        "schema_version": 1,
        "distribution": {
            "id": distro.get("ID"),
            "name": distro.get("PRETTY_NAME") or distro.get("NAME"),
            "version_id": distro.get("VERSION_ID"),
            "id_like": distro.get("ID_LIKE", "").split(),
        },
        "package_managers_on_path": package_managers,
        "display_manager": _detect_display_manager(root),
        "current_session": {
            "desktop": env.get("XDG_CURRENT_DESKTOP"),
            "session_type": env.get("XDG_SESSION_TYPE"),
            "session_desktop": env.get("XDG_SESSION_DESKTOP"),
        },
        "sessions": {
            "wayland": _session_entries(root / "usr/share/wayland-sessions"),
            "x11": _session_entries(root / "usr/share/xsessions"),
        },
        "compositor_executables": compositor_evidence,
        "shell_executables": shell_evidence,
        "limitations": [
            "Executable presence does not prove a functional installation.",
            "Display manager evidence indicates configuration, not necessarily the running service.",
            "Session files and environment variables do not prove login compatibility.",
            "No installation compatibility has been validated by this inventory.",
        ],
    }
