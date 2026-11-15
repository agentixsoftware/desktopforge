# SDDM baseline VM

Status: provisioned and used for the Niri + Noctalia lab cycle (2026-11-15).
It is a disposable guest, separate from the GNOME/GDM `kvm` guest.

## Profile and provisioning

`./scripts/desktopforge-vm --profile sddm ...` uses its own disk
(`run-sddm/`), SSH 22231, mutual-TLS console 22232, logs and backups
(`backups-sddm/`), so it can run alongside the `kvm` guest.

- **Disk:** a reflink clone of the verified `gnome-baseline-2026-11-14` backup,
  with the hash checked against its manifest.
- **Display manager** (logged lab-admin actions): `dnf5 install sddm
  sddm-wayland-generic` with no weak dependencies (6 MiB; it pulls in `libseat`
  and Weston for the greeter), `systemctl disable gdm`, `systemctl enable sddm`.
  GNOME remains as the pre-existing desktop.
- **Backup** `sddm-pre-niri-2026-11-15`: SDDM baseline plus the lab helper, with
  the pending offline update still present.
- **Start headless with 3D:** `--profile sddm --accelerator kvm --gl start`.
  Screenshots: `lab/tools/vnc-screenshot.py .desktopforge-vm/run-sddm/vnc.sock out.png`.
  QMP screendump has no surface for GL consoles; the VNC socket is in the private
  0700 lab directory.
- **Logins:** SDDM remembers the last session in `/var/lib/sddm/state.conf`
  (`[Last] Session=…`); lab runs preselect a session there and restart `sddm`.

## Results

| Check | Result |
| --- | --- |
| Inventory | Display manager `sddm` (configured); rendering `hardware` (virgl) |
| GNOME under SDDM | Logs in. GNOME notes "Screen Locking requires the GNOME display manager" (GNOME behavior, independent of DesktopForge) |
| Install (lab helper, Polkit dialog in GNOME) | Blocked first by the pending offline update; after discarding it, `completed`. Only **6** packages were recorded as installed: `libseat` was already present (required by SDDM) and was neither installed nor recorded |
| SDDM configuration | `/etc/sddm.conf`, `/etc/sddm.conf.d`, `/usr/lib/sddm/sddm.conf.d` byte-identical; display-manager symlink unchanged |
| SDDM session list | Shows "Niri + Noctalia (DesktopForge)" |
| Login through SDDM | `sddm-helper` starts `/etc/sddm/wayland-session` → `desktopforge-session niri-noctalia`; unit, `graphical-session.target` and XDG autostart active; Niri and Noctalia drawn |
| Logout (Super+Shift+E) | Back to the SDDM greeter; no processes, session variables, runtime files or failed units |
| Removal | 6 recorded packages and both files removed; `libseat` and `sddm` kept; RPM set identical to the SDDM baseline (1,948); SDDM configuration unchanged; preservation record identical; inventory `removed` |

Differences from GDM, found here:

- SDDM sets `XDG_SESSION_DESKTOP` from `DesktopNames` (`niri`); GDM uses the
  session file ID. The launcher passes either through unchanged.
- SDDM sends a session's stdout to `/dev/null` and stderr to
  `~/.cache/wayland-errors`, so the launcher's log was lost. **Fixed:** the
  launcher now writes to the journal socket (`journalctl -t desktopforge-session`)
  under any display manager, falling back to stderr. Verified under SDDM.
- No portal units failed at logout here (none had been started).

Not covered: SDDM with a Plasma (kwin) greeter, SDDM autologin or other
themes, X11 sessions, and the reference laptop's Ryoku greeter.
