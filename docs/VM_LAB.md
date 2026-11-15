# Local disposable Fedora VM lab

The local lab uses QEMU software emulation as the development session cannot
access `/dev/kvm`. It needs no host sudo, libvirt setup, system package installation
or graphical-session access. Guest administrative commands use a dedicated guest
account and apply only inside the disposable guest.

## State and access

All local images, SSH credentials, cloud-init seed, logs and screenshots live in
ignored `.desktopforge-vm/` under the checkout. That directory is private to the
account preparing it. Never commit it or copy host credentials into the guest.
No host filesystem is shared with the guest. Source is transferred explicitly by
SSH when required. SSH listens only on `127.0.0.1:22220`. QEMU's user-mode network
permits outbound guest networking; this is a test guest, not a malware sandbox.

The prepared guest uses Fedora Cloud Base Generic 45-1.4 x86_64 from the
[official Fedora download page](https://fedoraproject.org/cloud/download/).
The download was checked against the Fedora-signed CHECKSUM, verified using
Fedora's published OpenPGP keyring in the private lab directory:

- SHA-256: `50bdc5e70f6a24f540932d15411c1c6ae9fcfa40fb990d876d83c5cc823b2ad0`
- Signing fingerprint: `4F50A6114CD5C6976A7F1179655A4B02F577861E`

The downloaded base is retained separately from the working copy. The working
virtual disk was expanded from 5 GiB to 16 GiB using QMP `block_resize`; expansion
inside the guest was confirmed: the root filesystem reports 16 GiB and cloud-init reports done. QEMU uses
4 GiB RAM, two emulated vCPUs and virtio VGA. Software rendering cannot establish
real GPU compatibility. Cloud-init configures the guest-only `dfvm` user with a
fresh authorized key, locked password and passwordless guest sudo. No host SSH
agent is forwarded. The seed follows cloud-init's documented
[NoCloud SMBIOS discovery](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html).

## Prepared-lab controls

Run these from the checkout. No commands below install host packages:

```bash
./scripts/desktopforge-vm status
./scripts/desktopforge-vm ssh 'cat /etc/fedora-release; id'
./scripts/desktopforge-vm screenshot
./scripts/desktopforge-vm stop
```

`stop` requests graceful poweroff; wait for the supervisor to exit before copying
a working disk. For subsequent boots, run `./scripts/desktopforge-vm start` in a
persistent terminal or tool session. It runs in the foreground and supplies the
private cloud-init seed through a temporary loopback HTTP listener. It refuses to
start a second VM when the control socket responds. The downloaded base and
working disk are not automatically recreated or overwritten by the control helper.

Screenshots are written to `.desktopforge-vm/run/screen.ppm`; console output is in
`serial.log`. Host SSH settings are bypassed using `-F /dev/null` and the lab uses
its own known-hosts file. Never force-stop an unrelated process based on a saved
PID. If shutdown is unresponsive, investigate through the owned QMP socket before
considering a forced stop or discarding the guest disk.

## Validation scope

A cloud image is an automation starting point, not evidence of a Workstation
installation. Provision and verify the GNOME/GDM baseline inside the guest before
using it for preservation tests. Capture its configuration before introducing
Niri/Noctalia. Keep image verification and guest setup separate from DesktopForge
recipe validation. See [VM validation gates](VM_VALIDATION.md).

## Preservation records

`scripts/vm/record-baseline.py` collects hashes, ownership/modes, symlink targets,
package versions and OS identity without modifying guest configuration. It refuses
to run unless the hostname matches this dedicated lab guest. Invoke it inside the
guest with `--source-commit <commit>` and retain the JSON in the private lab area.
Capture another record after configuring GNOME/GDM and before any DesktopForge
installation test. The pre-desktop provisioning record is not that installation
baseline. Compare records and graphical behavior; hashes alone do not establish
that an existing desktop remains usable.
