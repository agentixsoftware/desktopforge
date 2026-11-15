# Removing a DesktopForge installation

Status: implemented in the VM-lab helper and verified in the KVM guest
(2026-11-15). GUI removal is not exposed; installation also remains disabled.

## Rules

The install record ([install records](INSTALL_RECORDS.md)) is the only source
of what may be removed. The planner (`src/desktopforge/helper/removal.py`) is
pure; the helper supplies fresh evidence and binds it into the plan hash.

| Item | Removed when | Otherwise |
| --- | --- | --- |
| Session entry, then config | Still a regular file with the recorded SHA-256; checked again through a no-follow handle, and the inode re-checked immediately before unlinking | Kept: `modified`, `missing`, `unsafe` or `unreadable` |
| Packages the install added | Still installed at the recorded version and architecture, and a DNF5 dry run (`clean_requirements_on_remove=False`) removes exactly that set | Kept: `changed` or `not-installed`. Dependents or any extra package **block** the removal |
| Packages the install reused | Never | Kept: `reused` |
| Per-user data, AccountsService remembered session | Never | Named in the preview (option A) |

Lab helper: preview/apply `remove-<install_id>` under
`org.desktopforge.lab.remove-session`. The preview states every removal and every
kept item with its reason, plus that removing `niri` also removes Fedora's
package-owned "Niri" session. Each step is journaled before it runs, and package
removal is verified with `rpm -q`. A strict removal record
`<removal_id>.removal.json` is written next to the install record, which is never
modified. The inventory reports `removed` or `partially-removed`; removed
installations no longer count as installed, and reinstalling is allowed.
Failures after a step starts are `failed_manual_recovery` and list what was
removed. A failed package removal whose outcome cannot be verified says so
("check rpm -q …"). Nothing claims a rollback.

## VM results (KVM, virgl, from backup `pre-niri-2026-11-14`)

| Step | Result |
| --- | --- |
| Fresh install | 7 packages recorded as installed by the install (all signed `655a4b02f577861e`), config, session entry |
| Real `dnf5 remove --assumeno` | Exactly the 7 packages; captured as `tests/fixtures/dnf5/remove-niri-noctalia.txt` |
| Removal (dialog) | Entry, config, then 7 packages removed; removal record written |
| After removal | RPM set identical to before install (1,942); DesktopForge and Fedora "Niri" entries gone; config dir empty; install record unchanged; inventory `removed`; plan back to a normal blocked preview; GNOME logout/login fine, no failed units |
| Reinstall | Allowed; new install record with the 7 packages |
| Edited config, then removal | Config kept (`modified`), with the preview saying why; entry and packages removed; RPM set identical again |
| Reinstall afterwards | Blocked: the kept file is not overwritten, and the message names the removal that kept it and what the user can do |

Not yet covered: dependents installed later by the user (unit-tested only), a
reboot between install and removal, a failed package transaction during removal
in the guest, and GUI presentation of removal.
