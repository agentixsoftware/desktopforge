# DesktopForge agent handoff

Updated at the end of the 2026-11-15 session (America/Los_Angeles; guest logs use UTC).
This replaces all earlier handoff text. Recheck runtime state before acting.

## 1. Resume in five minutes

```bash
cd /home/vick/Projects/desktopforge
git status --short --branch          # expect: clean, main == origin/main
git log --oneline -1                 # end-of-day commit (see section 6)
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m pytest -q   # expect: all pass (609 at pause)
./scripts/desktopforge-vm --profile kvm backups                # four verified backups
```

Guest state at the latest pause: Niri + Noctalia **installed** through the GUI by install
`4902a2f85f764242b32775dc0c02bb49` (7 packages recorded as installed; intact).
The history holds three earlier installs, each removed, with removal records.
The edited config from the kept-file test is at `/root/kept/` in the guest. Reboot,
failed-install/retry and dependency re-verification were run (`docs/LAB_HELPER.md`,
`docs/INSTALL_RECORDS.md`). The `end-of-day-2026-11-15` backup still has Niri installed.

**Removal is built and VM-verified** (2026-11-15 evening; see `docs/REMOVAL.md`).
Pick the next item from section 5 with the user.

## 2. Starting the VM

The user prefers to watch the VM. Ask them to run it in their **`ryoku`** host
terminal; the agent session (account `vick`) then drives it over SSH and QMP:

```bash
# On the laptop, in a terminal logged in as ryoku
cd /home/ryoku/vick/Projects/desktopforge
./scripts/desktopforge-vm --profile kvm --accelerator kvm --gl --show start   # with 3D (needed for Niri)
./scripts/desktopforge-vm --profile kvm --accelerator kvm --show start        # without 3D (software rendering)
```

- **`--gl` (virgl) is required for Niri to display.** With `--gl`, QMP
  `screendump` fails ("no surface"). Screenshot inside Niri with
  `niri msg action screenshot-screen`. GNOME and GDM cannot be screenshotted.
- **Without `--gl`, screenshots work,** but Niri cannot render. Use this mode
  for software-rendering and fallback tests.
- **Headless by the agent:** `/dev/kvm` was accessible from the agent session.
  Start with `run_in_background`:
  `./scripts/desktopforge-vm --profile kvm --accelerator kvm start`
  (add `--gl` for egl-headless). The user cannot see that VM, and only one
  QEMU may use the disk at a time.

Control (agent checkout): `status`, `ssh '<cmd>'`, `screenshot`, `stop`,
`backup NAME`, `restore NAME`, `backups`, all with `--profile kvm`.
Backup and restore refuse while QEMU is running. Stop gracefully, then wait
until `status` reports "Connection refused".

Agent VM tools are kept in `lab/tools/`: `qmp-sendkeys.py` for keystrokes, with the
password read from file and never echoed, and `atspi-press.py` for pressing GUI
buttons by accessible name inside the guest. Other small scratchpad helpers
were easy to recreate:
- QMP send-key typing from the private password file, never echoed
- screenshot to PNG via PIL
- `niri msg` screenshot
- running the lab client in the user's graphical session via `systemd-run --user`

## 3. Guest state at pause (`end-of-day-2026-11-15`)

- Fedora 45 Cloud Base plus Workstation environment; GDM; SELinux enforcing;
  account `dfvm` with passwordless guest sudo. The guest GUI password is in
  `.desktopforge-vm/keys/gui-password`: never print it.
- Source in the guest is a transferred archive at `~/desktopforge`, not a Git
  clone (`SOURCE_REVISION` says which). Re-transfer with
  `tar -c src tests scripts lab | ./scripts/desktopforge-vm --profile kvm ssh 'tar -x -C ~/desktopforge'`.
  After changing any root-installed lab file, reinstall with
  `sudo -n ~/desktopforge/scripts/vm/install-lab helper`.
- Installed lab components (root-owned): authorization probe, lab helper,
  helper core, `desktopforge-session` launcher.
- **Niri + Noctalia is installed** (packages niri 26.04-2, noctalia 5.5.0-3 and
  5 dependencies). The session "Niri + Noctalia (DesktopForge)" (recipe
  revision 2) uses the launcher, and its install record is
  `/var/lib/desktopforge/installs/8dbcd10ab09745aaa5e86ac19611de90.json`. That
  record lists niri/noctalia as *reused*: they were installed by an earlier
  pre-records run (documented).
- Also present: "DesktopForge Lab (GNOME)" lab session, Fedora's own "Niri"
  session (from the niri package), marker files from the synthetic tests,
  `~/.local/state/desktopforge/launches/niri-noctalia.json` (last result
  `no-display` from the non-virgl fallback test), and Noctalia per-user data.
- AccountsService remembered session: `gnome`.
- Every manual admin action in the guest is logged in `~/evidence/lab-admin.log`.
  A copy of the guest evidence, journals and records is in the ignored host folder
  `.desktopforge-vm/evidence/2026-11-15-session/`.

Backups (`.desktopforge-vm/backups-kvm/`, btrfs reflinks, SHA-256 manifests):

| Name | State |
| --- | --- |
| `gnome-baseline-2026-11-14` | Clean GNOME/GDM baseline, before any helper |
| `pre-niri-2026-11-14` | Lab helper and GNOME lab session; pending offline update kept; no Niri |
| `niri-installed-2026-11-15` | Niri + Noctalia installed with an install record |
| `end-of-day-2026-11-15` | Current; same plus the launch-state and option-A work |

## 4. What exists now (code map)

| Area | Where | Docs |
| --- | --- | --- |
| Read-only inventory (schema 6), planner, CLI, GUI | `detection.py`, `planning.py`, `cli.py`, `gui/` | README, `docs/GUI.md` |
| Helper core (stdlib-only, installable root-owned) | `src/desktopforge/helper/`: `fsops`, `evidence`, `grants`, `journal`, `executor`, `pkgtx`, `sessions`, `records`, `gpuprobe` | `docs/LAB_HELPER.md` |
| Lab Polkit probe | `lab/authprobe/` | `docs/LAB_AUTHPROBE.md` |
| Lab helper (D-Bus `org.desktopforge.LabHelper1`, Preview/Apply) | `lab/helper/` | `docs/LAB_HELPER.md` |
| Session launcher | `src/desktopforge/loginsession.py` → `desktopforge-session` | `docs/LAB_HELPER.md` |
| Install records, launch outcomes, rendering preflight | `helper/records.py`, `install_records.py`, `rendering.py` | `docs/INSTALL_RECORDS.md` |
| VM control and guest installer | `scripts/desktopforge-vm`, `scripts/vm/install-lab` | `docs/VM_LAB.md` |

Verified in the guest, with details in the docs:
- **Authorization:** Polkit deny, dismiss, approve, no retention, disconnect.
- **Request layer:** grants (replay, tamper, foreign connection, expiry, drift).
- **Package installs:** DNF5 install with signer check; the pending offline update blocked.
- **Session entries:** registration, plus GDM listing and login.
- **Niri + Noctalia session:** the launcher with graphical-session.target and
  portals, and cleanup after logout.
- **Install records:** intact, modified and incomplete states; the GUI shows
  "Installed by DesktopForge".
- **Rendering:** the preflight reports hardware with virgl and software-only
  with llvmpipe; without a display the session returns to GDM.
- **Failed-login warning (option A).**

Bugs found and fixed through VM runs:
- btrfs directory-handle listing returned stale entries
- the seccomp filter killed `rpm -q`, which led to a false "No changes were made"
- PID1 rejected `systemd-run --pipe` from inside the sandbox
- environment leaks after logout
- portal units left failed after logout

## 5. Next work

1. **Removal:** done (`docs/REMOVAL.md`). Follow-ups: GUI presentation,
   later-installed dependents in the guest, reboot between install and removal.
2. **Remaining Milestone 2 work:**
   - Done: reboot, failed install with retry (network outage), dependency re-verification.
   - GUI lab mode (decision 2a) is done and VM-verified: install and remove from the window via the
     lab helper (`docs/GUI.md`). Production installation stays disabled.
   - DNF network limits are done (`retries=2`, `timeout=20`), and helper `Progress` signals are shown in the GUI and CLI.
   - SDDM baseline VM is done (`docs/SDDM_VM.md`; profile `sddm`, backup `sddm-pre-niri-2026-11-15`).
   - Repair is done (`docs/REPAIR.md`): GUI and helper, VM-verified.
   - Next: production-path decisions with the user (privileged packaging, approved-recipe policy, enabling outside the lab).
3. **Product decisions already made:**
   - **Option A:** never reset the AccountsService remembered session; report
     failed logins instead.
   - **No software rendering for Niri:** block Niri plans unless the GPU probe
     reports hardware.
   - **Lab first:** lab-only Polkit actions and recipes; production installation
     stays disabled.

## 6. Safety rules and user preferences (unchanged)

- **Physical laptop is read-only:** no host packages, no host sudo. Do not touch
  SDDM, Niri, Ryoku, session launchers, services, or user configuration. The
  graphical account is `ryoku` (UID 1001); the agent runs as `vick` (UID 1000).
  The checkout is shared at `/home/ryoku/vick/Projects/desktopforge`.
- **The VM is disposable:** guest administration is authorized. Log manual admin
  actions in the guest's `~/evidence/lab-admin.log`.
- **Never expose secrets:** no passwords, keys, disks or private logs in output
  or Git. `.desktopforge-vm/` is ignored.
- **Installation stays disabled:** keep the GUI install action off until the
  helper and a concrete recipe pass the validation gates in `docs/VM_VALIDATION.md`.
- **Commits:** identity `Vick Reddy <agentixsoftware@gmail.com>`, set via
  `git -c user.name=... -c user.email=...`. Commits and pushes at logical stages
  are pre-authorized.
- **Working style:** concise progress updates. Show interesting VM milestones
  with real screenshots, not mockups. Give exact commands and say which machine
  and account they run on.
- **VM coordination:** announce before sending keystrokes or Polkit dialogs, and
  ask the user to keep hands off. Type the password only after confirming focus
  (a dialog is shown, or the helper's journal says "authorizing"). Never use
  `pgrep -f` with a pattern that matches its own command line.
- **Subagents:** the user hasn't asked for any; don't use them proactively.
