# Install records

Status: implemented for the VM-lab helper and read by the inventory, planner, CLI
and GUI. Installation from the GUI remains unavailable.

## What is recorded

After an apply that changed anything, the helper writes one record per install
to `/var/lib/desktopforge/installs/<install_id>.json`: root-owned, mode 0644,
created exclusively, never overwritten. It uses the same ID as the helper's
journal. Schema 1 (`src/desktopforge/helper/records.py`) is strict, with no
extra or missing keys:

| Field | Meaning |
| --- | --- |
| `state` | `completed`, `failed_recoverable` or `failed_manual_recovery` |
| `recipe` | recipe ID and revision; `plan_hash` of the approved plan |
| `authorization` | Polkit action and caller UID |
| `target`, `session` | compositor/shell and the registered session ID and name |
| `files` | each created file with role (`session-entry`, `session-config`) and SHA-256; paths must be inside `desktopforge-*` session entries or `/etc/desktopforge/sessions/` |
| `packages.installed` | packages this install added: version, architecture, repository, RPM transaction ID, signing key ID |
| `packages.reused` | requested packages that were already present and left unchanged |

Records describe what happened; they never authorize anything.

## How records are used

`detect` (inventory schema 5) reads the directory read-only and bounded. On
the live system the directory and each record must be root-owned and not
writable by others. Symlinks, oversized files, invalid records and name/ID
mismatches are ignored with an issue. Every recorded file is re-hashed:

| Installation status | Meaning |
| --- | --- |
| `intact` | all files match; recorded packages present at recorded versions |
| `modified` | a file's content changed, or a recorded package was removed or changed version |
| `incomplete` | a file is missing, replaced by a non-regular file, or unreadable |
| `failed` | the install itself did not complete |

The planner treats an `intact` installation of the selected combination as
status `installed`, with its own session ID and no operations. The CLI prints
it and exits 0; the GUI shows "Installed by DesktopForge". Damaged
installations are blocked, naming each problem. A session with the same ID but
no record is still treated as foreign and gets a new ID. The helper refuses to
re-apply a recipe with a completed record.

Package status uses the inventory's tracked RPM names; dependencies outside
that list are recorded but not yet re-verified. Repair, removal and
`AccountsService` default-session reset are not implemented yet.
