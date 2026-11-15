# Try the Niri + Noctalia launcher

DesktopForge now has a runnable **experimental launcher candidate**. It is not a
certified production release: VM login/logout and GPU validation are still
pending. It does not install packages or register/replace login sessions.

## Windowed trial

Run these from the repository root in a terminal belonging to your actual
Wayland desktop account:

```bash
PYTHONPATH=src python3 -m desktopforge.session_launcher --nested --check
PYTHONPATH=src python3 -m desktopforge.session_launcher --nested
```

The first command is read-only. It checks dependencies, account/runtime/display
context, versions and the user manager, and validates the generated configuration
with Niri's parser. It starts no desktop and writes no configuration. Add `--json`
to `--check` for structured results.

The second command opens a nested Niri window and starts Noctalia inside it.
This is a desktop-session trial. The read-only DesktopForge application is
available separately through `scripts/desktopforge-gui`; it is not opened by this
command. The trial opens Noctalia's application menu automatically after initialization; no application is launched until you select one. You should
see Noctalia's bar/panels. Focus the nested window and use **Alt+D** or
**Alt+Space** for its application menu, or **Alt+Return** for an available
terminal. A completely empty window without a bar requires startup diagnostics.
Quit with **Alt+Shift+E** while focused inside the window, close the nested
window, or press **Ctrl+C** in the launching terminal. Keys may be intercepted by
the parent compositor; Ctrl+C remains available in the separate terminal.
The starter config is minimal and Wayland-only (Xwayland is disabled); it does
not import your current keybindings. Applications started inside the trial belong
to its lifecycle and are stopped
when it ends; save any work before quitting.

On this laptop the graphical account is `ryoku`, while Codex runs as `vick`.
Run the trial as `ryoku` using the ordinary system Python in its terminal, rather
than an agent wrapper that switches to vick. Changing directories into
`/home/vick` does not change an account's identity. `id -un` should report `ryoku`
and `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY` should describe that desktop. Never copy
another user's runtime variables or run the launcher with sudo.

After installing DesktopForge into a development environment, the equivalent
entry point is `desktopforge-session --nested`. No installation is needed to use
the source commands above.

## Standalone trial in a VM

In a disposable Fedora VM with the dependencies already installed, log out of the
graphical session and log into a local TTY as the test user. Then run:

```bash
PYTHONPATH=src python3 -m desktopforge.session_launcher --standalone --check
PYTHONPATH=src python3 -m desktopforge.session_launcher --standalone
```

The launcher requires an active, local, same-user logind TTY session, no inherited
graphical display, and an inactive shared `niri.service`. It launches Niri directly
without `--session` or the distribution's `niri-session` wrapper. It does not
install a display-manager entry; returning to an existing desktop remains the
normal display-manager workflow after the trial ends.

Portals, accessibility, suspend/seat behavior, desktop autostart and real hardware
are not certified for this isolated startup strategy. A standalone compositor
that cannot acquire the VM seat should fail with journal diagnostics; do not
change host seat or display-manager configuration to force it to start.

## Prerequisites

The initial reviewed scope is Niri 26.04 and Noctalia 5.x on Linux with a systemd
user manager version 254 or newer. The launcher checks fixed `/usr/bin` tools:
`niri`, `noctalia`, `systemctl`, `systemd-run`, `dbus-run-session` and `env`.
Standalone mode also uses `loginctl`. Missing dependencies are reported; they are
never installed automatically. No downloaded installation script is used.

## What the launcher changes

Each run creates a fresh private directory under
`$XDG_RUNTIME_DIR/desktopforge/launch-<attempt>-...` containing generated Niri
configuration and isolated XDG config/state/cache/data directories. The generated
Noctalia config skips first-run onboarding for the temporary trial, disables
telemetry, and disables its custom app-launch prefix and app-specific systemd
services. Each launch opens directly to the shell rather than repeating setup. It does not include an existing Niri config or system Noctalia config.
Persistent user desktop configuration is not edited or migrated.

A fresh private D-Bus session and a uniquely named transient service contain the
trial. Its name is printed as `Diagnostic unit: desktopforge-<token>.service`.
The service has no enablement, shared desktop target dependencies or changes to
existing units. Niri is invoked directly without `--session`, with notification
and inherited manager variables excluded. No shared user-manager environment is
imported, cleared or restored, and the shared `niri.service`/Ryoku bootstrap path
is not started. Old model revision tokens are not treated as real systemd APIs.

The controller does not forward arbitrary environment variables such as GitHub
tokens into the trial. It supplies an explicit allowlist. Niri's child-spawn path
and Noctalia's configured direct app launches keep normal descendants inside the
owned service. The private D-Bus session is not a filesystem/security sandbox:
applications can still access the account's files and system services with the
user's normal permissions. Only try trusted applications in it.

Noctalia initialization is confirmed through its documented daemon-ready return
and an attempt-bound readiness record; the controller also observes the Noctalia
executable in the owned cgroup. It stops the trial if the shell fails, disappears,
or is outside that cgroup. This is not a pixel-level verification of a usable UI.

## Cleanup and diagnostics

Normal exit and interruption stop only the identified transient service. The
controller checks the unit description, transient flag and invocation identity
before stopping it. `KillMode=control-group` and bounded stop/KILL handling cover
its remaining descendants. Generated files and the attempt marker are removed
only after unit shutdown and an empty/removed cgroup are confirmed. The lock inode
remains for subsequent runs.

The launcher retains the marker and run directory if it cannot establish owned
shutdown. It never adopts or stops an unrelated invocation. If the launcher is
force-killed, the user manager may keep the service running until it is stopped;
no automatic crash takeover is implemented. Runtime markers last only as long as
the user runtime directory survives.

While the trial is still open, use another terminal in the same desktop account:

```bash
PYTHONPATH=src python3 -m desktopforge.session_launcher --diagnose
```

This command reads the current attempt record, owned unit state, shell readiness
record, Noctalia log tail and a bounded journal excerpt. It does not start/stop
anything or change configuration, and it does not inspect another user's home or
runtime directory. It will report unavailable context if run through an agent
wrapper that switches accounts. Diagnostics from an ended successful attempt may
be unavailable because temporary profile files were already cleaned up.

For manual diagnostics, replace `<printed-unit>` with the exact name printed by this run:

```bash
journalctl --user -u '<printed-unit>' -b --no-pager
systemctl --user show '<printed-unit>' \
  -p Description -p InvocationID -p ActiveState -p ControlGroup
```

If a force-killed launcher left its own unit running, an operator can stop that
specific printed unit with `systemctl --user stop '<printed-unit>'` after checking
its identity. Keep any unfinished marker for review; don't delete it blindly to
bypass recovery checks. Never substitute `niri.service`, a Ryoku service or
`graphical-session.target` for the generated unit name.

## Evidence and limits

Automated tests cover generated argv/environment/config, parser validation,
readiness publication, cancellation, startup failures, identity changes and
cleanup refusal with an injected service manager. Native tests separately cover
real locks, crash markers, config descriptors and fixture child signals. During
development only Niri's parser/version commands and Noctalia's version command
were executed; no compositor or transient desktop service was launched here.

The startup strategy was reviewed against
[Niri 26.04 startup](https://github.com/niri-wm/niri/blob/v26.04/src/main.rs) and
[child spawning](https://github.com/niri-wm/niri/blob/v26.04/src/utils/spawning.rs).
The service boundary follows the documented
[systemd-run interface](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html).
Noctalia documents [daemon readiness](https://docs.noctalia.dev/noctalia/getting-started/running-the-shell/),
[configuration roots](https://docs.noctalia.dev/noctalia/configuration/), and
[app-launch behavior](https://docs.noctalia.dev/noctalia/v5.4.1/configuration/shell/).
These sources explain the design, not a passing VM integration result.

## Source helpers and diagnostic handoff

Executable source helpers locate the package using their own path, so they work
from any current directory without setting PYTHONPATH or installing the package:

- `scripts/desktopforge-session`: the same launcher/check/diagnose entry point.
- `scripts/desktopforge-diagnostics`: read-only session collection, saving a private
  JSON report in the checkout's ignored `.desktopforge-reports/` directory.

Use the path to the checkout that your current account can access. On the
reference laptop, ryoku accesses the shared project through
`/home/ryoku/vick/Projects/desktopforge`; vick's home is private and must not be
made public to work around that account boundary. Reports written through the
existing shared mount can be inspected by the development account without
changing ryoku's runtime/home permissions. The helper does not switch users,
invoke sudo, start/stop services or modify desktop configuration. The user still
has to initiate it in the correct account; the restricted agent cannot invoke a
process as ryoku on its own.

### Correct nested shortcuts

The generated config explicitly uses `Alt` for Niri's nested `Mod` and `Super` for
standalone `Mod`. Earlier Super-key instructions for nested mode were wrong.
Startup messages now name the actual modifier, and the application menu opens
at initialization so the trial has an immediately useful surface. The behavior
matches [Niri's modifier documentation](https://github.com/niri-wm/niri/wiki/Configuration:-Key-Bindings).

### Offscreen reproduction (2026-11-14)

A development run used already-installed Weston 15.0.1 with a headless backend,
private runtime/home/config directories under `/tmp`, and the real installed
Niri 26.04 / Noctalia 5.4.1 binaries. No shared desktop unit was started and no
installed desktop configuration was changed. Cleanup targeted only the harness's
own direct/adopted child processes, using pidfds rather than executable names.

Evidence: Noctalia reported successful initialization; its log recorded a
created/rendered bar, disabled telemetry, and `panel manager: opened "launcher"`.
The readiness record reported `ready: true` and `launcher_opened: true`. This
confirms the fresh-profile startup path reached the shell and app-menu command.
Screenshot capture and a Niri IPC query timed out under the offscreen backend,
so this is partial startup evidence, not a passing visual/interactive test or a
reproduction of the inaccessible ryoku desktop. User-manager unit orchestration
was not tested by that direct-process harness. No packages were installed.
