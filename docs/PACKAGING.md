# RPM packaging

Status: development build verified in the SDDM VM (2026-11-15). Not published;
no COPR exists yet. Proposal step 2 ([production proposal](PRODUCTION_PROPOSAL.md)).

`packaging/desktopforge.spec` builds two noarch packages from a `git archive`
tarball (`desktopforge-<version>/` prefix):

| Package | Contents |
| --- | --- |
| `desktopforge` | Python package (inventory, planner, GUI, CLI, helper core), `/usr/bin/desktopforge`, `/usr/bin/desktopforge-gui`, desktop entry. The experimental nested trial launcher is not shipped |
| `desktopforge-helper` | `/usr/libexec/desktopforge/desktopforge-helper` (daemon, production profile), `/usr/libexec/desktopforge/desktopforge-session` (login-session launcher), bus policy, D-Bus activation, sandboxed `desktopforge-helper.service`, Polkit actions `org.desktopforge.{install,remove,repair}-session`, session template, `/var/lib/desktopforge/installs` |

`%check` runs the helper, record, removal, repair, rendering, launcher and
profile tests (255 at the first build).

## Build (inside a disposable VM, never on the reference laptop)

```bash
git archive --format=tar.gz --prefix=desktopforge-0.1.0/ HEAD > desktopforge-0.1.0.tar.gz
# in the guest, with rpm-build pyproject-rpm-macros python3-devel desktop-file-utils
# systemd-rpm-macros python3-pytest installed:
rpmbuild -ba desktopforge.spec   # spec from packaging/, tarball in ~/rpmbuild/SOURCES
```

## Verified in the SDDM VM

- **Install:** `dnf install` of both RPMs; `rpm -V` clean; files root-owned.
- **`Info()` on `org.desktopforge.Helper1`:** profile `production`, recipes `[]`.
  Nothing is approved yet, so production offers nothing.
- **Lab recipes refused:** production rejects `fedora45-niri-noctalia-lab` and
  `lab-synthetic-marker` ("unknown recipe").
- **Service and Polkit:** the unit runs with the same sandbox as the lab
  helper, and the three production Polkit actions are registered separately
  from the lab's.
- **Packaged CLI:** `desktopforge detect` / `plan` work (SDDM, hardware rendering).
- **Uninstall:** `dnf remove` deletes the helper, policy and actions;
  `/var/lib/desktopforge/installs` stays while records remain.

A helper only removes or repairs installations recorded by itself (producer
check), so lab and production records can never be acted on by the other.

Follow-ups: build in mock or COPR rather than in a VM; package signing;
`rpmlint`; refuse or warn on helper removal while recorded installations
exist; SELinux policy (step 3).
