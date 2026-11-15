# Proposal: taking DesktopForge from the VM lab to real machines

Status: **accepted** (2026-11-15). The owner accepted the recommendations for
all decisions in section 9 (recorded there). Installation stays disabled
outside the disposable VMs until the work they imply has passed review and a
recipe is approved.

## 1. Summary

The reference session (Fedora 45 + Niri + Noctalia) works end to end in the
lab: install, remove and repair from the CLI client and the GUI. It has been
tested on GDM and SDDM, through reboots, failed installs, broken dependencies
and edited files, with install records, rendering preflight and a session
launcher that cleans up after itself. All of it runs through a **lab** helper
that exists only inside the VMs.

Three decisions stand between that and a real machine:

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | How the privileged part is delivered | A signed native **RPM** (`desktopforge` + `desktopforge-helper`), first from a COPR the user adds deliberately; never downloaded or bootstrapped by the app |
| 2 | What makes a recipe "approved" | Bundled in that RPM only. It must have passed the lab test matrix, with machine-readable evidence committed, plus your sign-off. No recipes downloaded at runtime in v0.1 |
| 3 | Where the GUI may install | Only where every gate passes: production helper present, an approved recipe for the exact Fedora release and display manager, hardware rendering, clean preflight. Everywhere else stays read-only, as today |

Recommended sequence: production helper and packaging → real-hardware
validation on a spare machine or test account → a small opt-in pre-release.
Your laptop stays read-only throughout unless you explicitly decide otherwise.

## 2. What the lab already proves, and what it does not

**Proven in disposable VMs:**
- Polkit authorization bound to the bus caller.
- One-time grants bound to the plan and evidence.
- A journal written before each step.
- Handle-based file writes.
- Fedora-signed package installs with exact-set verification.
- Honest failure reporting.
- Install, removal and repair records.
- GDM and SDDM integration, plus the launcher's environment and portal handling.
- The rendering preflight.
- Preservation of the existing desktop.

**Not proven yet:**
- Real GPUs (only virgl and llvmpipe).
- Any machine with existing user customization beyond our test edits.
- Concurrent users.
- Laptops with hybrid graphics.
- The physical reference laptop's Ryoku/SDDM setup.
- An independent security review of the helper.
- Behavior across a Fedora release upgrade.

## 3. Decision 1 — delivering the privileged helper

### Recommended: native RPM packages

| Package | Contents |
| --- | --- |
| `desktopforge` | The unprivileged GUI and CLI (what `scripts/desktopforge-gui` runs today) |
| `desktopforge-helper` | The system D-Bus service, its bus policy and Polkit actions, the session launcher (`/usr/libexec/desktopforge/desktopforge-session`), and the **approved** recipes and templates (`/usr/share/desktopforge/`) |

Why:
- Root-owned files come from the package manager, verified by RPM signatures.
- Users can remove DesktopForge's machinery with ordinary tools.
- The helper's version always matches its recipes.

Differences from the lab helper:
- New names: bus `org.desktopforge.Helper1`, actions such as
  `org.desktopforge.install-session`, `…remove-session`, `…repair-session`.
- No synthetic or lab recipes, and no lab-admin shortcuts.
- Records stay in `/var/lib/desktopforge/`. Lab and production never share a bus
  name or Polkit action, so lab authorizations can never apply to production.

Distribution:
- First a Fedora **COPR** the user enables explicitly. DesktopForge must never add
  a repository silently, its own included.
- Later, a Fedora package review, which brings independent review and
  Fedora-signed packages.

### Hardening needed before release

1. **SELinux.** The lab helper runs as `unconfined_service_t`. Ship a small policy
   module that confines the helper to its state directory, the session and config
   paths, the system bus, and starting transient units. Run in permissive mode
   during testing, enforcing before release.
2. **Package backend.** Replace the CLI parsing of DNF5 output with Fedora's
   **dnf5daemon** D-Bus API (`org.rpm.dnf.v0`, present on Fedora Workstation).
   It gives structured transactions, progress and offline-transaction awareness
   with no table parsing. Keep the current adapter as the tested fallback.
3. **Independent security review** of the helper protocol and code.
4. **Helper updates.** A helper upgrade must read the records written by older
   versions; the schema stays strict and versioned.

### Alternatives considered

| Option | Why not (now) |
| --- | --- |
| GUI installs the helper on first run via `pkexec` | Bootstraps privilege from unverified code; nothing vouches for the helper |
| Flatpak GUI + RPM helper | Possible later; adds portal and sandbox questions without changing the privileged design |
| AppImage including the helper | Ruled out in ARCHITECTURE.md: no bundled privileged code |

## 4. Decision 2 — what makes a recipe approved

Proposed lifecycle: **draft → lab-validated → approved → released**.
- Only **approved** recipes ship in `desktopforge-helper`.
- The helper refuses any recipe it did not ship with, as it does today.

**Lab-validated** requires a committed evidence file
`validation/<recipe-id>/<revision>.json`, produced from the VM runs. It
records the recipe hash, DesktopForge commit, image and package versions,
display managers, renderer, and the result of each case:

| Case | Already exercised for the reference recipe |
| --- | --- |
| Preview shows packages, files, notes and blockers | Yes |
| Install, then login, logout cleanup, original desktop login | Yes (GDM, SDDM) |
| Reboot with the session installed, and during it | Yes (GDM) |
| Failed install (network), retry | Yes |
| Software rendering blocked; no-display fallback | Yes |
| Removal, reinstall, edited-file removal | Yes (GDM, SDDM) |
| Repair (missing file, missing package, edited file) | Yes (GDM) |
| Real GPU (Intel, AMD) | **No** |
| Fedora release upgrade with the session installed | **No** |

**Approved** means:
1. The evidence is complete, with no unexplained failures.
2. Code review of the recipe and template.
3. **Your sign-off** as a signed tag or commit (for example `recipe-approved/fedora45-niri-noctalia-r3`).

Agent-generated recipes follow the same path; agents cannot approve.

**Versions:**
- The recipe records the package versions it was validated with.
- Newer versions after installation produce a warning, not a block (already implemented).
- A new **major** version of the compositor or shell, or a new Fedora release,
  requires re-validation before new installs are offered.

## 5. Decision 3 — when the GUI may install

The install button is enabled only when **all** of these hold, re-checked in
the helper at apply time:

1. `desktopforge-helper` is installed and its protocol version matches the GUI's.
2. An **approved** recipe matches the exact distribution, release and configured
   display manager (initially Fedora 45 with GDM or SDDM).
3. Rendering is `hardware` (the probe already exists).
4. Preflight is clean: no conflicting session IDs or files, no pending offline
   update, no unexpected DNF warnings.
5. The user reviewed the plan and authenticated through Polkit.

Otherwise the GUI stays exactly as it is now: read-only preview plus an
explanation of which gate failed. Lab mode remains only for development VMs.

**Initial support statement** (what the README would say): Fedora 45, GDM or
SDDM, Niri + Noctalia, Intel or AMD graphics, single-user desktop. NVIDIA,
Arch/CachyOS, Hyprland and DMS stay "not yet supported" until each passes the
same matrix.

## 6. Real hardware, and your laptop

VMs cannot validate GPUs, hybrid graphics, suspend or real user setups. Proposed order:

1. A spare machine, or a separate test account on a machine you don't rely on,
   with Fedora 45 and Intel or AMD graphics. Run the full matrix there, ideally
   with a btrfs snapshot first.
2. Only then, and only if you explicitly decide to, the reference laptop. It
   already runs Niri, Ryoku and SDDM, with global Niri hooks. The preflight would
   correctly report those hooks, and Niri and Noctalia as reused packages. That
   is a valuable test, but it is also the most complex target, so it should come last.

## 7. Risks and open questions

- **Third-party shell behavior:** Noctalia contacts GitHub on first start; its
  telemetry is off by default. Disclosed today; keep watching across versions.
- **Upstream session startup may change** (for example niri's environment
  import), so the launcher needs regression tests per release.
- **Uninstalling DesktopForge itself** leaves records and installed sessions
  behind. Recommend `desktopforge-helper` refuse removal while any recorded
  installation exists, or document how to remove those first.
- **Support burden:** each added compositor/shell/distribution multiplies the matrix.

## 8. Proposed next steps (after your decisions)

| Step | Size | Outcome |
| --- | --- | --- |
| 1. Production helper: rename and split from the lab helper, approved-recipe loader, protocol version check | Medium | **Done (2026-11-15):** one daemon (`src/desktopforge/helperd/daemon.py`) with `lab` and `production` profiles; production offers approved recipes only (none yet); `Info()` reports protocol, profile and recipes; lab verified in the guest |
| 2. RPM spec files plus a local mock/COPR build; install in a fresh VM | Medium | **Done (2026-11-15):** `packaging/desktopforge.spec` built in the SDDM VM; install, production `Info`, refusal of lab recipes, uninstall verified ([PACKAGING.md](PACKAGING.md)); mock/COPR build pending |
| 3. SELinux policy module (permissive, then enforcing in the VM) | Medium | Confined helper |
| 4. dnf5daemon backend, keeping the CLI adapter as fallback | Medium | Structured package transactions and progress |
| 5. Validation evidence file plus a script to produce it from VM runs | Small | Approval becomes checkable |
| 6. GUI gates (section 5) with clear "why not" messages | Small | Read-only unless every gate passes |
| 7. Real-hardware run on a spare machine | Depends on hardware | First non-VM evidence |

## 9. Decisions (accepted 2026-11-15)

1. **Packaging:** native RPMs (`desktopforge`, `desktopforge-helper`), first
   from a COPR the user enables explicitly; later a Fedora package review.
2. **Approval:** a committed evidence file from the lab matrix, code review and
   the owner's signed sign-off. Only approved recipes are bundled; nothing is
   downloaded at runtime.
3. **First real-machine scope:** Fedora 45, GDM or SDDM, Niri + Noctalia,
   Intel or AMD graphics, single-user desktop.
4. **Hardware:** no spare machine or test account identified yet. Real-GPU
   validation (step 7) waits until one is named; other steps proceed.
5. **Reference laptop:** stays read-only for the whole first release.
