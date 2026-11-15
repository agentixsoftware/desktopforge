# DesktopForge — Roadmap

Version 0.1 (draft) | 2026-11-14

## Milestone 0 — Discovery and feasibility
- Verify Fedora/Arch package availability and documented startup procedures for Niri, Hyprland, DMS, Noctalia.
- Verify session registration under GDM and SDDM without replacing display managers.
- Confirm license/name availability and test matrix.

**Exit:** One reference combination has a reproducible, manually verified installation procedure.

## Milestone 1 — Read-only detection + planning
- Build CLI inventory, compatibility catalog, typed recipe schema, and dry-run planner.
- Add tests and plain-English plan output.

**Exit:** `detect`, `list`, `plan` work without any system writes.

## Milestone 2 — Secure installation foundation
- Implement narrow privileged helper, polkit policy, journal, backup/conflict handling, and verification.
- Create VM test harness and failure injection.

**Exit:** Automated installation of the Fedora + Niri + Noctalia reference session without altering GNOME/GDM.

## Milestone 3 — GUI wizard
- PySide6 onboarding, selection, plan preview, authorization, progress, verification, recovery instructions.
- Usability test with beginner Linux users.

**Exit:** First-time users can add a supported session with no terminal commands after supported helper setup.

## Milestone 4 — Expand supported matrix
- Validate Fedora and Arch/CachyOS target combinations one by one.
- Release native test packages; evaluate AppImage GUI packaging.

**Exit:** Each advertised combination passes the published test matrix.

## Later
- Debian support, TUI, managed repair/uninstall/update, additional compositors and shells, signed community recipe registry.
- Phase in an optional Codex skill over the shared core and CLI. Begin with
  maintainer research, diagnostics, and draft recipes/tests after the read-only
  interfaces stabilize; this can precede installation support. Add guided
  installation only after the helper, approval flow, journal, recovery, and VM
  validation are ready. Agent-generated recipes require review and the normal
  compatibility test matrix. This is outside the current milestone's exit criteria.

## Risk register
- Third-party installer behavior and changing upstream shell integrations.
- Package versions and repository availability differ by distro release.
- GPU/driver-specific compositor behavior.
- Partial package transactions cannot always be undone.
- Privilege escalation and recipe supply-chain risks.
- AppImage portability limitations.

## Indicative effort
6–10 weeks for a narrow technical MVP is an early estimate, not a commitment; broad beginner-ready support may take substantially longer.

## Current implementation notes

Read-only `detect`, `list`, typed recipe validation and deterministic blocked
planning are implemented. An early Milestone 3 GUI now exposes this core through
system inventory, target choices and plan/requirements views. This is a preview
with installation permanently unavailable; it does not imply completion of the
Milestone 2 privileged helper or VM installation/lifecycle validation.
