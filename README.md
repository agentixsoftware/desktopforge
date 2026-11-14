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

## Project documents

- [Product requirements](PRD.md)
- [Technical architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache License 2.0. See [LICENSE](LICENSE). Third-party dependencies and recipes remain subject to their respective licenses.
