# DesktopForge — Technical Architecture

Version: 0.1 (draft) | 2026-11-14

## Architectural decision
Primary user experience: Python/PySide6 graphical wizard. Shared Python core with a CLI for automation and testing. Optional Textual TUI later. Initial distribution: native development/test packages; explore a portable AppImage for the unprivileged GUI only after cross-distro runtime testing. AppImage is not a privileged installer or a universal compatibility guarantee.

## Logical components
1. **GUI**: wizard, previews, progress, error/recovery presentation.
2. **CLI**: `desktopforge detect`, `list`, `plan`, `apply`, `verify` (proposed commands).
3. **System inventory**: `/etc/os-release`, package tools, session files, active display manager, user environment, GPU/driver checks. Treat detections as evidence, not infallible conclusions.
4. **Compatibility resolver**: versioned, tested constraints for distro/compositor/shell/driver/display manager.
5. **Planner**: merges distribution, compositor, shell, and integration recipes into an ordered declarative operation plan.
6. **Executor**: nonprivileged operations in user context; narrow privileged helper for approved package/service/file operations.
7. **Journal**: state transitions, pre-change snapshots, hashes, package transaction IDs when available, install records.
8. **Verifier**: validates session file, executable availability, essential services, and preservation of preexisting login session. Runtime login validation may still require a human or VM test.

## Trust boundaries
- Never run the GUI or entire playbook engine as root.
- The privileged helper must not accept arbitrary shell commands, unrestricted file paths, or unvalidated recipe operations.
- Authenticate privileged requests with polkit or an equivalent supported mechanism; authorize each sensitive operation class.
- Verify recipe provenance and constrain recipe syntax to a typed schema.
- Separate trusted, bundled recipes from experimental community submissions.
- Validate all target paths; reject traversal, unsafe symlinks, and writes outside allowlisted locations.
- Do not silently enable third-party repositories, change display managers, or install AUR packages.

## Recipe composition
- `distributions/<distro>.yaml`: package names, supported package manager, repository policies.
- `compositors/<name>.yaml`: compositor dependencies, launch/verification rules.
- `shells/<name>.yaml`: shell dependencies and startup requirements.
- `integrations/<compositor>-<shell>.yaml`: compatibility constraints, session launch and integration details.
- Compatibility is a versioned test result, not merely a claimed YAML flag.

### Illustrative recipe (NOT executable)
```yaml
schema_version: 1
id: fedora-niri-noctalia
status: unverified
constraints:
  distribution: fedora
  compositor: niri
  shell: noctalia
  preserve_display_manager: true
steps:
  - type: package_install
    packages: [niri]
    privilege: system
  - type: verify_dependency
    name: noctalia
  - type: create_session
    id: desktopforge-niri-noctalia
    template: sessions/niri-noctalia.desktop.j2
    privilege: system
checks:
  - type: session_exists
    id: desktopforge-niri-noctalia
```
This schema is a design sketch; actual dependencies, session startup, and install methods must be validated before release.

## Installation state machine
`detected -> planned -> approved -> preflight_passed -> backed_up -> applying -> verifying -> completed`

Failure states: `blocked`, `failed_recoverable`, `failed_manual_recovery`. Journal every transition. Do not label a partially applied plan as rolled back unless the reversal has been verified.

## Install record
Track install ID, timestamp, system fingerprint (non-identifying), recipe versions, plan hash, user approvals, package transaction IDs, packages newly installed vs preexisting, created/modified files with hashes, backup locations, session ID, verification results, and recovery steps. Avoid storing personal information or secrets in logs.

## Session strategy
- Prefer new unique `.desktop` files in `/usr/share/wayland-sessions/` when supported by the display manager.
- Preserve existing GDM/SDDM configuration and existing session definitions.
- A session wrapper starts the compositor and shell using compositor-specific documented methods; ensure lifecycle and environment are correct.
- User config is isolated under appropriate per-user configuration paths, with backup/conflict checks.
- Do not assume arbitrary compositor/shell combinations work because both packages install.

## Distribution adapters
- Fedora: DNF; RPM package ownership and transactions.
- Arch/CachyOS: pacman; optional AUR support excluded from first release unless explicitly reviewed.
- Debian: APT planned after MVP.
- Distro-specific package names, version availability, repository trust, and system service differences must be resolved by adapters.

## Testing strategy
- Unit tests for detection parsing, resolver, planner, schema validation, and path safety.
- Integration tests for adapters and helper authorization using controlled fixtures.
- Disposable VM matrix for each supported distro/version and GDM/SDDM baseline.
- Snapshot before install; verify old session remains available and new session is selectable.
- Fault injection: network failure, package conflict, insufficient disk, interruption, malformed recipe, missing executable, duplicate session ID.
- GPU-dependent checks require real hardware coverage; VMs are insufficient for every compositor path.

## Packaging
- Start with developer install and native RPM/pacman test packages to simplify helper deployment.
- Build AppImage only for GUI and nonprivileged logic after testing minimum glibc, Qt dependencies, FUSE/runtime behavior, and supported distributions.
- Privileged helper should be installed as a separately verified native package, never bundled as an implicitly trusted setuid executable.

## Future manager compatibility
Treat installation records as durable, versioned state from v0.1. Shared package ownership, user edits, and unmanaged installations must be reconciled before implementing removal/repair.

## Optional agent interface (future)
A Codex skill may consume the same structured inventory and deterministic plans
as the GUI and CLI. Detection, compatibility decisions, operation validation,
execution, and journaling belong in the shared core; the skill must not implement
a separate installer. No agent integration is currently implemented.

The initial useful scope is maintainer assistance: upstream research, explanation
of unknown evidence, failure diagnosis, and proposed recipe or test changes.
Treat upstream content and generated recipes as untrusted input. The core must
enforce typed recipe constraints and keep unsupported or unverified installations
blocked regardless of an agent's recommendation.

Later guided execution can call the reviewed core interfaces once available.
Existing plan approval and Polkit authorization requirements apply, and the
privileged helper continues to reject arbitrary commands and unrestricted paths.
An agent cannot promote a recipe to validated support or bypass these boundaries.

## Helper protocol proposal

The [helper protocol proposal](docs/HELPER_PROTOCOL.md) defines candidate caller
identity, request/approval binding, revalidation and operation boundaries for the
next VM experiments. It is a design proposal, not an implemented or deployed
privileged API. The [disposable VM lab](docs/VM_LAB.md) provides guest-only
administration and preservation records for validation.
