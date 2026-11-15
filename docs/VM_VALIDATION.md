# Installation validation in disposable VMs

Status: preparation only. DesktopForge has no approved installation executor or
validated install recipe. Read-only observations do not satisfy the tests below.
This document scopes the next stage; it does not authorize changes to the host.

## First matrix

Start with a disposable Fedora 45 GNOME/GDM VM and the Niri/Noctalia recipe.
Repeat on an SDDM baseline before claiming SDDM support. Keep the Fedora COSMIC /
Niri / Ryoku laptop as a read-only reference until the installation procedure has
passed the disposable matrix. Hardware/GPU coverage remains a separate requirement.

A usable environment needs an OS image, sufficient disk and memory, a way to
observe the graphical login screen, and an independent recovery console. Record
whether the guest uses hardware acceleration or software emulation; neither
establishes real GPU compatibility. Snapshot or copy the guest disk before each
mutating case. Do not reuse the host's home directory, system bus, package database,
Wayland socket, credentials or user systemd manager inside the guest.

## Evidence before installation

Record the guest distribution, architecture, package versions, configured display
manager, registered sessions, relevant Niri hooks, and the exact DesktopForge
commit and recipe revision. Save `detect --json` and `plan --json` output.
The current plan is expected to return status `blocked` and CLI exit code 1.
Capture baseline hashes and relevant ownership/modes for existing session files,
display-manager configuration and existing user compositor/shell configuration.
Keep the original graphical login usable from the recovery console.

## Helper implementation gates

Before exposing any apply capability, define and test a versioned request protocol
with explicit operation classes, bounded inputs, fixed package-manager adapters
and allowlisted file locations. Do not accept arbitrary commands or unrestricted
paths. Authorization must bind to the exact reviewed plan and requesting user;
changed inventory or filesystem state requires renewed preflight and approval.

The implementation must record preexisting versus newly created resources,
backups, operation results and partial failures. It must reject stale plans,
unsafe symlinks, duplicate session destinations, unreviewed repositories and
unvalidated recipes. Keep Install disabled while these guarantees are incomplete.

## Cases required before advertising support

| Case | Required evidence |
| --- | --- |
| Clean reference installation | New session selectable and usable; original desktop still logs in |
| Compositor/shell already installed | Reuse decisions justified; existing configs and services preserved |
| Legacy or mismatched shell version | Plan blocked; no implicit upgrade or migration |
| Existing hooks and conflicting session IDs | Conflicts explained; no silent overwrite or modification |
| Authorization denied or request tampered with | Request rejected; no privileged changes |
| Failure during each operation | Accurate journal and recovery instructions; no false rollback claim |
| Repeated installation attempt | Idempotent result or explicit conflict without damage |
| Logout, failed startup and subsequent original login | Owned services stop; no leaked environment or configuration |
| Reboot | Original and added login paths behave as recorded |

Attach guest image identity, snapshot identity, logs, before/after comparisons,
graphical observations and verification results to each case. A passing unit test
or nested compositor trial is insufficient evidence for a login-session install.
Repository provenance, key trust and effective package policy must be checked in
the guest; the GUI's static repository declarations alone do not settle them.
