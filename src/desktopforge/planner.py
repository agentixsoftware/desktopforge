"""Conservative, read-only compatibility catalog and deterministic plan preview.

No operations are executed. Catalog entries are design targets, not verified support.
"""
from __future__ import annotations

from typing import Any

TARGETS = {
    "niri": ("noctalia", "dms", "ryoku"),
    "hyprland": ("noctalia", "dms"),
}
DISTROS = ("fedora", "arch", "cachyos")


def list_targets(inventory: dict[str, Any]) -> dict[str, Any]:
    distro = inventory["distribution"].get("id")
    return {
        "distribution": distro,
        "targets": [
            {"compositor": compositor, "shell": shell, "status": "unverified",
             "eligible_for_install": False,
             "reason": "No validated version-specific installation recipe or integration test"}
            for compositor, shells in TARGETS.items() for shell in shells
        ] if distro in DISTROS else [],
        "supported_for_install": [],
        "notice": "Catalog entries are research targets, not tested compatibility claims.",
    }


def plan(inventory: dict[str, Any], compositor: str, shell: str) -> dict[str, Any]:
    """Return a non-executable plan with explicit blockers and evidence."""
    distro = inventory["distribution"].get("id")
    known = compositor in TARGETS and shell in TARGETS[compositor]
    blockers = []
    if distro not in DISTROS:
        blockers.append("Distribution has no defined research target")
    if not known:
        blockers.append("Compositor/shell combination is not in the research catalog")
    if known and distro in DISTROS:
        blockers.append("No validated, version-specific installation recipe exists")
        blockers.append("No tested session integration or rollback procedure exists")
    compositor_found = inventory.get("compositor_executables", {}).get(compositor, {}).get("found", False)
    shell_found = inventory.get("shell_executables", {}).get(shell, {}).get("found", False)
    registered = [
        s["name"] for s in inventory.get("session_analysis", {}).get("registered_sessions", [])
        if compositor in s.get("compositor_candidates", [])
        and shell in s.get("shell_candidates", [])
    ]
    return {
        "schema_version": 1,
        "target": {"distribution": distro, "version": inventory["distribution"].get("version_id"),
                   "compositor": compositor, "shell": shell},
        "status": "blocked",
        "executable": False,
        "writes": [],
        "package_commands": [],
        "display_manager_policy": "preserve",
        "evidence": {"compositor_executable_found": bool(compositor_found),
                     "shell_executable_found": bool(shell_found),
                     "matching_registered_sessions": registered},
        "proposed_steps": [
            "Validate distribution/version and package provenance",
            "Verify compositor and shell dependencies and their integration",
            "Review unique session launcher and user configuration paths",
            "Back up files before any modification",
            "Request explicit approval before privileged operations",
            "Verify new session while preserving existing login options",
        ],
        "blockers": blockers or ["No installable recipe is available"],
        "notice": "Preview only: no packages, files, services or sessions are modified.",
    }
