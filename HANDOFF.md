# DesktopForge agent handoff

Prepared on 2026-11-14 America/Los_Angeles (some guest logs are dated 2026-11-15 UTC).
This is a continuation guide for the existing checkout and disposable VM lab.
Recheck runtime state and permissions before acting; the GUI and VM have been
verified, but they are not currently guaranteed to be running.

## 0. Latest update — supersedes conflicting statements below

Later session, 2026-11-14:

- Git metadata writes, pushes and `/dev/kvm` all work from the agent session.
  The agent boots the KVM guest itself, headless, in a background task:
  `./scripts/desktopforge-vm --profile kvm --accelerator kvm start`. No host-terminal
  launch is needed unless that changes; screenshots come from QMP.
- `-no-reboot` is gone: guest reboots reset in place (verified).
- Verified cold backup `gnome-baseline-2026-11-14` (configured GNOME/GDM, refreshed
  evidence, before any helper install). Restore with
  `./scripts/desktopforge-vm --profile kvm restore gnome-baseline-2026-11-14`
  after a graceful `stop`. Restore round trip and boot from it were verified.
- Refreshed guest evidence is in the ignored `.desktopforge-vm/evidence/2026-11-14-refresh/`.
- The lab authorization probe is implemented and tested in the guest; see
  `docs/LAB_AUTHPROBE.md`. It is installed in the running guest's working disk,
  not in the baseline backup.
- The guest checkout is still a transferred archive, not a Git clone; see
  `~/desktopforge/SOURCE_REVISION` inside the guest.
- The lab helper (preview/approve/apply, synthetic recipes only) and the reusable
  helper core in `src/desktopforge/helper/` are implemented and VM-tested; see
  `docs/LAB_HELPER.md`. Guest services install with `scripts/vm/install-lab
  {authprobe,helper}` (replaces `install-authprobe`).
- The user can now watch the VM: they launched it from their `ryoku` terminal with
  `--show`, and the agent drives it over SSH/QMP. If that window is closed, ask
  them to rerun the documented `--show start` command (or boot headless yourself).
  Announce before sending keystrokes or triggering Polkit dialogs.
- Niri needs 3D: the user starts the VM with `--gl` (virgl). QMP `screendump` then
  fails ("no surface"); inside Niri use `niri msg action screenshot-screen`. For GDM
  logins without sight, preselect via AccountsService `SetSession` and restart gdm
  (log both in the guest's `~/evidence/lab-admin.log`). Never type the password
  without a confirmed dialog/greeter focus.
- Latest: Fedora 45 Niri + Noctalia lab recipe revision 2 installed in the
  running guest through the helper; its session uses the `desktopforge-session`
  launcher and passed login/logout/cleanup/GNOME checks (docs/LAB_HELPER.md).
  Backups: `gnome-baseline-2026-11-14`, `pre-niri-2026-11-14`.

## 1. Read this first

- Repository: <https://github.com/agentixsoftware/desktopforge>
- Agent checkout: `/home/vick/Projects/desktopforge`.
- Branch: `main`.
- Latest committed/pushed checkpoint: `9cde97ed9b70e5f39b8c4365f3aeffedbefd65e6`.
- Two preexisting working-tree changes are tested and must be preserved:
  `src/desktopforge/gui/window.py` and `tests/test_gui.py`.
- This handoff is newly created and may also appear as an untracked file.
- The GUI works. Installation is intentionally unavailable. There is no production
  privileged helper, executor, validated installation recipe, or completed login
  preservation/lifecycle matrix.
- The accelerated Fedora VM was provisioned, logged into GNOME, and used to run
  DesktopForge and the tests. At handoff preparation, its SSH/QMP ports were closed
  and the control helper reported connection refused. It needs a host-terminal
  restart before further guest work.
- Workspace file writes and GitHub reachability work in the current agent session,
  but Git metadata is explicitly read-only. `git add` failed creating
  `.git/index.lock`. No commit was created by that attempt. Do not discard the
  changes or circumvent the restriction using another index, Git directory, or API.

## 2. User intent, authorization, and collaboration preferences

The user is Vick Reddy; requested Git identity:

```text
Vick Reddy <agentixsoftware@gmail.com>
```

The user wants a beginner-friendly, GUI-first application that adds supported
Wayland compositor/shell combinations as additional login sessions while preserving
the original desktop and display manager. Python core/CLI, PySide6 GUI, declarative
recipes, a narrow Polkit helper, and VM validation are the planned architecture.
Initial distributions are Fedora and Arch/CachyOS; compositors are Niri and
Hyprland; shells are Noctalia, DMS, and experimental Ryoku.

The user explicitly authorized commits and pushes at logical stages and asked us
to keep working until we actually need an answer. Do not repeatedly request push
approval. That authorization does not override tool permission restrictions or the
host safety rules below.

Working preferences:

- Take action; avoid handing routine work back to the user.
- When user intervention is necessary, give exact terminal commands and specify
  whether they belong on the physical host or inside the VM and under which user.
- Explain a permission failure concretely. Do not repeatedly troubleshoot GitHub
  authentication when the actual problem is DNS, sandbox networking, or `.git` writes.
- The user wants to see interesting milestones. Announce them and show actual VM
  screenshots or the live VM window. GDM and DesktopForge running in GNOME have
  already been shown. Do not show mockups as runtime evidence.
- Give concise progress updates during long work. The initial software-emulated
  setup took far too long; use the accelerated guest for subsequent work.
- No subagents have been requested. Current collaboration instructions prohibit
  proactive delegation unless the user or applicable instructions request it.

## 3. Safety boundaries: physical host versus disposable guest

### Physical reference laptop: keep its desktop read-only

Do not install/remove/upgrade host packages, use host sudo, or change SDDM, Niri,
Ryoku, registered session launchers, existing systemd units, user configuration,
account permissions, or group memberships without explicit permission. Never run
untrusted downloaded installation scripts.

Repository edits, project-local test dependencies already prepared, temporary
fixtures, and unprivileged QEMU processes are the development workspace. All
privileged desktop setup so far occurred inside the disposable guest, not on the
physical reference desktop.

### Disposable VM: development and validation environment

The user authorized a VM with sufficient administrative access so the agent needs
less intervention. The dedicated guest account has passwordless guest sudo.
Guest package installation and lab setup are within this scope. Keep that scope
obvious in commands: use `scripts/desktopforge-vm --profile kvm ssh '...'`.
Do not confuse guest sudo with permission for host sudo.

Do not enable DesktopForge production installation merely to make a demo work.
Lab policy experiments must remain separate from production apply authorization.
The fact that both packages or executable paths exist does not prove compatibility,
repository provenance, signature trust, or safe reuse.

## 4. Accounts and access: the important complication

The physical graphical login runs as `ryoku` (UID 1001). The agent operates as
`vick` (UID 1000). The user deliberately keeps the Ryoku graphical setup under
`ryoku` to avoid configuration conflicts.

The existing shared Projects mount exposes the checkout to the graphical user at:

```text
/home/ryoku/vick/Projects/desktopforge
```

Do not chmod Vick's private home or modify that existing mount. The normal user
already successfully launched both DesktopForge and the KVM VM through the shared
path. The GUI inventories the account that launches it; an agent-side inventory
without graphical-session environment cannot establish the active Ryoku shell.

The tool runtime cannot access `/dev/kvm`, even though the normal `ryoku` terminal
reported `KVM_READY`. Host sysfs showed KVM exists. The tool also could not connect
to Vick's host user bus, so do not try to solve this by changing existing host
services or D-Bus configuration.

Git networking initially failed in earlier sessions, then worked after CLI
restarts. GitHub authentication was also originally in Ryoku's keyring; the user
subsequently configured Vick's GitHub authentication. Many pushes succeeded.
Most recent public `git ls-remote` succeeded. The present commit blocker is the
read-only Git metadata mount, not evidence of bad GitHub credentials.

## 5. Current Git state and the pending fix

At handoff inspection:

```text
## main...origin/main
 M src/desktopforge/gui/window.py
 M tests/test_gui.py
```

The pending fix is small and already verified on host and guest:

1. The tab stylesheet reduces horizontal padding from `15px` to `8px`.
2. A regression test, `test_all_plan_tabs_are_visible_at_minimum_window_width`,
   resizes the window to 880x720, scans fixture inventory, and verifies that all
   five tab rectangles fit in the tab bar, including Packages.

The new test failed before the fix: Packages extended beyond the visible tab bar.
It passes after the fix. This reproduces the user's earlier report that Packages
was missing; the tab was hidden behind scroll arrows at narrow widths.

Last successful complete checks, including this uncommitted fix:

| Environment | Result |
| --- | --- |
| Host `.venv-gui`, Qt offscreen | **319 passed** |
| Accelerated Fedora VM, native PySide6 | **318 passed, 1 skipped** |

The guest skip was `tests/test_session_launcher.py`: Niri parser is not installed.
This is expected for the clean pre-install GNOME baseline. It is not a skipped GUI
suite: native PySide6 was installed and GUI tests ran.

`git diff --check` passed. The guest also received the modified GUI and test files
by explicit file transfer, so the guest checkout is an archive of `9cde97e` plus
those two changes. It has no `.git` directory.

Once Git writes are permitted, review and commit the pending fix and this handoff.
Suggested fix message: `fix: keep Packages tab visible at minimum window width`.
Use the requested identity through `git -c user.name=... -c user.email=... commit`
if the checkout has no configured author. Push is already authorized.

Recent checkpoints, newest first:

| Commit | Purpose |
| --- | --- |
| `9cde97e` | Secured console across accounts, separate KVM profile, visible VM window |
| `0d63076` | Require actual `ryoku-shell` command in the reference recipe |
| `0360ee7` | Select accessible KVM for future boots with explicit TCG fallback |
| `4bf4907` | Supervisor heartbeats and runtime termination recovery notes |
| `c90b211` | Guest preservation recorder and helper protocol proposal |
| `55c382c` | Disposable VM controls and verified-image notes |
| `92ef594` | Static Fedora repository evidence and VM validation gates |
| `420aed8` | Recipe command roles, owner checks, package-major requirements |
| `37fa2b0` | Future optional agent skill documented over the shared core |
| `8673e86` | Retain ownership evidence for every discovered shell command |
| `d17c342` | RPM ownership checks for discovered paths |
| `b63f6c1` | Local installed-RPM evidence in plans and GUI |
| `d2dbcba` | Native read-only GUI checkpoint, earlier in history |

## 6. Quick commands for the next agent

Run these from the agent checkout:

```bash
cd /home/vick/Projects/desktopforge
git status --short --branch
git diff --check
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m pytest -q
PYTHONPATH=src python3 -m desktopforge detect --json
PYTHONPATH=src python3 -m desktopforge list
PYTHONPATH=src python3 -m desktopforge plan --compositor niri --shell noctalia --json
```

A blocked plan deliberately exits **1**. Successful detect/list exit 0; malformed
recipe/CLI errors may exit 2. Do not treat the expected blocked-plan exit as a test
failure or try to remove the blocker just to produce exit 0.

Prepared host GUI environment: `.venv-gui/`, ignored by Git, with PySide6-Essentials
and pytest. Base Python does not necessarily have Qt. Core imports do not require
Qt; do not add it as a mandatory core dependency.

Native GUI in the user's normal graphical terminal:

```bash
/home/ryoku/vick/Projects/desktopforge/scripts/desktopforge-gui
```

This opens DesktopForge itself. `desktopforge-session` is a separate experimental
compositor/shell trial, not the GUI application.

## 7. Architecture and implementation map

Read `README.md`, `PRD.md`, `ARCHITECTURE.md`, and `ROADMAP.md`, then use these files:

| Area | Files and behavior |
| --- | --- |
| Inventory | `detection.py`: os-release, configured DM, session files, command discovery, process/session hints, package/repository/preflight evidence; inventory schema 4 |
| Shell analysis | `session_analysis.py`: exact executable matching, ownership/cgroup evidence, conservative multi-shell correlation; no confirmed ownership from hints |
| Installed packages | `packages.py`: fixed local RPM queries, sanitized environment, timeouts, strict parsing, discovered-command owner records; no DNF transaction or refresh |
| Command requirements | `requirements.py`: typed basename, role, expected package, optional numeric major; pure evidence assessment |
| Repository declarations | `repositories.py`: fixed default DNF directories, bounded no-symlink file reads, IDs and declared flags only, no URL/credential collection |
| Static conflict inspection | `preflight.py`: path types/names, Niri hooks, DM configuration, session namespace conflicts, OSTree marker |
| Recipes | `recipes.py`, `data/recipes/*.yaml`: strict JSON subset of YAML 1.2, duplicate/unknown key rejection, exact distro/version/DM constraints; only unverified status accepted |
| Operations | `operations.py`: dependency checks, package proposals, session proposals; deterministic topological order and no execution |
| Planner | `planning.py`: deterministic blocked plan, preservation policy, collision-safe session ID preview, assessments and blockers; schema 2 |
| Compatibility adapter | `planner.py`: upstream/legacy interface wrapper; preserve its API and tests |
| Session draft | `session_layout.py`: incomplete isolated layout and launch contract; never an executable installation |
| GUI | `gui/__init__.py`, `gui/window.py`: lazy Qt loading, threaded detection, target selection, five plan tabs, explicit clipboard copy; installation always disabled |
| Experimental runtime | `lifecycle.py`, `launcher_runtime.py`, `transient_session.py`, `session_launcher.py`, `session_worker.py`: separate trial infrastructure |
| VM control | `scripts/desktopforge-vm`: prepared-lab start/status/ssh/screenshot/stop; default TCG and secured KVM profiles |
| Preservation evidence | `scripts/vm/record-baseline.py`: guest-only fixed-path hashes/ownership/modes and package/OS evidence |

### Important resolver and evidence rules

- `ID_LIKE` does not grant compatibility. Release and configured DM must match.
- Path discovery now retains **every** matching shell command; first-match fields
  remain for compatibility. Do not regress to only `ryoku` or only `noctalia-shell`.
- `/usr/bin/ryoku` belongs to `ryoku`, the management CLI. The reference service
  runs `/usr/bin/ryoku-shell daemon`, owned by `ryoku-shell`. Either package's
  presence alone cannot substitute for the required command/role.
- The Noctalia reference recipe requires package major **5**. Numeric major
  matching excludes RPM epoch/release; major 50 must not match 5. Non-numeric
  version evidence stays unknown. No Niri/Ryoku version range has been validated.
- Missing command evidence is unknown; an explicitly inspected absent command is
  missing. Ownership must uniquely match the expected package for a requirement
  to be observed. All-observed requirements still leave installation unverified.
- RPM vendor/source headers do not prove repository origin or key trust.
- Static repo declarations cover `/etc/yum.repos.d`, `/etc/distro.repos.d`, and
  `/usr/share/dnf5/repos.d`. They do not resolve defaults, overrides, custom
  reposdir, plugins, effective trust, package availability, or installed origin.
- A missing OSTree marker does not prove a supported mutable Fedora deployment.
- Fixture roots never silently query the host RPM database or borrow its home.
- Planning performs no live changes. No proposal, requirement result, or catalog
  match can enable GUI installation.

### Bundled recipes at this checkpoint

- `fedora45-niri-noctalia`: schema 2, revision 2, Fedora 45 with GDM/SDDM,
  unverified. Proposes Niri/Noctalia packages and dependency/session checks.
  Requirements: `niri` and `niri-session` owned by `niri`; `noctalia` owned by
  `noctalia`, package major 5. Session layout remains incomplete.
- `fedora45-niri-ryoku`: schema 2, revision 2, Fedora 45/SDDM reference only,
  unverified, **no installation operations**. Requirements: `niri`, `niri-session`,
  and `ryoku-shell`. Existing bootstrap/stop hooks still need review.

## 8. Physical Fedora multi-shell reference

Historical read-only observations (recheck if needed):

- Fedora Linux 45 (COSMIC), configured SDDM, Niri 26.04.
- Graphical account `ryoku`; services `niri.service`, `ryoku-shell.service`,
  `ryoku-session.target`.
- Registered sessions: COSMIC, Niri (DMS), Niri (Noctalia), Niri (Ryoku).
- Observed RPM versions: Niri `0:26.04-2.fc45`, Noctalia `0:5.4.1-1.fc45`,
  Ryoku Shell `1:1.0.9-1.fc45`, DMS `2.1.2-1.fc45`.
- `ryoku-shell.service` includes startup/stop hooks and depends on the Ryoku
  session target. Existing global Niri drop-ins bootstrap Ryoku.
- Agent-side active-shell evidence was unknown without the graphical account's
  environment/process evidence. Do not label this a broken running Ryoku session.

See `docs/REFERENCE_FEDORA45_MULTISHELL.md`, session preflight docs, and the user's
local `/home/vick/RYOKU-INSTALL-NOTES.md`. The latter is private reference material;
do not copy its full contents into Git. Inspect service files as text only; do not
execute them. Check file type before reading an executable as text: Ryoku commands
are compiled ELF binaries, not shell wrappers.

## 9. Disposable VM lab: verified state and exact controls

### Use the KVM profile

The normal `ryoku` host terminal has KVM access. A one-time launch from that
terminal provides a visible QEMU window plus agent-controlled SSH and console.
The following command has already worked for the user:

```bash
cd /home/ryoku/vick/Projects/desktopforge
./scripts/desktopforge-vm --profile kvm --accelerator kvm --show start
```

Leave the launch terminal and VM window open. The script is already in the shared
checkout; no additional clone or pull is needed merely to launch it. If it reports
an error, inspect `run-kvm/qemu.log` before changing permissions or installing
host packages.

At handoff preparation, ports 22220, 22221, and 22222 were all closed/unreachable.
The accelerated control helper returned connection refused. Do not assume the
previously shown GUI is still live.

From the agent checkout after the user starts it:

```bash
./scripts/desktopforge-vm --profile kvm status
./scripts/desktopforge-vm --profile kvm ssh 'cat /etc/fedora-release; id; sudo -n true'
./scripts/desktopforge-vm --profile kvm screenshot
```

KVM profile specifics:

- Root state: `.desktopforge-vm/`, Git-ignored and private.
- Working disk: `run-kvm/guest.qcow2`, virtual size 16 GiB; file was about 6.5 GiB
  at handoff inspection. Do not overwrite it with the original cloud image.
- Seed: `seed-kvm/`, NoCloud via a temporary loopback HTTP listener and SMBIOS.
- Guest hostname: `desktopforge-fedora45`; account: `dfvm` (UID 1000).
- Guest administrator access: `sudo -n` inside SSH.
- SSH: loopback port 22221; dedicated key in `.desktopforge-vm/keys/`.
- Console: loopback port 22222 with mutual TLS; private certificates under
  `run-kvm/tls/`. Server hostname validation and client authentication are enabled.
- QEMU: two vCPUs, 4 GiB RAM, virtio VGA, GTK window with host GL off if `--show`.
- No host home/filesystem or SSH agent is shared into the guest. Source was
  explicitly transferred using `git archive` plus the two pending GUI files.

Do not paste keys, certificates' private keys, or passwords into responses or Git.
The guest GUI password is stored privately in `.desktopforge-vm/keys/gui-password`;
read it only when needed for guest automation and never print it. No user password
was requested or copied from the physical laptop. Do not casually regenerate
these credentials; a running host-launched guest expects the matching TLS material.

### What actually succeeded in the accelerated guest

- Verified Fedora Cloud Base Generic 45-1.4 x86_64 image booted; QMP `query-kvm`
  returned both enabled and present.
- Image checksum was verified against Fedora's signed CHECKSUM and published key.
  Image verification receipt is in `run-kvm/image-verification.json`.
- Root filesystem expanded to 16 GiB; cloud-init finished.
- Installed `@workstation-product-environment`, `python3-pyside6`, and
  `python3-pytest` through Fedora DNF **inside the guest**.
- DNF transaction completed successfully. Guest-only systemd jobs were
  `desktopforge-lab-baseline.service` and `desktopforge-lab-graphical-ready.service`.
- Enabled GDM and graphical.target as guest baseline setup; authenticated the
  dedicated user through GDM and reached a GNOME Wayland desktop.
- Observed packages: GNOME Shell `51.1-1.fc45`, GDM `51.1.1-1.fc45`,
  native PySide6 `6.11.2-3.fc45`; SELinux was **Enforcing**.
- DesktopForge ran through a guest user unit named `desktopforge-preview.service`.
- It detected configured GDM, GNOME Wayland, GNOME and GNOME Classic session
  registrations, and no Niri/Noctalia installation. Its plan exited 1 as expected.
- Final guest suite after tab fix: **318 passed, 1 skipped** in about 6 seconds.
- The GUI showed the Packages tab after the padding fix; a regression also checks
  the 880px minimum width. Keep the screenshot evidence and tests separate from
  any claim of installer validation.

This is a cloud-derived VM provisioned with the Workstation environment. The
inventory and welcome tour still displayed Cloud Edition. Do not relabel the base
as an official Workstation ISO or claim a broader VM matrix was completed.

### Guest files and evidence

Inside the guest:

```text
/home/dfvm/desktopforge/                 source archive plus the pending GUI fix
/home/dfvm/desktopforge-tests.log        final pytest output and skip reason
/home/dfvm/baseline-detect.json          read-only inventory
/home/dfvm/baseline-plan.json            blocked Niri/Noctalia plan
/home/dfvm/baseline-preservation.json    fixed-path preservation record
```

The preservation record was made before all later guest display/idle preferences
were adjusted. Recapture a final baseline before helper or install experiments.
No clean rollback snapshot/cold backup has yet been confirmed. The verified
pristine download is not a snapshot of the configured GNOME baseline.

Host-side ignored artifacts under `run-kvm/` include:

- `gdm.png`: actual graphical login screen.
- `desktopforge-fixed.png`: clean maximized DesktopForge view with all five tabs.
- `desktopforge-gnome.png`, `desktopforge-maximized.png`: earlier GUI evidence.
- `desktopforge-first.png`: first-login tour over the application.
- `desktopforge-tabs-fixed.png`: blank/idle display capture; not a useful GUI proof.
- `desktopforge-packages.png`: an overview-mode capture after an input attempt;
  do not describe it as a verified Packages tab click.
- `bootstrap-evidence.json`: captured before GUI setup; its false graphical-baseline
  fields are historical, not a current assessment. Later screenshots/guest logs
  establish the GUI milestone.
- `serial.log`, `qemu.log`, image receipt, and private TLS state.

Do not commit `.desktopforge-vm/`, screenshots, guest disks, logs, or credentials
by accident. Existing ignore rules cover that entire directory.

### Guest presentation and automation details

- The VM initially used a narrow 736x850 display. We temporarily set Virtual-1 to
  1280x960 through the guest's `gdctl` (without `--persistent`).
- The GUI was maximized using guest keyboard input. Screenshot capture works
  across the different account path prefixes because QEMU's working directory is
  fixed and the TLS profile uses a relative screenshot destination.
- GNOME's default idle lock blanked the display during testing. Guest-only settings
  were then changed: idle-delay 0, screen locking false, AC/battery idle action
  `nothing`, automatic software download and download notification false.
  `/system-update` was absent; no offline update was scheduled at that check.
- These guest preferences must not be applied to the physical Ryoku account.
- Absolute mouse automation was not fully verified. `query-mice` listed active
  absolute `vmmouse`, but a click attempt ended in GNOME overview rather than the
  intended tab. Inspect each fresh screenshot and avoid blind coordinate loops.
- Guest keyboard login using the private test password succeeded. `loginctl`
  session IDs such as 29 were runtime-specific; re-enumerate instead of hardcoding.
- For the app, prefix guest commands with `XDG_RUNTIME_DIR=/run/user/1000` and
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` as necessary. Do not import
  the physical host user's session environment.

To reopen the GUI in an existing guest GNOME session, inspect its user unit first:

```bash
./scripts/desktopforge-vm --profile kvm ssh 'export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus; systemctl --user status desktopforge-preview --no-pager'
```

If the unit is no longer loaded, launch it with:

```bash
./scripts/desktopforge-vm --profile kvm ssh 'export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus; systemd-run --user --collect --unit=desktopforge-preview /home/dfvm/desktopforge/scripts/desktopforge-gui'
```

### Old emulated profile: do not confuse it with the successful baseline

The default profile uses `run/guest.qcow2`, SSH 22220 and an owned Unix QMP socket.
Its tool-managed processes were terminated twice (exit 143). A foreground terminal
with heartbeats later remained up, but package verification/installation was far
too slow under TCG. Its GNOME transaction was incomplete when it was paused with
QMP; memory and transaction state were preserved at that moment, not snapshotted.
Current process state is not guaranteed after interruptions. Do not resume/reuse
that disk as a clean baseline, and never open either live disk from two QEMU writers.

### Important remaining VM-control limitation

The launcher still passes `-no-reboot`. A guest reboot can therefore terminate
QEMU and require another host-terminal launch. Before reboot/failure testing,
review and fix this behavior. Investigate supported QMP `set-action` behavior or
adjust future launch flags; do not assume the running VM already has restart
support. No reliable snapshot/restore or automatic restart mechanism has yet been
implemented or tested. Do not copy live QCOW2 files as if they were clean backups.

## 10. Recommended next work, in order

### A. Recover access and finish the current checkpoint

1. Verify the latest session's actual permissions: project file writes, Git metadata
   writes, network reachability, and the VM endpoints are separate capabilities.
2. Preserve and review the two pending GUI files and this document. Restore normal
   authorized Git writes, rerun checks if edits/environment warrant it, then commit
   and push. Do not reset the checkout or force-push.
3. If the VM is still stopped, give the user the exact normal-host KVM launch
   command above. This is the known necessary handoff because the tool cannot
   open the KVM device. Once running, confirm secured console, SSH and guest sudo.

### B. Make the accelerated lab repeatable before mutating tests

1. Confirm GNOME/GDM and SELinux state after reboot. Reopen the GUI and show the user
   the milestone. Check source revision: the guest is not a Git clone and does not
   update itself when host commits change.
2. Refresh inventory, plan and preservation records. Copy needed evidence into the
   ignored host lab area. Preserve the original GNOME login and recovery SSH.
3. Establish a verified clean snapshot/backup and a tested restore path. Fix the
   `-no-reboot` behavior before planning reboot cases that would need repeated
   user intervention. Track disk/RAM usage; multiple images can fill the laptop.
4. Keep current runtime evidence accurate in VM_LAB/VM_VALIDATION docs; existing
   committed notes predate the successful graphical baseline and contain older
   preparation-only wording.

### C. Implement the helper boundary first, inside the VM

Read `docs/HELPER_PROTOCOL.md` and `docs/VM_VALIDATION.md`. Proposed next experiment:
a **lab-only, non-mutating authorization probe**, not production installation.

- Implement and test a small system-bus service which obtains the unique sender
  and UID from the bus and checks a dedicated Polkit action. Never accept a
  caller-claimed UID/PID/HOME, arbitrary commands, recipe paths or target paths.
- Exercise identity, denial, cancellation and graphical authorization in the VM.
  The guest's passwordless SSH sudo is not evidence that GUI Polkit works.
- Install only reviewed/root-owned lab service code and policy in the disposable
  guest. Never run a privileged service directly from a user-writable checkout.
- Keep this lab path separate from production apply. The probe has been proposed
  but **has not been implemented or installed**; no files for it exist yet.
- Then implement bounded versioned requests, plan/caller binding, expiry/replay
  rejection, fresh evidence checks, journaling and fixed filesystem operations.
  Add meaningful attack/failure regressions before exposing writes.

Report the concrete design and findings before substantial architecture changes.
The user authorized continuing development, but do not treat a design proposal as
a security review or a passing test result.

### D. Validate one concrete installation before enabling the GUI action

Use Fedora 45 + Niri + Noctalia first. Resolve effective repositories/key trust,
package versions/dependencies, isolated configuration, session registration,
launch lifetime, failure cleanup and environment leakage. Existing reference
Niri/Ryoku hooks make the physical laptop unsuitable as the first mutating target.

Test the concrete recipe and helper in a disposable GNOME/GDM baseline with
pre/post comparisons, logout, failed startup, repeat attempts, reboot and recovery.
Repeat under SDDM before claiming SDDM support. Real GPU validation remains
separate from virtio/software rendering and KVM CPU acceleration.

Keep the GUI installation action disabled until the helper and concrete recipe
meet those gates. Do not turn `unverified` into `validated` by adding a boolean.
Validation provenance and trusted recipe policy still need a real design.

## 11. Existing experimental session launcher: avoid repeating the detour

There is a runnable `desktopforge-session` trial using a unique transient user
unit, private D-Bus/config directories, explicit environment allowlist, owned
cgroup checks and an isolated Niri config. It launches Niri directly without the
shared `niri.service` or `niri-session` path. Nested mode uses **Alt**, standalone
uses Super; the Noctalia app menu is opened automatically after readiness.

The user previously saw a nested desktop/app launcher and understandably expected
DesktopForge itself. That confusion was fixed by building `desktopforge-gui`.
Do not send the user back to the nested trial when they want to see this app.
The trial is not an installed login session or proof of production lifecycle safety.

Relevant implementation/docs: `launcher_runtime.py`, `transient_session.py`,
`session_launcher.py`, `session_worker.py`, `docs/TRY_LAUNCHER.md`,
`docs/LAUNCHER_RUNTIME.md`, `docs/LAUNCHER_LIFECYCLE.md`.

## 12. Optional agent skill decision

The user considered replacing the app with a Codex skill. Agreed direction:
continue the GUI/core and phase in an optional skill over the same interfaces.
Earlier skill uses can include upstream research, diagnostics, and drafting recipes
and tests. Agent suggestions do not certify compatibility or bypass review,
authorization, helper limits or recovery requirements. Codex must not be required
to use DesktopForge. This is already documented in PRD/ARCHITECTURE/ROADMAP at
`37fa2b0`; it is outside the current milestone's installation exit criteria.

## 13. Documentation reading order

1. This handoff, current Git status/diff, README, PRD, ARCHITECTURE, ROADMAP.
2. `docs/GUI.md` and `docs/RECIPES.md` for current application and schema behavior.
3. `docs/VM_LAB.md`, `docs/VM_VALIDATION.md`, `docs/HELPER_PROTOCOL.md` before VM
   helper work. Remember their older preparation-only statements need updating
   against the verified results recorded above.
4. `docs/SESSION_PREFLIGHT.md`, `docs/FEDORA45_NIRI_NOCTALIA_RESEARCH.md`,
   `docs/REFERENCE_FEDORA45_MULTISHELL.md` for integration risks and reference data.
5. Launcher lifecycle/runtime/trial docs only when working on that separate path.

The most useful immediate deliverable is to preserve/commit the tested GUI fix,
restore the accelerated lab, and begin its authorization-boundary experiments.
There is already a functioning GUI and a working VM baseline; build from those
instead of recreating the earlier setup work.
