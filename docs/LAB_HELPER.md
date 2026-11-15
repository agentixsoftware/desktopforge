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

## Not yet covered

The helper has not yet been tested for caller disconnect during an apply
dialog; the probe has. Also not tested: locked/inactive sessions, two users,
concurrent applies from separate users, session removal (a v0.1 non-goal, needs ownership records), journal-disk-full in the guest, path
replacement races in the guest (unit-tested only), reboot during apply, and
SDDM. Real recipe operations (package transactions, session registration) need
their own operation classes and reviews before any of this approaches production.
