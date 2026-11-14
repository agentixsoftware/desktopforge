# Contributing to DesktopForge

DesktopForge is an open-source Linux desktop combination installer. Contributions are welcome.

## Principles
- Preserve users' existing desktops and display managers.
- Do not execute arbitrary remote installer scripts or introduce hidden privileged changes.
- Add support only with documented upstream installation methods and reproducible tests.
- Label unverified combinations experimental; do not claim compatibility from package presence alone.
- Keep the core engine independent of the GUI.
- Avoid destructive configuration writes; require backups, conflict detection, and explicit consent.

## Recipe contribution checklist
1. Identify supported distribution and version range.
2. Identify exact compositor/shell versions and prerequisites.
3. Document package provenance and required repositories.
4. Define nonprivileged and privileged steps using allowlisted operation types.
5. Include deterministic dry-run output and verification checks.
6. Test in a disposable VM and, when needed, real GPU hardware.
7. Verify the preexisting desktop session and display manager remain functional.
8. Document limitations, manual recovery, and test evidence.

## Development workflow (planned)
- Python 3, PySide6, pytest, YAML schema validation.
- PRs require unit tests and a VM integration report for new supported combinations.
- Security-sensitive changes require additional review.

## Security reporting
Do not post exploit details in public issues. Until private vulnerability reporting is enabled, contact the repository maintainers privately.

## Licensing
By contributing, you agree to license your contributions under Apache-2.0 and confirm you have the rights to submit them.
