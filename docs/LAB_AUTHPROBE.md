# VM-lab authorization probe

Status: **lab experiment, disposable VM only.** The probe makes no system changes,
is not the production helper, and enables nothing in DesktopForge. Installation
remains unavailable. Production code never references the probe (a test enforces
this).

It is the first step of the [helper protocol proposal](HELPER_PROTOCOL.md): prove
that caller identity and Polkit authorization can be established from the system
bus alone before any operation is designed on top of it.

## What it is

| Piece | Location in repo | Installed in guest (root-owned) |
| --- | --- | --- |
| Service (stdlib + PyGObject, self-contained) | `lab/authprobe/desktopforge-lab-authprobe` | `/usr/local/libexec/desktopforge-lab/` |
| Bus policy | `org.desktopforge.LabAuthProbe1.conf` | `/etc/dbus-1/system.d/` |
| Bus activation | `org.desktopforge.LabAuthProbe1.service` | `/usr/share/dbus-1/system-services/` |
| Polkit action | `org.desktopforge.lab.authprobe.policy` | `/usr/share/polkit-1/actions/` |
| systemd unit | `desktopforge-lab-authprobe.service` | `/etc/systemd/system/` |

- One method, `Probe() -> a{sv}`, with **no input arguments**. The bus rejects any
  call carrying arguments (signature mismatch) before the code runs.
- Identity: the bus-assigned unique sender name, and the UID from the bus daemon's
  `GetConnectionUnixUser`. Nothing the caller claims is used.
- Authorization: Polkit `CheckAuthorization` with a `system-bus-name` subject for
  `org.desktopforge.lab.authprobe` (`allow_any=no`, `allow_inactive=no`,
  `allow_active=auth_admin` — no retained authorization), with user interaction.
- Fail-closed classification: only a well-formed `is_authorized=true` reply is
  `authorized`; malformed replies and every error map to `error`/`cancelled`.
- If the caller disconnects mid-dialog, the probe calls `CancelCheckAuthorization`.
- At most four pending checks, one per connection; exits after 60 s idle.
- Unit: runs the installed copy with `python3 -Is`; empty capability bounding set,
  `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, private network/devices,
  `AF_UNIX` only, `@system-service` syscall filter. Root UID is retained only so
  Polkit accepts checks for another subject.

## Lab install (inside the VM only)

```bash
# host, agent checkout: transfer source, then install with guest sudo
tar -c lab scripts/vm | ./scripts/desktopforge-vm --profile kvm ssh 'tar -x -C ~/desktopforge'
./scripts/desktopforge-vm --profile kvm ssh 'sudo -n ~/desktopforge/scripts/vm/install-lab authprobe'
# remove
./scripts/desktopforge-vm --profile kvm ssh 'sudo -n ~/desktopforge/scripts/vm/install-lab authprobe --uninstall'
```

The installer refuses to run unless the hostname is the dedicated guest. It copies
the reviewed files to fixed paths through root-owned temporary files and renames,
so the system service never executes from the user-writable checkout.

## Results (2026-11-14, Fedora 45 KVM guest, Polkit 127, dbus-broker 37, SELinux enforcing)

| Case | Caller | Result |
| --- | --- | --- |
| SSH session, UID 1000 with passwordless sudo | `gdbus` over SSH | `denied` — not an active local session |
| Caller passes `1000` or `s /etc/shadow` | `gdbus`, `busctl` | Rejected by the bus: `InvalidArgs`, type does not match `()` |
| root | `sudo gdbus` over SSH | `authorized` (Polkit's implicit root rule) |
| Graphical user, dialog cancelled | user-manager process in the GNOME login | GNOME Shell dialog shown; `dismissed` |
| Graphical user, correct password | same | `authorized` |
| Immediate repeat after approval | same | Dialog shown again (no retention) |
| Caller killed while dialog open | same | Dialog withdrawn; probe logged the disconnect; `denied` |
| Idle | — | Service exits after 60 s; bus-activates on next call |

Observations to carry forward:

- Guest SSH sudo is not GUI Polkit evidence: the same UID is denied over SSH and
  challenged in the graphical session, as intended.
- Polkit 127 treated a process in the user's systemd manager (`systemd-run --user`,
  not inside the login-session scope) as belonging to the active GNOME session and
  presented the dialog there. The real GUI is launched the same way in the lab.
- After the caller disappears, Polkit returned not-authorized rather than the
  `Cancelled` error. Both are fail-closed; the probe does not depend on which.
- Not yet covered: an inactive/locked graphical session, a second simultaneous
  user, fast-user-switching, and SDDM. These remain open before any operation class.

## Next steps

Bounded, versioned requests on top of this identity: a preview that returns a
short-lived token bound to sender, UID, recipe revision, plan hash and evidence
fingerprint; apply-time re-check of all of them; expiry/replay rejection; and a
durable journal — still with synthetic, guest-only operations, and still without
enabling GUI installation.
