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

Every recorded package, dependencies included, is re-checked with one read-only
`rpm -q` (fixed argv, every name accounted for, status equal to the missing
count). A missing or changed package makes the installation `modified`. If the
query cannot answer, it is `unverified` and blocked, not `intact`. Verified in
the guest by force-removing the dependency `tomlplusplus` (`modified`, naming it)
and reinstalling it (`intact`). Repair is not implemented; removal is described
in [REMOVAL.md](REMOVAL.md). The `AccountsService` default session is never
reset (option A).

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

Observed:
- The virgl guest reports `hardware`, with renderer `virgl (Mesa Intel(R)
  Iris(R) Xe Graphics (ADL GT2))`; the reference laptop reports `hardware`
  (Intel Iris Xe).
- On the same guest booted without `--gl`, the probe reports `software-only`.
  Both signals agree: `EGL_MESA_device_software` and `llvmpipe (LLVM 23.1.2)`.
  The CLI shows the installed session as `installed` with the "would show no
  picture" warning, a fresh Niri + DMS plan is blocked naming llvmpipe, and the
  lab helper refuses the Niri recipe.

## Launcher no-display fallback (non-virgl guest)

Choosing "Niri + Noctalia (DesktopForge)" at GDM: niri logged "software EGL
renderers are skipped". About 5.5 s later the launcher logged "no usable
display … ending the session so the login screen returns". It then unset its
five variables, removed its three runtime files and found no failed units,
and the GDM user list returned. Previously this left a frozen screen.

Remaining observations:
- `oo7-daemon-login`, the login keyring daemon PAM starts for every graphical
  login, kept the ended session in `closing`. It is not started by
  DesktopForge and does not affect the next login.
- GDM remembered `desktopforge-niri-noctalia` as the default even though it
  could not display, so a plain login bounces back to GDM until another
  session is chosen. Choosing GNOME explicitly worked and reset the default.
  Decision (option A): DesktopForge does not reset that AccountsService value.

## Launch outcomes (per user)

The launcher runs as the user and cannot write the root-owned install record.
It therefore keeps its last 10 outcomes (`started`, `no-display`,
`start-failed`, `refused`) per profile in
`$XDG_STATE_HOME/desktopforge/launches/<profile>.json` (default
`~/.local/state/…`). The directory is 0700, the file 0600; the file is
replaced atomically without following symlinks, and writing is best effort.
The inventory attaches the latest outcome to the matching installation.

If the last login failed, an intact installation stays `installed` and gains a
warning: the login did not start, the reason, and that the login screen may
still preselect the session. The CLI prints it; the GUI shows it in the plan
summary. A later successful start clears it. A session cannot leave a message
on GDM's greeter through a supported interface, so the message appears the
next time DesktopForge is opened, plus in the journal.

Verified on the non-virgl guest: the bounce wrote `no-display`, the CLI and GUI
showed the warning, and GDM's remembered value changed only when the user
chose GNOME.
