# Repairing a DesktopForge installation

Status: implemented in the VM-lab helper, offered by the GUI's VM lab mode,
and verified in the KVM guest (2026-11-15). Production installation remains
disabled.

## Rules

Repair restores **exactly** what the install record describes. The planner is
`src/desktopforge/helper/repair.py` (pure); the helper supplies fresh evidence.

| Situation | Repair |
| --- | --- |
| Recorded file missing | Recreated only if the current recipe renders content with the recorded SHA-256. If the recipe changed, repair blocks rather than writing something different |
| Recorded file edited | **Blocked**: never overwritten. The message says to move it aside, after which it counts as missing and is restored |
| Symlink or other object in its place, or unreadable | Blocked |
| Package the install added is missing | Reinstalled at the recorded version only; if the repositories offer a different version, blocked ("repair does not change versions") |
| Reused package is missing | Reinstalled, so the session works; removal still treats it as reused |
| Resolution would add unrecorded packages | Blocked |
| Package present at a newer version | Not damage: the installation stays `installed` with an "updated since installation" warning |
| Recipe revision changed since installation | Blocked |
| Installation removed | Blocked: install again instead |

Order: packages, then config, then `niri validate`, then the session entry last,
so the login screen offers the session only once everything it needs is back.

Lab helper: `repair-<install_id>` under `org.desktopforge.lab.repair-session`.
The preview lists what will be restored and states that edits are not
overwritten and versions not changed. A strict repair record
`<repair_id>.repair.json` is written next to the untouched install record. The
inventory shows the last repair in the installation's history. The GUI shows
**Repair in VM lab…** next to "Remove from VM lab…" only when the installation
is `modified` or `incomplete`.

## VM results (KVM GNOME/GDM guest, through the GUI)

| Case | Result |
| --- | --- |
| Session entry deleted and dependency `tomlplusplus` force-removed | CLI and GUI: `incomplete`, naming both; GUI offered "Repair in VM lab…" |
| Repair (review, Polkit, progress) | Reinstalled `tomlplusplus 0:3.4.0-8.fc45` and restored the entry; repair record written; rescan `intact`; both files byte-identical to the recorded hashes |
| Config edited, then repair | Refused before authentication: "…was edited; repair does not overwrite it. Move it aside to have the original restored." The edit was untouched |
| Edited config moved aside, then repair | Original restored (matches the recorded hash); the user's edit kept in the moved-aside copy; `intact` |

Related change: package updates by normal system maintenance no longer mark an
installation as modified (see [install records](INSTALL_RECORDS.md)), and
removal removes a package the installation added even after it was updated.
