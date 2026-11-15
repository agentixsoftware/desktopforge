# DesktopForge native application preview

The first PySide6 window opens DesktopForge itself. It reads system evidence and
previews installation requirements. It does not start a desktop, execute a recipe,
install a package, request privilege, modify a display manager or edit user config.
Installation is visibly unavailable and has no executor callback.

## Launch from this checkout

```bash
./scripts/desktopforge-gui
```

The helper locates the source from its own path, and uses the prepared project
`.venv-gui` when the invoking interpreter lacks PySide6. No activation or
PYTHONPATH setting is required. The virtual environment is ignored by Git and is
not a system-package installation. A fresh checkout can install `.[gui,dev]` in
its own environment; see DEVELOPMENT.md.

From the reference laptop's actual ryoku terminal, the complete path is:

```bash
/home/ryoku/vick/Projects/desktopforge/scripts/desktopforge-gui
```

The existing shared Projects mount makes the code/environment accessible. No
permission changes or account switching are needed. The GUI inspects the account
that launches it and displays that account in the system panel. It does not borrow
another account's graphical-session variables. If no display is available, it
returns a clear error before constructing a Qt window.

After installing the GUI extra into an isolated development environment, the
console entry point is `desktopforge-gui`; `python -m desktopforge.gui` also works.
The separate `desktopforge-session` tool opens a nested/standalone desktop trial,
not this application.

## What is available

- **Refresh system** asynchronously reads the shared detector's evidence. Scan
  progress is visible, and a second refresh cannot overlap the current one.
- **Your system** shows distro, execution account, configured display manager,
  current desktop and conservative active-shell confidence. Correlated service
  hints stay labeled as hints, not confirmed ownership. Registered sessions are
  listed separately from executable discovery.
- **Combination choices** cover the existing research catalog. Changing either
  selection immediately rebuilds the shared core's blocked dry-run preview.
- **Proposals** show deterministic order, descriptions and future permission
  requirements. No availability check in this table is executed by the GUI.
- **Requirements** explain blocking issues. The Review requirements button opens
  that view; it is not a fake Next/Continue installation step.
- **References** show the selected recipe's reviewed HTTPS source links. They are
  not fetched automatically. A click opens a link in the user's browser.
- **JSON details** show inventory and plan data. Copy plan JSON copies only the
  plan to the clipboard when the user clicks; there is no automatic export or
  settings persistence.

A combination inside the catalog is still unverified. "Outside current recipe
scope" describes the core's unsupported result without claiming upstream software
cannot work. Executable evidence does not promote a target to installation support.

Detection failure invalidates the previous inventory and plan, disables selection
and copying, and leaves Refresh available for retry. Planning errors clear stale
proposals/details but retain the valid inventory. Untrusted inventory names are
rendered as plain text. Even an optimistic/malformed planner result cannot enable
the installation control.

## Implementation boundary

`desktopforge.gui` loads Qt only when requested; core/CLI imports remain Qt-free.
The widget implementation calls `detect_system` and `build_plan` directly and
contains no launcher/executor integration. There is no hidden connection from the
disabled installation button to a system operation.

Inventory runs in a Qt worker thread. Closing during a scan waits for that
read-only operation to finish rather than destroying a running thread. The GUI
entry point explicitly disposes its window and pending Qt deletion events before
application teardown. No QSettings or desktop theme/config changes are used.

The window uses Qt Widgets and a local palette/stylesheet, without remote fonts,
web views or generated web assets. Plan views scroll on small windows.

## Validation

The GUI environment runs the full core suite plus offscreen interaction tests:
fixture inventory, target changes, requirements navigation, clipboard JSON,
failure/retry handling, conservative hint labels, small-window layout, duplicate
scan prevention, close-during-scan and real GUI-process shutdown. Tests also guard
against accidental calls into desktop runtime primitives.

A real local inventory was rendered offscreen and visually inspected during
development. It showed Fedora 45 COSMIC, configured SDDM, the four registered
sessions and the five Niri/Noctalia proposals with installation unavailable. This
is evidence of GUI rendering and core integration; it is not validation of an
installation or the separately running ryoku session.

## Installed package evidence

The **Packages** tab shows the selected compositor and shell's exact RPM package
names, installed epoch/version/release and architecture, and unverified reuse
candidates. The shared detector queries a fixed allowlist on live Fedora only;
there is no DNF invocation, repository refresh, transaction or privilege request.
Timeouts, unavailable RPM and ambiguous responses stay unknown. An absent package
means only that exact name is absent; an executable may have another origin.
Arch/CachyOS inspection remains unknown pending a separate adapter.

Vendor and source-RPM header fields are available in JSON details. They do not
prove the originating repository, signature trust, executable ownership or safe
reuse. Package presence never enables Install or satisfies recipe validation.
The queries use RPM's documented [query operation](https://rpm.org/docs/6.0.x/man/rpm.8)
and [query format](https://rpm.org/docs/6.0.x/man/rpm-queryformat.7).
