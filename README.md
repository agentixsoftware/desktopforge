# DesktopForge

**Your Linux desktop. Your combination.**

DesktopForge is an open-source, beginner-friendly tool for adding compatible Wayland compositor and desktop shell combinations to an existing Linux installation, without replacing the working desktop or display manager.

> **Status: planning / v0.1 draft.** No installation functionality has been released. The target compatibility matrix is not yet validated.

## Initial scope

- Distributions: Fedora Workstation and Arch/CachyOS
- Compositors: Niri and Hyprland
- Shells: Noctalia and DankMaterialShell (DMS)
- Display managers: preserve existing GDM or SDDM
- First reference installation: Fedora Workstation with GNOME/GDM, adding a separate Niri + Noctalia login session

## Design principles

1. Additive installations by default; never silently replace an existing session or display manager.
2. Detect, plan and preview before any changes.
3. Use validated declarative recipes rather than opaque remote installer scripts.
4. Isolate privileged operations in a narrowly scoped, authorized helper.
5. Track installed packages, changed files, backups, verification and recovery guidance.
6. Share one installation engine between the GUI and CLI.

## Planned technology

Python + PySide6 GUI, Python CLI/core, YAML playbooks, a polkit-authorized native helper, and VM-based compatibility testing. A portable AppImage for the unprivileged GUI will be evaluated after native packaging.

## Current prototype: multi-shell detection

Run `PYTHONPATH=src python3 -m desktopforge detect` (or add `--json`). The read-only inventory now reports registered shell candidates (Ryoku, Noctalia, DMS), process evidence, and active-shell confidence. It does not assume that a registered shell is installed or running. See [Fedora 45 multi-shell reference](docs/REFERENCE_FEDORA45_MULTISHELL.md). Read-only inspection confirms the reference distribution, configured SDDM, four session definitions and executable availability. Active-shell validation remains incomplete because the development environment exposes no graphical-session variables or matching process evidence.

## Project documents

- [Product requirements](PRD.md)
- [Technical architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache License 2.0. See [LICENSE](LICENSE). Third-party dependencies and recipes remain subject to their respective licenses.

## Read-only catalog and preview

```bash
PYTHONPATH=src python3 -m desktopforge list
PYTHONPATH=src python3 -m desktopforge plan --compositor niri --shell ryoku
PYTHONPATH=src python3 -m desktopforge plan --compositor niri --shell noctalia
```

Both commands accept `--json`. The catalog describes target scope, including experimental Ryoku combinations; all entries are unverified for every version. Plans are deterministic for identical inventory inputs, preserve existing sessions and configuration, and contain no executable operations. Version 2 recipes can describe ordered, typed operation proposals; all remain blocked and are never applied. A blocked plan exits with status 1; successful inventory/catalog commands exit with status 0. Session IDs are previews, not filesystem reservations.

Recipe metadata now uses strict typed constraints for distribution ID, exact release
versions and configured display manager. The Fedora 45 + Niri + Ryoku + SDDM
reference has bundled **unverified metadata only**. Other versions are outside
that metadata's constraints; this does not establish upstream incompatibility.
See [recipe schema](docs/RECIPES.md) for the supported format and limitations.

The first concrete package/session preview targets Fedora 45 + Niri + Noctalia v5
with an existing GDM or SDDM. It proposes packages and a distinct session path,
shows source references, and stays **blocked** on isolated config, service hooks,
environment cleanup, package review and VM validation. No installation support is
claimed. See the [research and validation gates](docs/FEDORA45_NIRI_NOCTALIA_RESEARCH.md).

Read-only [preflight inspection](docs/SESSION_PREFLIGHT.md) now flags existing
service, display-manager and environment hooks for review, accounts for occupied
DesktopForge paths, and previews isolated Niri/Noctalia config locations. The
launcher and config remain incomplete drafts; no files or services are changed.

A [launcher lifecycle simulation](docs/LAUNCHER_LIFECYCLE.md) now tests startup,
shell readiness and ownership-aware environment cleanup using immutable fixture
state. It has no runtime adapter and cannot launch or alter a desktop session.

The internal [native launcher foundation](docs/LAUNCHER_RUNTIME.md) now implements
per-user locking, unfinished-attempt markers, pinned read-only config descriptors
and pidfd-based direct-child control. Tests use temporary files and trusted
fixture processes only. There is no production launch command or installed
session launcher; all inventory and planning commands remain read-only.

## Try the runnable launcher

From the repository root, in your actual Wayland desktop account's terminal:

```bash
PYTHONPATH=src python3 -m desktopforge.session_launcher --nested --check
PYTHONPATH=src python3 -m desktopforge.session_launcher --nested
```

This experimental Niri + Noctalia candidate opens a separate nested window using
fresh config, a private D-Bus session and its own transient user service. Quit
with Super+Shift+E or Ctrl+C in the launching terminal. It installs nothing and
does not alter existing desktop config/services. VM-tested production support is
still pending. See [trial instructions, standalone mode and diagnostics](docs/TRY_LAUNCHER.md).
