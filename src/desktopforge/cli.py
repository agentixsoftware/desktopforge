"""DesktopForge command-line interface. All commands are currently read-only."""

from __future__ import annotations

import argparse
import json
import sys

from .detection import detect_system


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desktopforge", description="Inspect Linux desktop environment safely")
    sub = parser.add_subparsers(dest="command", required=True)
    detect = sub.add_parser("detect", help="Show read-only system inventory")
    detect.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)
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
            print("Note: Detection is evidence only; compatibility is not yet verified.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
