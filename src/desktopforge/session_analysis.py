"""Read-only, evidence-based session and shell discovery.

Session launcher text is untrusted; never execute Exec= or other desktop entries.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

SHELL_MARKERS = {
    "ryoku": ("ryoku",),
    "noctalia": ("noctalia",),
    "dms": ("dms", "dankmaterialshell", "dank-material-shell"),
}
COMPOSITOR_MARKERS = {"niri": ("niri",), "hyprland": ("hyprland",), "sway": ("sway",)}
SHELL_EXECUTABLES = {
    "ryoku": ("ryoku", "ryoku-shell"),
    "noctalia": ("noctalia-shell", "noctalia"),
    "dms": ("dms",),
}


def _markers(value: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    lower = value.lower()
    # Token boundaries prevent unrelated names such as 'admsomething' matching.
    return [name for name, terms in mapping.items()
            if any(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", lower)
                   for term in terms)]


def _entry_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}
    values: dict[str, str] = {}
    in_entry = False
    for line in lines:
        line = line.strip()
        if line == "[Desktop Entry]":
            in_entry = True
        elif line.startswith("[") and line.endswith("]"):
            in_entry = False
        elif in_entry and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key in ("Name", "Exec", "TryExec"):
                values[key] = value
    return values


def describe_sessions(sessions: list[dict[str, str]]) -> list[dict[str, object]]:
    result = []
    for item in sessions:
        fields = _entry_values(Path(item["path"]))
        evidence = " ".join((item["id"], item["name"], fields.get("Exec", ""), fields.get("TryExec", "")))
        result.append({
            **item,
            "exec": fields.get("Exec"),
            "try_exec": fields.get("TryExec"),
            "compositor_candidates": _markers(evidence, COMPOSITOR_MARKERS),
            "shell_candidates": _markers(evidence, SHELL_MARKERS),
            "confidence": "hint_only",
        })
    return result


def inspect_processes(proc_root: Path = Path("/proc")) -> list[dict[str, object]]:
    """Inspect own-readable /proc cmdlines only; no subprocess or ps invocation."""
    result = []
    try:
        pids = list(proc_root.iterdir())
    except OSError:
        return result
    for pid in pids:
        if not pid.name.isdecimal():
            continue
        try:
            with (pid / "cmdline").open("rb") as stream:
                raw = stream.read(8192)
        except OSError:
            continue
        if not raw:
            continue
        argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if not argv:
            continue
        executable = Path(argv[0]).name.lower()
        # Match executable name, not arbitrary command-line arguments.
        shells = [name for name, binaries in SHELL_EXECUTABLES.items() if executable in binaries]
        compositors = [name for name in COMPOSITOR_MARKERS if executable == name]
        if shells or compositors:
            try:
                cgroup = (pid / "cgroup").read_text(encoding="utf-8")[:4096].strip()
            except (OSError, UnicodeError):
                cgroup = None
            try:
                owner_uid = pid.stat().st_uid
            except OSError:
                owner_uid = None
            result.append({"pid": int(pid.name), "executable": executable,
                           "uid": owner_uid, "cgroup": cgroup,
                           "shell_candidates": shells, "compositor_candidates": compositors})
    return sorted(result, key=lambda entry: entry["pid"])


def session_analysis(sessions: list[dict[str, str]],
                     environ: Mapping[str, str],
                     processes: list[dict[str, object]]) -> dict[str, object]:
    """Avoid inferring active shell from registered sessions alone."""
    described = describe_sessions(sessions)
    current = [environ.get(key, "") for key in
               ("DESKTOP_SESSION", "XDG_SESSION_DESKTOP", "XDG_CURRENT_DESKTOP")]
    matched = [entry for entry in described if any(
        token and (token.lower() == entry["id"].lower() or token.lower() == entry["name"].lower())
        for token in current)]
    explicit_shells = sorted(set(sum((_markers(value, SHELL_MARKERS) for value in current), [])))
    running_shells = sorted(set(name for proc in processes for name in proc["shell_candidates"]))
    candidates = sorted(set(explicit_shells + running_shells))
    own_uid = os.getuid()
    user_services = sorted({
        name
        for proc in processes
        if proc.get("uid") == own_uid
        and "/user@" in (proc.get("cgroup") or "")
        and ".service" in (proc.get("cgroup") or "")
        for name in proc["shell_candidates"]
    })
    if len(explicit_shells) == 1:
        active = {"name": explicit_shells[0], "confidence": "environment_hint",
                  "reason": "Session environment names the shell; not runtime verification"}
    elif len(running_shells) == 1 and not explicit_shells:
        active = {"name": None, "confidence": "unknown",
                  "reason": "Shell process observed but cannot reliably associate it with this login session"}
    else:
        active = {"name": None, "confidence": "unknown",
                  "reason": "Insufficient or conflicting evidence to identify this session's shell"}
    return {
        "registered_sessions": described,
        "matching_session_hints": [entry["id"] for entry in matched],
        "running_shell_process_candidates": running_shells,
        "current_user_service_shell_candidates": user_services,
        "shell_candidates": candidates,
        "active_shell": active,
        "limitations": [
            "Registered sessions are not evidence of the currently running shell.",
            "A process may belong to another user or another login session.",
            "A user service can outlive a login session; its cgroup alone does not prove active-shell ownership.",
            "Exec entries are parsed as untrusted text, never executed.",
        ],
    }
