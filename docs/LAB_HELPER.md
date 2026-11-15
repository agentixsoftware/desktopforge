# VM-lab helper: preview, approve, apply (built-in lab recipes only)

Status: **lab experiment, disposable VM only.** The only changes this service can
make are creating marker files in `/var/lib/desktopforge-lab/markers` and
registering `desktopforge-*` login sessions in `/usr/share/wayland-sessions`. It
is not the production helper, it cannot run real recipes, and DesktopForge
installation remains disabled. Follows the [helper protocol proposal](HELPER_PROTOCOL.md) and
builds on the [authorization probe](LAB_AUTHPROBE.md).

## Layers

**Helper core** — `src/desktopforge/helper/`, standard library and relative
imports only, so the files can be installed root-owned outside the checkout.
Nothing in the GUI or CLI imports it (tests enforce both).

| Module | Responsibility |
| --- | --- |
| `fsops.py` | Directory-handle operations: per-component `O_NOFOLLOW` walk from `/`, owner and group/other-write checks, `O_EXCL` file creation with fsync of file and directory, mode capped at 0644, strict names |
| `evidence.py` | Non-following records (type, mode, owner, hash, symlink target) of a directory; canonical-JSON SHA-256 fingerprint |
| `grants.py` | One-time grants bound to caller connection + UID, recipe revision, plan hash and evidence fingerprint; expiry; consumed before any check; global and per-UID bounds; dropped when the caller disconnects |
| `journal.py` | Per-install `O_EXCL` JSON-lines journal (0600), fsync per entry; a write failure stops execution |
| `sessions.py` | Strict `[Desktop Entry]` rendering from fixed values (`desktopforge-*` IDs, allowlisted absolute commands, no field codes, no control/escape characters, fixed key set); spec-conformant `Name` reading of existing entries |
| `executor.py` | Typed operations only (`create_file`, `register_session`, test-only `fail`) against named directory handles; journal before each step; verification by re-hash; `failed_recoverable` vs `failed_manual_recovery`; never reports a rollback |

**Lab service** — `lab/helper/`: `org.desktopforge.LabHelper1` on the system bus.

- `Preview(recipe_id)`: the ID must name one of the built-in synthetic recipes.
  The helper computes the plan and the evidence itself (`/usr/share/wayland-sessions`
  and the marker directory) and returns a plain-language summary, plan hash, blockers
  and, if not blocked, a grant token. There is no Polkit prompt, and nothing changes.
- `Apply(token, plan_hash)`: redeems the grant (one-time, same connection and UID,
  the plan hash the client approved, not expired). It then asks Polkit
  `org.desktopforge.lab.apply-synthetic` (`auth_admin`, active sessions only)
  with the caller's bus name, and cancels the check if the caller disconnects.
  After authorization it recomputes evidence and plan, and anything changed
  means rejection. Then it journals `approved` → `preflight_passed` → execution.
  Only one apply runs at a time.
- Recipes: `lab-synthetic-marker` (create one file), `lab-synthetic-fail`
  (create one file, then injected failure) and `lab-session-gnome` (register
  "DesktopForge Lab (GNOME)", which starts the stock `/usr/bin/gnome-session`).
- Each operation class has its own Polkit action:
  `org.desktopforge.lab.apply-synthetic` and `org.desktopforge.lab.register-session`.
- Session preflight blocks on an existing file, an existing session with the same
  display name (case-insensitive), or any session entry whose name it cannot read.
- Unit: root UID with an empty capability set, `ProtectSystem=strict`, private
  network; writable paths are only `StateDirectory=desktopforge-lab` and
  `/usr/share/wayland-sessions`. It imports the
  core only from `/usr/local/lib/desktopforge-lab/python`.

`lab/helper/desktopforge-lab-client` is the unprivileged test client. It keeps
one bus connection for preview and apply and has switches to misbehave on
purpose (`--tamper-plan`, `--other-connection`, `--replay`, `--pause`).

## Install in the guest

```bash
tar -c lab scripts/vm src/desktopforge/helper | ./scripts/desktopforge-vm --profile kvm ssh 'tar -x -C ~/desktopforge'
./scripts/desktopforge-vm --profile kvm ssh 'sudo -n ~/desktopforge/scripts/vm/install-lab helper'
./scripts/desktopforge-vm --profile kvm ssh 'sudo -n ~/desktopforge/scripts/vm/install-lab helper --uninstall'
```

## Results (2026-11-14, Fedora 45 KVM guest, Polkit 127, SELinux enforcing, btrfs root)

| Case | Result | Changes |
| --- | --- | --- |
| Unknown recipe (`fedora45-niri-noctalia`) | Preview rejected | none |
| SSH caller, valid preview | Apply `not_authorized` (denied) | none |
| Approved hash differs from preview | Rejected: plan does not match | none |
| Token used from a second connection | Rejected: different caller | none |
| GNOME user approves in Polkit dialog | `completed`; root-owned 0644 marker; 9-entry journal | marker only |
| Same token replayed | Rejected: unknown or already used | none |
| Repeat attempt with marker present | Preview `blocked`, no token, no dialog | none |
| Dialog cancelled | `not_authorized` (dismissed) | none |
| Session file added between preview and approval | Rejected after authorization: system changed | none |
| Injected failure after first operation | `failed_manual_recovery`, partial file listed, `rolled_back: false` | partial marker |
| Apply after 125 s (TTL 120 s) | Rejected: token expired, no dialog | none |

### Bug found and fixed during the run

The repeat-attempt case first returned `ready` even though the marker existed.
The helper kept the marker directory open from startup, and on btrfs a
long-lived directory handle did not list entries created after it was opened.
`os.listdir(fd)` reuses that handle. Create-exclusive would still have refused
to overwrite, but the preflight evidence was stale. Evidence now lists through a
fresh `openat(dir_fd, ".")`. The regression test also runs on the checkout's
filesystem, because pytest's `tmp_path` is tmpfs, where the bug does not occur.
It fails with the old code on btrfs.

A first run of the drift case was invalid. The test removed the drift before
the post-approval recheck, so applying was correct. The rerun keeps the drift
until the outcome arrives.

## Session registration results (2026-11-14, GDM 51.1.1, GNOME Shell 51.1)

| Step | Result |
| --- | --- |
| Preview | Plan names the exact file and command; `register-session` authorization; no blockers |
| Polkit dialog | Operation-specific message ("add a new DesktopForge lab login session…") |
| Apply | `completed`; 7-entry journal; file root:root 0644, SELinux `usr_t`, exactly the template |
| Preservation record diff | Only change: the new session file (other recorded paths, OS and package data identical) |
| DesktopForge inventory | Lists "DesktopForge Lab (GNOME)" beside GNOME and GNOME Classic |
| GDM Session Type menu | New entry listed; existing entries unchanged |
| Log in through new entry | Active Wayland session, `GDMSESSION=desktopforge-lab-gnome` |
| Log out, log in to original GNOME | Works; `GDMSESSION=gnome` |
| Repeat registration | Preview blocked: file exists and display name exists; no token, no dialog |

Finding: choosing a session at GDM updates the user's remembered default in
AccountsService (`Session` property). After using the added session, it becomes
the default for the next login until the user picks another. That is display
manager behavior, not a DesktopForge write, but recovery guidance for a broken
added session must account for it.

Stale default (tested): with the remembered session set to the lab entry and its
file moved away, GDM omitted the entry, preselected GNOME and logged in to
`GDMSESSION=gnome`. AccountsService kept the stale `desktopforge-lab-gnome`
value, so if the file returns, it becomes the default again. Removal and
recovery tooling should reset or at least report that value.

## Fedora 45 Niri + Noctalia lab install (2026-11-15)

Recipe `fedora45-niri-noctalia-lab`, one `org.desktopforge.lab.install-session`
authorization. Package operations use `src/desktopforge/helper/pkgtx.py`:
- **Fixed command:** DNF5 with `--repo=fedora --repo=updates`, signature checking
  forced on, no weak dependencies.
- **Strict parsing:** the transaction table is parsed strictly (the fixture is
  real guest output). Upgrades, removals, replacements, weak dependencies and
  every DNF warning block the plan.
- **Bound to the preview:** the previewed package set is part of the plan hash and
  is re-resolved before installing.
- **Verified after install:** each package's version and Fedora 45 signing key
  `655a4b02f577861e` are checked.

The commands run as transient units started through systemd, with output in
root-only logs under `/var/lib/desktopforge-lab/package-logs`.

| Step | Result |
| --- | --- |
| First preview | Blocked: a pending offline update (GNOME Software, `dnf5daemon-server`) would have been cancelled by the install |
| Lab-admin action | `dnf5 offline clean`, logged separately; not done by DesktopForge |
| Preview | 7 packages (niri, noctalia, 5 dependencies), config file, `niri validate`, session entry, disclosure notes |
| First apply | **Bug:** DNF installed all 7 packages, but the verifying `rpm -q` was killed by the helper's seccomp filter (`fchown` is in `@privileged`). The empty output was read as "not installed", and the result and journal said "No changes were made" — **false** |
| Recovery | `dnf5 history undo` as a logged lab-admin action; RPM set, `~/.config` and the preservation record identical to before |
| Fix | rpm results must account for every name, with status equal to the missing count. Failures after the transaction starts are `TransactionRan`, reported as verified packages or "state unknown", never "no changes". rpm now also runs outside the sandbox |
| Second apply | `completed`, 13-entry journal; the RPM diff is exactly the 7 reviewed packages; signer verified; config `etc_t`, session entry `usr_t` |
| GDM | Lists "Niri + Noctalia (DesktopForge)" and Fedora's package-owned "Niri" (as disclosed) |
| Login | Session active; `niri --session --config /etc/desktopforge/sessions/niri-noctalia.kdl` and `noctalia` running; `GDMSESSION=desktopforge-niri-noctalia`, `XDG_CURRENT_DESKTOP=niri` |
| Picture | **None.** Niri: "software EGL renderers are skipped". The VM GPU was `virtio-vga` without 3D, so only llvmpipe exists. GNOME accepts software rendering; Niri does not. Screen stayed on GDM's last frame |
| After ending the session | No Niri/Noctalia/xwayland-satellite processes, no session variables in the user manager, no runtime-dir leftovers, no failed units; no `~/.config/niri` (isolation held); `~/.config/noctalia` created (disclosed) |
| Remembered default | GDM now defaulted to the session that could not display; choosing GNOME explicitly worked and reset it |
| Original GNOME | Logs in (`GDMSESSION=gnome`) |

Also seen: Niri logged `import environment shell exited with exit status: 1`.
Its own import of session variables into systemd failed, so nothing leaked,
but portals and user services may lack `WAYLAND_DISPLAY`. That needs
investigating once the session renders.

Next: `scripts/desktopforge-vm --gl` gives the guest a virgl 3D GPU
(`virtio-vga-gl`, host OpenGL). Recipes need a real rendering preflight
(hardware or virgl EGL, not llvmpipe) rather than only a disclosure note.

## Niri + Noctalia with a virgl GPU (2026-11-15, `--gl`)

| Check | Result |
| --- | --- |
| Guest GPU | `virtio_gpu` with `+virgl`; QMP `screendump` returns "no surface" with `gtk,gl=on`, so screenshots come from `niri msg action screenshot-screen` inside the session |
| Login | Niri drives `Virtual-1` at 1496×850 with `/etc/desktopforge/sessions/niri-noctalia.kdl`; Noctalia bar, wallpaper and first-run wizard shown |
| Keybindings from the DesktopForge config | Hotkey overlay lists them; Super+Space opens the Noctalia launcher; Super+T opens Ptyxis; Super+Shift+E asks for confirmation and exits |
| DesktopForge inside the session | Inventory: current desktop `niri · wayland`, active shell Noctalia (environment hint), both found on PATH. **It offered `desktopforge-niri-noctalia-2`**: without install records it does not recognize its own installed session |
| Noctalia first start | Telemetry logged as disabled (the default). Blobless clones of `github.com/noctalia-dev/official-plugins` and `community-plugins` into `~/.local/state/noctalia`; data in `~/.local/state`, `~/.cache` and an empty `~/.config/noctalia`. Disclosure corrected |
| `import environment shell exited with exit status: 1` | Harmless for variables: they were imported into the user manager |
| systemd integration | `graphical-session.target` and `xdg-desktop-portal` stayed inactive: running `niri --session` directly bypasses `niri.service`, so no portals or XDG autostart |
| After logout (Super+Shift+E) | No processes. **Leak:** the still-running user manager kept `WAYLAND_DISPLAY`, `DISPLAY`, `XDG_CURRENT_DESKTOP=niri` and a stale `NIRI_SOCKET`; `/run/user/1000` kept `wayland-1`, its lock and Noctalia's lock |
| Next GNOME login | `GDMSESSION=gnome`; gnome-shell and new user services saw GNOME values and no `NIRI_SOCKET`. Leaked values were not observed there in this run |

The remaining work is a DesktopForge session launcher. It should start
`graphical-session.target` the way `niri.service` does, so portals and autostart
work, and on exit remove exactly the variables and runtime files it introduced
(as `niri-session` does for its five). It must also avoid `niri-session`'s import
of the whole login environment and stay independent of global `niri.service`
drop-ins such as the reference laptop's Ryoku hooks. Separately, install records
are needed so DesktopForge recognizes sessions it installed.

## DesktopForge session launcher (2026-11-15, recipe revision 2)

`src/desktopforge/loginsession.py` is installed root-owned as `desktopforge-session`;
the session entry runs `desktopforge-session niri-noctalia`. It is stdlib-only,
runs as the user, and is started by GDM. It:

- refuses if `graphical-session.target` or its own unit is already active
- runs `niri --session --config …` as the transient user unit
  `desktopforge-niri-noctalia.service` in `session.slice`, with the dependencies
  `BindsTo=`/`Before=graphical-session.target`, `graphical-session-pre.target` and
  `xdg-desktop-autostart.target`. These mirror `niri.service`, but the unit uses
  its own name, so global `niri.service` drop-ins do not apply
- passes only allowlisted login variables (`XDG_SESSION_ID`, seat/VT, session
  names, `LANG`, `LC_*`) and forces `XDG_CURRENT_DESKTOP=niri`
- after `READY`, records which of the five variables niri published, and ends
  the session if niri reports no outputs, so GDM returns instead of a black screen
- on compositor exit or logout signal: stops the unit and graphical targets;
  resets only graphical-session units that failed during this session; unsets
  or restores only variables still equal to what it published; removes the
  display's socket/lock files and Noctalia's lock only when no one holds the lock

| Check (virgl guest) | Result |
| --- | --- |
| Install with existing packages | Preview "No packages need to be installed / reused unchanged: niri, noctalia"; config and session entry created |
| Login | Unit active in `session.slice` with only allowlisted variables; `graphical-session.target`, `-pre` and `xdg-desktop-autostart.target` active |
| Portals | `org.freedesktop.portal.Desktop` activated with GNOME and GTK backends |
| Logout (Super+Shift+E) | Launcher unset all 5 variables, removed `wayland-1`, its lock and `noctalia-wayland-1.lock`; units and targets inactive; no processes |
| Portal failures | `xdg-desktop-portal-gnome`/`-gtk` exit 1 when the compositor disappears (same as with `niri.service`); the launcher resets just those and logs them; no failed units remain |
| Next GNOME login | `GDMSESSION=gnome`, no `NIRI_SOCKET`, no failed units |

The no-display fallback is covered by unit tests only; it has not run on the
non-virgl VM yet. D-Bus activation-environment values set by niri cannot be
removed through `UpdateActivationEnvironment`; dbus-broker launches
`SystemdService=` activations through the user manager, whose environment is
cleaned.

Lab note: a blind password entry went into a terminal (echoed on screen, in no
file) because a wait loop's `pgrep -f` matched its own command line. Waits now
use the helper's journal.

## Install records in the guest (2026-11-15)

See [install records](INSTALL_RECORDS.md). The pre-records revision-2 session
was removed as a logged lab-admin action and re-applied. Its record lists niri
and noctalia as **reused**: they were already present, although an earlier lab
run had installed them before records existed. CLI `plan` then reported
`installed` (exit 0), the GUI showed "Installed by DesktopForge", and the helper
blocked a re-apply. Appending a line to the config gave `modified` (blocked,
naming the file); moving the session entry away gave `incomplete`; restoring
both gave `intact` again.

## Not yet covered

The helper has not yet been tested for caller disconnect during an apply
dialog; the probe has. Also not tested: locked/inactive sessions, two users,
concurrent applies from separate users, session removal (a v0.1 non-goal, needs ownership records), journal-disk-full in the guest, path
replacement races in the guest (unit-tested only), reboot during apply, and
SDDM. Real recipe operations (package transactions, session registration) need
their own operation classes and reviews before any of this approaches production.
