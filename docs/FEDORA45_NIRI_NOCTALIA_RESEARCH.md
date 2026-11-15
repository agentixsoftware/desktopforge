# Fedora 45 + Niri + Noctalia: recipe research

Review date: 2026-11-14. Status: **unverified, blocked, preview only**.
This is a source review and static inventory check, not a successful DesktopForge
installation or a compatibility certification. No installer, compositor, shell,
service or package transaction was started during this review.

## Why this is the first concrete preview

The PRD's original reference is an additive Niri/Noctalia session alongside an
existing desktop. Fedora publishes both package names, so a package proposal can
be grounded in distribution packaging rather than an opaque installer. The
research scope is mutable Fedora 45 with existing GDM or SDDM; neither display
manager has been tested with a DesktopForge-generated session.

The bundled recipe `fedora45-niri-noctalia`, revision 1, is schema version 2. It
proposes `niri` and `noctalia` through DNF5, then availability checks for `niri`,
`niri-session` and `noctalia`, then a new session file. Checks describe a future
verification step; the planner does not execute them. Existing executable presence
does not cause the proposal to skip packages or authorize reuse or an upgrade.

## Source findings

- [Fedora Niri package](https://packages.fedoraproject.org/pkgs/niri/niri/):
  the Fedora 45 listing at review time identifies `niri-26.04-2.fc45`. This
  establishes package naming and published availability, not enabled repository
  provenance or a proposed package transaction on this laptop.
- [Fedora Noctalia package](https://packages.fedoraproject.org/pkgs/noctalia/noctalia/):
  the Fedora 45 stable listing at review time identifies `noctalia-5.5.0-3.fc45`.
  Version selection, dependency resolution and conflict handling remain pending.
- [Noctalia installation](https://docs.noctalia.dev/noctalia/getting-started/installation/):
  upstream documents Fedora packages from the default repositories. Its v5
  implementation is distinct from the legacy Quickshell-based v4 implementation;
  treating either executable as sufficient evidence for reuse would be wrong.
- [Noctalia startup](https://docs.noctalia.dev/noctalia/getting-started/running-the-shell/):
  upstream recommends compositor autostart and documents Niri's
  `spawn-at-startup "noctalia"`. DesktopForge must model that in isolated
  configuration instead of editing a user's existing Niri configuration.
- [Niri systemd integration](https://github.com/niri-wm/niri/wiki/Example-systemd-Setup):
  `niri-session` provides systemd session integration. Starting a shell alongside
  a bare compositor does not establish correct service and logout lifetimes.

The URLs describe mutable upstream documentation; record the review date when
using them. Sources are review references, not signed recipe provenance.

## Read-only laptop observations

RPM ownership queries reported `niri-26.04-2.fc45.x86_64` for `/usr/bin/niri`,
`/usr/bin/niri-session` and `/usr/share/wayland-sessions/niri.desktop`.
`rpm -q` reported `noctalia-5.4.1-1.fc45.x86_64` and
`ryoku-desktop-niri-1.0.9-1.fc45.x86_64`. These installed versions differ from the
latest published Noctalia listing; no update was requested or performed.

The existing Noctalia session calls a local wrapper. Reading it showed that it
selects a per-user Niri config only if readable, and explicitly clears
`NIRI_CONFIG` from the user manager after the session returns. The installed
`niri-session` imports environment into the user manager but does not include
`NIRI_CONFIG` in its cleanup list. This supports a regression requirement around
cross-login environment leakage; it is not proof all failure paths are covered.

A system-wide Niri service drop-in pulls in `ryoku-bootstrap.service`, whose
installed definition calls `ryoku materialize`. The local setup also uses separate
accounts and protective configuration to keep shells apart. We read these facts;
we did not start those services or copy private user configuration into fixtures.
An additive preview must not silently remove, disable or rewrite those hooks.

## Why Ryoku remains metadata-only

The [Ryoku installer documentation](https://github.com/Ryoku-dev/ryoku/blob/main/ryoku-shell-installer/README.md)
describes a desktop conversion path that can change display-manager setup,
repositories, networking and user configuration. That does not establish a
minimal additive installation method compatible with DesktopForge's contract.
The existing working Ryoku setup remains a valuable multi-shell detection
reference. It does not justify calling its installer from a recipe, even with
an option named dry-run. No Ryoku installer was downloaded or executed.

## Gates before any installable recipe

1. Detect mutable versus Atomic Fedora and architecture, and resolve packages
   against reviewed enabled repositories without adding repositories silently.
2. Define isolated configuration and a launcher with explicit environment
   ownership. The recipe's `niri-noctalia-v5` template ID is a reserved design
   reference; an incomplete isolated-layout preview now exists, but no executable
   launcher or complete config generator is bundled yet.
3. Inspect effective user/global compositor service hooks and display-manager
   wrappers. Model conflicts without changing the host or disabling other shells.
4. Specify failure handling for missing user config, unavailable dependencies,
   an already running Niri user service, interrupted startup and logout. A missing
   Noctalia config must not silently launch some other shell and count as success.
5. In disposable Fedora 45 VMs, separately test a GNOME/GDM baseline and an
   SDDM baseline. Snapshot first; install only in the VM after explicit approval.
   Confirm old login paths and their configuration remain intact, a distinct
   DesktopForge session starts Noctalia v5, and logout leaves no shell/service or
   environment state that changes the next login.
6. Add a fixture with the observed Ryoku bootstrap hook and the multi-user layout.
   Confirm the preflight blocks unreviewed interactions instead of attempting a
   conversion. Test session ID collisions, absent per-user files and Noctalia v4
   alongside v5. Add real GPU coverage separately; VMs cannot establish it.

Current offline tests cover recipe validation, constraint mismatches, canonical
proposal order, collision-free ID previews, surfaced blockers/references and
preservation of input inventory. No VM login or installation tests have run.

## Follow-up: static preflight and isolated layout

The planner now models isolated configuration and launcher locations without
emitting runnable launcher code. Fixed-path read-only inventory identifies Niri
service hooks, SDDM configuration, environment hooks and occupied DesktopForge
namespaces. This advances gates 2 and 3 as design/observation work, without
establishing safe startup or effective config interpretation. See
[session preflight](SESSION_PREFLIGHT.md). All VM gates remain pending.
