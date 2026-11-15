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

The detector reads os-release, session .desktop files, a display-manager systemd symlink, selected environment variables, and executable availability on PATH. The results are best-effort observations; they are not proof that a compositor or shell will work. The catalog and deterministic blocked plan preview are available through `list` and `plan` (see README). Typed metadata and exact distro/version/display-manager constraints are implemented (see RECIPES.md). Concrete operations, component-version checks and validation provenance remain pending.

## Security model

No commands are executed. No configuration files are modified. The executable lookup uses `shutil.which`. The detector never evaluates the contents of os-release or session files.
