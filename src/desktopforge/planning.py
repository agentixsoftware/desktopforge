"""Conservative catalog and deterministic previews; no executable operations."""
from __future__ import annotations

DISTRIBUTIONS = ("fedora", "arch", "cachyos")
COMPOSITORS = ("niri", "hyprland")
SHELLS = ("noctalia", "dms", "ryoku")


def compatibility_catalog() -> list[dict[str, str]]:
    """Target scope only: no distro/version combination is validated yet."""
    return [
        {"distribution": distro, "compositor": compositor, "shell": shell,
         "status": "unverified"}
        for distro in DISTRIBUTIONS for compositor in COMPOSITORS for shell in SHELLS
    ]


def build_plan(inventory: dict, compositor: str, shell: str) -> dict:
    """Build a stable preview from supplied evidence without performing changes."""
    if compositor not in COMPOSITORS or shell not in SHELLS:
        raise ValueError("Unknown compositor or shell")
    distro = inventory["distribution"]["id"]
    status = "unverified" if distro in DISTRIBUTIONS else "unsupported"
    existing = {entry["id"] for group in inventory["sessions"].values() for entry in group}
    base = f"desktopforge-{compositor}-{shell}"
    session_id = base
    suffix = 2
    while session_id in existing:
        session_id = f"{base}-{suffix}"
        suffix += 1
    blockers = ["No validated installation recipe is available."]
    if status == "unsupported":
        blockers.insert(0, "Distribution is outside the initial target catalog.")
    return {
        "schema_version": 1,
        "dry_run": True,
        "status": "blocked",
        "target": {"distribution": distro,
                   "version_id": inventory["distribution"]["version_id"],
                   "compositor": compositor, "shell": shell},
        "compatibility": status,
        "blockers": blockers,
        "session_id_preview": session_id,
        "component_evidence": {
            "compositor_executable_found": inventory["compositor_executables"][compositor]["found"],
            "shell_executable_found": inventory["shell_executables"][shell]["found"],
        },
        "preserve": {"display_manager": inventory["display_manager"]["name"],
                     "existing_sessions": sorted(existing), "user_configuration": True},
        "operations": [],
        "limitations": ["Executable discovery does not validate compatibility or safe reuse.",
                        "Session ID is a preview; filesystem conflicts must be checked before any future apply."],
    }
