"""DesktopForge command-line interface. All commands are currently read-only."""

from __future__ import annotations

import argparse
import json
import sys

from .detection import detect_system
from .recipes import RecipeError
from .planning import COMPOSITORS, SHELLS, build_plan, compatibility_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desktopforge", description="Inspect Linux desktop environment safely")
    sub = parser.add_subparsers(dest="command", required=True)
    detect = sub.add_parser("detect", help="Show read-only system inventory")
    detect.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    catalog = sub.add_parser("list", help="List unverified target combinations")
    catalog.add_argument("--json", action="store_true")
    plan = sub.add_parser("plan", help="Preview a blocked, read-only installation plan")
    plan.add_argument("--compositor", choices=COMPOSITORS, required=True)
    plan.add_argument("--shell", choices=SHELLS, required=True)
    plan.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "list":
        entries = compatibility_catalog()
        if args.json:
            print(json.dumps(entries, indent=2, sort_keys=True))
        else:
            for entry in entries:
                print("{distribution}: {compositor} + {shell} ({status})".format(**entry))
        return 0
    if args.command == "plan":
        try:
            result = build_plan(detect_system(), args.compositor, args.shell)
        except RecipeError as exc:
            print(f"Recipe validation failed: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Read-only preview: {args.compositor} + {args.shell}")
            print(f"Compatibility: {result['compatibility']}; plan: {result['status']}")
            print(f"Session ID preview: {result['session_id_preview']}")
            existing = result.get("existing_installation")
            if existing:
                print(f"Installed by DesktopForge: {existing['session']['name']} "
                      f"(install {existing['install_id']}, {existing['recorded_at']}, {existing['status']})")
            for warning in result.get("warnings", []):
                print(f"Warning: {warning}")
            for finding in result.get("preflight", {}).get("findings", []):
                print(f"Review: {finding['path']}: {finding['reason']}")
            layout = result.get("session_configuration_preview")
            if layout:
                print(f"Isolated user config draft: {layout['user_config']['relative_path']}")
                for file in layout["system_files"]:
                    print(f"System file draft: {file['path']}")
                print("Launcher and config are incomplete design previews.")
                print("Runnable trial: desktopforge-session; login-session integration remains unvalidated.")
            for blocker in result["blockers"]:
                print(f"Blocked: {blocker}")
            if result["operations"]:
                print("Operation proposals (not executed):")
                for operation in result["operations"]:
                    print(f"  {operation['id']} [{operation['privilege']}]: {operation['summary']}")
            else:
                print("No operations proposed.")
            print("Preserve existing sessions, display manager and user configuration.")
            for source in result.get("recipe_sources", []):
                print(f"Reference: {source}")
        # Nothing to do for an intact DesktopForge installation; anything else is blocked.
        return 0 if result["status"] == "installed" else 1
    if args.command == "detect":
        result = detect_system()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            dist = result["distribution"]
            print(f"Distribution: {dist['name'] or 'unknown'} ({dist['id'] or 'unknown'})")
            print(f"Version: {dist['version_id'] or 'unknown'}")
            dm = result["display_manager"]
            print(f"Display manager: {dm['name'] or 'unknown'} ({dm['confidence']})")
            session = result["current_session"]
            print(f"Current desktop: {session['desktop'] or 'unknown'}")
            print(f"Session type: {session['session_type'] or 'unknown'}")
            print(f"Package managers on PATH: {', '.join(result['package_managers_on_path']) or 'none found'}")
            for kind in ("wayland", "x11"):
                names = [s["name"] for s in result["sessions"][kind]]
                print(f"{kind.upper()} sessions: {', '.join(names) or 'none found'}")
            for category in ("compositor_executables", "shell_executables"):
                found = [name for name, evidence in result[category].items() if evidence["found"]]
                print(f"{category.replace('_', ' ').capitalize()}: {', '.join(found) or 'none found'}")
            analysis = result["session_analysis"]
            active = analysis["active_shell"]
            print(f"Active shell: {active['name'] or 'unknown'} ({active['confidence']})")
            registered_shells = sorted({shell for session in analysis["registered_sessions"] for shell in session["shell_candidates"]})
            print(f"Registered shell candidates: {', '.join(registered_shells) or 'none found'}")
            print("Note: Detection is evidence only; compatibility is not yet verified.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
