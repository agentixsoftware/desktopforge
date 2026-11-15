# DesktopForge agent handoff

Updated at the end of the 2026-11-15 session (America/Los_Angeles; guest logs
use UTC). It replaces all earlier handoff text. Recheck the runtime state before
acting; section 9 has a ready-made start prompt for the next agent.

## 1. Where things stand (one paragraph)

The reference session, **Fedora 45 + Niri + Noctalia**, can be installed,
removed and repaired by a privileged D-Bus helper, from both the CLI client and
the GUI. It works on GDM and SDDM in disposable KVM VMs, and preserves the
existing desktop. The owner **accepted** `docs/PRODUCTION_PROPOSAL.md` (section
9 records the decisions). Its steps **1, 2, 5 and 6 are done**:
- one daemon with `lab` and `production` profiles
- RPM packaging
- validation-evidence tooling
- GUI production gates

Production offers **no recipes yet**: approval needs current evidence, real-GPU
runs and the owner's signed sign-off. The reference recipe's evidence is
honestly **not-validated** today, because all 19 VM cases are *stale* (the code
changed after they ran) and the two real-hardware cases are missing.

## 2. Resume checklist

```bash
cd /home/vick/Projects/desktopforge
git status --short --branch         # expect clean; main == origin/main
git log --oneline -3                # latest: this handoff commit, then 970f393
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m pytest -q   # expect 743 passed
./scripts/validation-report validation/fedora45-niri-noctalia-lab/r2.json   # expect: not-validated, 19 stale
./scripts/desktopforge-vm --profile kvm backups ; ./scripts/desktopforge-vm --profile sddm backups
./scripts/desktopforge-vm --profile kvm status ; ./scripts/desktopforge-vm --profile sddm status
ls -l /dev/kvm                      # agent session could use KVM directly
```

## 3. The two disposable VMs

| Profile | Purpose | State at pause | Ports |
| --- | --- | --- | --- |
| `kvm` | Fedora 45 + GNOME + **GDM** | Was running in the user's window (`--gl --show`), logged into GNOME. Niri + Noctalia installed through the GUI (install `4902a2f85f764242b32775dc0c02bb49`, intact, then repaired and verified). Source `f74ca09+profiles`; lab helper installed; no RPMs | SSH 22221, TLS console 22222 |
| `sddm` | Clone of the GNOME baseline with **SDDM** (sddm-wayland-generic) instead of GDM | Shut down. Dev RPMs (`desktopforge`, `desktopforge-helper` 0.1.0-0.1.dev from `d34982d`) installed alongside the lab helper; Niri not installed | SSH 22231, TLS console 22232 |

Backups (btrfs reflink clones with SHA-256 manifests; `backup`/`restore` refuse
while QEMU runs):

| Profile | Backup | Contents |
| --- | --- | --- |
| kvm | `gnome-baseline-2026-11-14` | Clean GNOME/GDM baseline, before any helper |
| kvm | `pre-niri-2026-11-14` | Lab helper; pending offline update kept; no Niri. **Best start for a full matrix run on GDM** |
| kvm | `niri-installed-2026-11-15` | Niri + Noctalia installed (older code) |
| kvm | `end-of-day-2026-11-15` | Older state with Niri installed |
| sddm | `sddm-pre-niri-2026-11-15` | SDDM baseline + lab helper; pending offline update kept. **Best start for a full matrix run on SDDM** |
| sddm | `sddm-rpm-dev-2026-11-15` | Current SDDM state with dev RPMs |

Disk: about 14 GB free on `/home`.

### Starting and driving the VMs

- **User-visible (preferred for demos):** ask the user to run this in their
  **`ryoku`** terminal on the laptop:

  ```bash
  cd /home/ryoku/vick/Projects/desktopforge
  ./scripts/desktopforge-vm --profile kvm --accelerator kvm --gl --show start
  ```

  Leave out `--gl` for software-rendering tests.
- **Headless by the agent** (account `vick`; `/dev/kvm` was accessible): run with
  `run_in_background`:
  `./scripts/desktopforge-vm --profile sddm --accelerator kvm --gl start`.
  Only one QEMU per disk.
- **Screens:**
  - Without `--gl`: `./scripts/desktopforge-vm --profile P screenshot` (PPM).
  - Headless `--gl`: `lab/tools/vnc-screenshot.py .desktopforge-vm/run-<profile>/vnc.sock out.png`.
  - `--gl --show` (the user's window): only from inside Niri
    (`niri msg action screenshot-screen`); GNOME and GDM cannot be captured.
- **Typing:** `DESKTOPFORGE_VM_PROFILE=<profile> lab/tools/qmp-sendkeys.py --secret .desktopforge-vm/keys/gui-password` (never echoes).
- **GUI buttons:** launch the GUI with `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`, then
  press buttons by name with `lab/tools/atspi-press.py` inside the guest.
- **Logins without sight:**
  - GDM: preselect via AccountsService
    `busctl call org.freedesktop.Accounts /org/freedesktop/Accounts/User1000 org.freedesktop.Accounts.User SetSession s <id>`, then restart gdm.
  - SDDM: edit `[Last] Session=` in `/var/lib/sddm/state.conf` and restart sddm.
  - Log every such lab-admin action in the guest's `~/evidence/lab-admin.log`.
- **Polkit dialogs:** type the password only after the helper's journal shows
  `: authorizing` for the current run (`journalctl -u desktopforge-lab-helper --since @<t>`).
- **Source into a guest:** `git archive --format=tar HEAD | ./scripts/desktopforge-vm --profile P ssh 'rm -rf ~/desktopforge && mkdir ~/desktopforge && tar -x -C ~/desktopforge'`
  (include working-tree changes with a `tar` of the tree if uncommitted), then
  `sudo -n ~/desktopforge/scripts/vm/install-lab helper`.
- **Every fresh install from a baseline is first blocked** by a pending offline
  update (GNOME Software). That's correct behavior; discard it with
  `sudo dnf5 offline clean` as a logged lab-admin step.

## 4. Code map

| Area | Where | Docs |
| --- | --- | --- |
| Read-only inventory (schema 6), planner, CLI | `detection.py`, `planning.py`, `cli.py`, `install_records.py`, `rendering.py` | README, `docs/INSTALL_RECORDS.md` |
| GUI (read-only, VM lab mode, production mode) | `gui/window.py`, `labclient.py` | `docs/GUI.md` |
| Helper core (stdlib only) | `src/desktopforge/helper/`: `fsops`, `evidence`, `grants`, `journal`, `executor`, `pkgtx`, `sessions`, `records`, `removal`, `repair`, `gpuprobe` | `docs/LAB_HELPER.md`, `REMOVAL.md`, `REPAIR.md` |
| Daemon (lab and production profiles) | `src/desktopforge/helperd/daemon.py`; entry points `lab/helper/desktopforge-lab-helper` and `packaging/desktopforge-helper` | `docs/PACKAGING.md` |
| Session launcher | `src/desktopforge/loginsession.py` (installed as `desktopforge-session`) | `docs/LAB_HELPER.md`, `SDDM_VM.md` |
| RPM packaging | `packaging/desktopforge.spec` and service, policy and bus files | `docs/PACKAGING.md` |
| Validation evidence | `src/desktopforge/validation.py`, `scripts/validation-report`, `validation/` | `docs/VALIDATION_EVIDENCE.md` |
| VM control, guest installer, agent tools | `scripts/desktopforge-vm`, `scripts/vm/install-lab`, `lab/tools/` | `docs/VM_LAB.md` |

## 5. Decisions already made by the owner

- **Production proposal accepted** (`docs/PRODUCTION_PROPOSAL.md` section 9):
  - RPMs via a user-enabled COPR.
  - Approval = current evidence + review + the owner's signed sign-off; only
    approved recipes are bundled.
  - First scope: Fedora 45, GDM or SDDM, Niri + Noctalia, Intel or AMD.
  - **No real-hardware test machine yet.**
  - The **reference laptop stays read-only for the whole first release.**
- **Option A:** never reset the AccountsService or SDDM remembered session;
  report failed logins in DesktopForge instead.
- **Niri needs hardware rendering:** plans are blocked unless the GPU probe
  reports hardware.
- **2a:** GUI lab mode in VMs. Production mode only with the RPM helper and
  an approved recipe.

## 6. Next work, in recommended order

1. **Scripted lab-matrix runner** (the agreed next step, not started). Goal:
   re-run the 19 cases in `src/desktopforge/validation.py` `LAB_CASES` on current
   code and record them, with commits, in
   `validation/fedora45-niri-noctalia-lab/r2.json`, so `scripts/validation-report`
   reaches `lab-validated`. Suggested shape:
   - A host-side script, e.g. `scripts/vm/run-matrix`, that:
     - restores the `pre-niri` (GDM) or `sddm-pre-niri` (SDDM) backup
     - boots headless with `--gl`
     - deploys `git archive HEAD` and installs the lab helper
     - discards the pending offline update
     - runs each case through the lab helper, with assertions on outcomes,
       records, RPM diffs, preservation records and launcher journal lines
     - records results.
   - **Authorization without typing:** a root caller is authorized by Polkit
     implicitly (`sudo` lab client), but GUI login, logout and Polkit-dialog
     cases need keystrokes via `qmp-sendkeys`.
   - Software-rendering cases need a boot **without** `--gl`.
   - Commit only when the tree is clean, so each case's commit is exact.
2. **Step 3: SELinux.** The helper runs `unconfined_service_t`. Write a policy
   module (permissive in the VM first).
3. **Step 4: dnf5daemon.** Replace DNF5 CLI parsing with `org.rpm.dnf.v0`
   (present on Fedora Workstation); keep the CLI adapter as fallback.
4. **Step 7: real hardware.** Blocked until the owner names a test machine.
   Needed for the `approvable` tier.
5. Smaller follow-ups:
   - mock/COPR build and `rpmlint`
   - warn or refuse when the helper RPM is removed while recorded
     installations exist
   - a GUI for removal details (kept files)
   - re-test SDDM with the Plasma greeter

## 7. Bugs found through VM runs (all fixed; keep their regression tests)

- btrfs stale directory listing through a long-lived handle.
- seccomp killed `rpm -q` (`fchown`), which led to a false "No changes were made".
- PID1 rejects `systemd-run --pipe` from a sandboxed caller.
- Environment leaks after logout.
- Portals left failed after logout.
- SDDM discards session stdout, so the launcher now logs via the journal socket.
- Desktop-entry `Name = X` parsing.
- Package updates were wrongly treated as damage.
- Duplicate missing-package messages.

## 8. Safety rules and user preferences

- **The physical laptop is read-only:**
  - no host packages and no host sudo
  - do not touch SDDM, Niri, Ryoku, session launchers, services, or user configuration
  - the graphical account is `ryoku` (UID 1001); the agent runs as `vick`
    (UID 1000); the checkout is shared at `/home/ryoku/vick/Projects/desktopforge`
- **The VMs are disposable:** guest administration is authorized. Log manual
  admin actions in the guest's `~/evidence/lab-admin.log`.
- **Never expose secrets:** no passwords, keys, disks or private logs in output
  or Git (`.desktopforge-vm/` is ignored).
- **Installation stays disabled** outside the VMs until a recipe is approved
  (evidence, review, sign-off).
- **Commits:** identity `Vick Reddy <agentixsoftware@gmail.com>` via
  `git -c user.name=... -c user.email=...`. Commits and pushes at logical stages
  are pre-authorized.
- **Working style:**
  - concise progress updates
  - real VM screenshots, never mockups
  - exact commands, naming which machine and account they run on
  - the owner approves each major step ("go ahead"), so propose before
    substantial or risky work
- **VM coordination:** announce before keystrokes or Polkit dialogs in a VM the
  user is watching. Never use `pgrep -f` with a pattern that matches its own
  command line.
- **Subagents:** not requested; don't use them proactively.

## 9. Start prompt for the next agent

```text
Take over DesktopForge development in /home/vick/Projects/desktopforge.

Read HANDOFF.md fully first, then docs/PRODUCTION_PROPOSAL.md (accepted
decisions), docs/VALIDATION_EVIDENCE.md and docs/VM_LAB.md. Run the resume
checklist in HANDOFF.md section 2 and report what you verified (git state,
tests, validation report, VM backups and status, KVM access).

The next agreed work item is the scripted lab-matrix runner (HANDOFF.md
section 6, item 1): re-run the 19 lab cases on current code in the disposable
KVM VMs (GDM profile "kvm", SDDM profile "sddm"), record results with exact
commits in validation/fedora45-niri-noctalia-lab/r2.json, and get
scripts/validation-report to "lab-validated". Propose the runner's design
briefly before building it, then proceed when I say go.

Safety: the physical laptop stays read-only (no host packages, no host sudo, no
changes to SDDM, Niri, Ryoku, services, launchers or user config). Guest
administration inside the disposable VMs is authorized; log manual admin
actions in the guest's ~/evidence/lab-admin.log. Never expose the VM password,
keys, disks or private logs. Installation stays disabled outside the VMs until a
recipe is approved with my signed sign-off.

You may commit and push at logical stages (identity: Vick Reddy
<agentixsoftware@gmail.com>). Give concise progress updates, show real VM
screenshots for interesting milestones, and when I must do something, give exact
commands and say which machine and account to run them in.
```
