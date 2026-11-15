# Recipe validation evidence

Status: implemented (proposal step 5, 2026-11-15). This is the checkable
part of recipe approval; the owner's signed sign-off remains a separate,
manual step.

- **Where:** `validation/<recipe-id>/r<revision>.json`, checked with
  `scripts/validation-report <file> [--require lab-validated|approvable]`.
- **Bound to recipe content:** the fingerprint covers the recipe definition
  (excluding its status) and its templates. Profile paths are normalized, so lab
  evidence applies to the identical production recipe. Any change to packages,
  notes, files or templates changes the fingerprint.
- **Bound to current code:** every case records the commit it ran on. If
  `src/desktopforge/helper`, `helperd`, `loginsession.py` or the templates changed
  since that commit, the case is **stale** and does not count.
- **Tiers** (`src/desktopforge/validation.py`):
  - `lab-validated`: all VM matrix cases pass on current code.
  - `approvable`: additionally real Intel and real AMD hardware runs.
  - `not-validated`: anything less.

  Only an approvable recipe may be proposed for sign-off and bundled in
  `desktopforge-helper`.

## Current state: `fedora45-niri-noctalia-lab` r2

The committed file records all 19 lab cases as passed, with environments,
commits and doc references. **The report says `not-validated`:** every case ran
before later code changes (the daemon restructuring, the launcher's journal
logging, repair and update rules), so all are stale. The hardware cases are
missing (no test machine yet). Next: re-run the lab matrix on current code,
ideally scripted, and record the new commits.
