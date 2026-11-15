# Developer quick start

This first implementation is **read-only**. It does not install desktops, edit system files, request root privileges, or validate compatibility.

Requirements: Python 3.10 or newer.

```bash
git clone https://github.com/agentixsoftware/desktopforge.git
cd desktopforge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
desktopforge detect
desktopforge detect --json
python -m pytest
```

Alternative without installation: `PYTHONPATH=src python3 -m desktopforge detect --json`.

## Current scope

The detector reads os-release, session .desktop files, a display-manager systemd symlink, selected environment variables, and executable availability on PATH. The results are best-effort observations; they are not proof that a compositor or shell will work. The catalog and deterministic blocked plan preview are available through `list` and `plan` (see README). Typed metadata and exact distro/version/display-manager constraints are implemented (see RECIPES.md). Typed operation proposals and deterministic dependency ordering are implemented with synthetic fixtures. Validated concrete recipes, component-version checks and validation provenance remain pending.

## Security model

On live Fedora, detection runs fixed, local-only `/usr/bin/rpm --query --noplugins` commands for a small package allowlist, with sanitized environment and a three-second timeout per query. It never invokes DNF, refreshes repositories or starts a transaction. Fixture roots never query the host package database. No configuration files are modified. The executable lookup uses `shutil.which`. The detector never evaluates the contents of os-release or session files.

## Native GUI preview

Use `scripts/desktopforge-gui` to open the application. The prepared checkout uses
an ignored `.venv-gui` environment; no system Python or packages were modified.
On a fresh development checkout, create an isolated environment and install the
optional GUI/dev extras there:

```bash
python3 -m venv .venv-gui
.venv-gui/bin/python -m pip install -e '.[gui,dev]'
QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -m pytest -q
```

The core CLI has no Qt dependency. GUI tests are skipped when PySide6 is absent;
they run in full in the GUI environment using Qt's offscreen platform. See
[GUI scope and validation](GUI.md). No privileged helper or installer is invoked.

Read-only inventory also reports static Fedora repository declarations from the
three default DNF5 repository directories. It parses only IDs and literal flags,
never evaluates URLs or downloads metadata, and does not resolve effective DNF
policy or installed-package origin. See [GUI evidence](GUI.md) for the limits.
