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

## Rendering preflight

`src/desktopforge/helper/gpuprobe.py` opens each DRM render node through GBM,
initializes EGL on it the way Niri does, and reports whether the EGL device is
a software device (`EGL_MESA_device_software`) together with `GL_RENDERER`.
Either software signal classifies a node as software. Callers run it as a
separate process with a 15-second timeout and a clean environment.
`LIBGL_ALWAYS_SOFTWARE` does not change the GBM path, and other overrides are
not passed. Failures report `unknown`, never `hardware`.

- Inventory (schema 6) has `rendering`: `hardware`, `software-only`, `none` or `unknown`.
- Planner: Niri combinations are blocked unless rendering is `hardware`. No
  claim is made for other compositors until verified. An intact installation
  on such a system stays `installed` but carries a warning.
- Lab helper: recipes with `requires_hardware_rendering` run the probe as root
  in a transient unit (the sandbox has no `/dev/dri`). Anything but `hardware`
  blocks the plan, and the result is bound into the plan hash.
- GUI: a "Graphics" line in the system panel.

Observed: the virgl guest reports `hardware`, with renderer `virgl (Mesa
Intel(R) Iris(R) Xe Graphics (ADL GT2))`; the reference laptop reports
`hardware` (Intel Iris Xe). The software-only case on a non-virgl guest is
covered by unit tests and still needs a VM run.
