# DesktopForge — Product Requirements Document

Version: 0.1 (draft)  
Date: 2026-11-14  
Status: Proposed, not implemented

## Vision
DesktopForge is an open-source, beginner-friendly Linux desktop combination installer. It detects an existing Linux system, recommends validated Wayland compositor + shell combinations, and adds selectable login sessions while preserving the current desktop.

## Primary users
- Beginner Linux enthusiasts who want to experiment safely with desktop setups.
- Intermediate users who want repeatable installation rather than dotfile copy/paste.
- Maintainers contributing tested integration recipes.

## Goals for v0.1
1. Detect distribution/version, package manager, display manager, current desktop, existing sessions, compositor, shell, and relevant hardware/driver constraints.
2. Display only verified compatible target combinations for the detected system; explain experimental and unsupported combinations.
3. Reuse existing compositor or shell installations where feasible.
4. Preview changes in plain language, including repositories, packages, user files, privileged files, and service changes.
5. Add a distinct session without replacing the current desktop or display manager.
6. Save pre-change backups, execution logs, and a machine-readable installation manifest.
7. Verify registration and provide safe instructions to log out and choose the new session.
8. Fail safely and give recovery instructions when operations cannot be automatically reversed.

## Initial target matrix (not yet validated)
- Fedora Workstation: Niri + Noctalia; Niri + DMS; Hyprland + Noctalia; Hyprland + DMS.
- Arch Linux and CachyOS: same four combinations, subject to separate validation.
- Existing GDM or SDDM is preserved.
- First reference scenario: Fedora Workstation with GNOME/GDM, adding Niri + Noctalia.

Each distro/version/combination is *unsupported* until integration tests pass. Do not treat target scope as a compatibility guarantee.

## User flow
1. Welcome and safety explanation.
2. Detect system and report detected facts, confidence, and blocking issues.
3. Choose compositor (installed/new) and compatible shell.
4. View compatibility, required components, disk/network needs, and risk level.
5. Review exact plan, backup targets, and permissions; explicitly approve.
6. Execute with progress, logs, and actionable error handling.
7. Validate files and session registration; show next-login steps and recovery path.

## Functional acceptance criteria
- A dry-run produces a deterministic, readable plan without modifying the system.
- Installing a supported combo does not disable, replace, or reconfigure the existing display manager.
- Existing session files are not overwritten; generated session names and IDs are unique.
- All privileged actions require explicit authorization and are restricted to an allowlisted operation set.
- No downloaded installer script is piped directly into a shell or executed without review.
- Every managed change has a manifest entry and relevant pre-change backup.
- Re-running a successful plan is idempotent or clearly reports conflicts.
- Partial failures leave the previous login path available, with accurate recovery guidance.
- User home configuration is not overwritten without a separate, explicit confirmation.

## Non-goals for v0.1
- Full uninstall, repair, automatic upgrades, or cross-desktop configuration migration.
- Automatically replacing GDM/SDDM or changing the default login session.
- Supporting arbitrary community recipes or every Linux distribution.
- Promising full system rollback of package transactions.
- Supporting every GPU/driver configuration.

## Future phases
- v0.2: More distros, compositors, shells, and tested combinations.
- v0.3+: Managed updates, repair, removal, shared-dependency tracking, session inventory.
- Later: Community recipe registry with provenance, signing, reviews, and compatibility telemetry (opt-in only).
- Later: An optional Codex skill that uses DesktopForge's shared core and CLI for investigation, planning, and guided operation.

## Agent-assisted workflows (future direction)
The GUI remains the primary interface for beginners. A future Codex skill can
provide an additional interface to the same inventory, compatibility resolver,
planner, and approved execution capabilities. Using DesktopForge must not require
Codex or an agent account.

An earlier development-focused skill may research unfamiliar combinations,
diagnose failures, and draft recipes and regression tests. Agent-generated recipes
remain unverified until reviewed and validated against the same test matrix as
other recipes. Agent suggestions do not establish compatibility.

Any later installation workflow must use the shared execution and authorization
boundaries, including explicit plan approval, the narrow privileged helper,
installation records, and recovery guidance. Agent flexibility does not expand the
helper's allowed operations. This direction adds no agent deliverable to v0.1.

## Success measures
- First-install completion rate in disposable test VMs.
- Zero regression of preexisting login paths in supported tests.
- Median time from launch to first selectable session.
- Number of combinations with passing automated tests.
- Number and severity of manual recovery incidents.

## Open decisions
- Confirm dependency license compatibility.
- Determine supported distro versions and minimum package versions after feasibility spikes.
- Choose helper authorization and installation mechanism after security review.
