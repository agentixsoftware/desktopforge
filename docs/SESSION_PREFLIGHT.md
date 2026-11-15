# Isolated session drafts and read-only preflight evidence

This Milestone 1 layer exposes design drafts and static filesystem observations.
It cannot authorize installation, start a desktop, generate a runnable launcher,
modify configuration or reserve a path. All plans remain blocked and non-executable.

## Isolated layout preview

The `niri-noctalia-v5` design maps a generated session ID to three locations:

| Purpose | Draft location |
| --- | --- |
| New login entry | `/usr/share/wayland-sessions/<session-id>.desktop` |
| Dedicated launcher | `/usr/libexec/desktopforge/sessions/<session-id>/launch` |
| Isolated Niri config | `<user-config-base>/desktopforge/sessions/<session-id>/niri.kdl` |

The user config base is an absolute `XDG_CONFIG_HOME`, falling back to
`HOME/.config`. The draft never selects another account's config or copies the
existing Niri configuration. Its Noctalia autostart fragment is not a complete
usable Niri configuration. The launcher is intentionally represented by a path
and contract with no executable content. The desktop entry's draft `Exec` names
that unavailable launcher and must not be installed as-is.

The launch contract requires `niri-session`, selection of the isolated config via
`NIRI_CONFIG`, ownership of imported environment values, rejection of an already
running compositor, and tested cleanup on normal exit, failure and interruption.
It is a specification, not an implemented runtime. No user-manager environment is
queried, imported or cleared. No service is started, stopped, enabled or masked.

`session_configuration_preview` contains those incomplete drafts separately from
the recipe's operation proposals. Every draft has `overwrite: false` and the layout
has `complete: false` and `executable: false`. Unknown templates have no layout.

## Static inspection

Inventory schema version 3 adds `preflight_evidence`. The detector performs
`lstat` and directory listings at fixed locations. It does not evaluate config
contents or invoke systemd, display managers, shells or package managers.

The evidence covers:

- System/global and selected-user Niri service overrides, drop-ins and wants.
- Global and selected-user default-target wants (user service hooks).
- SDDM configuration directories and the SDDM/GDM primary config paths.
- System and selected-user environment config directories.
- `/run/ostree-booted`, treated as a marker rather than proof of mutability.
- Existing Wayland entry filenames and DesktopForge launcher/config namespaces.

Only the current execution account's config context is selected by default.
Running the CLI as a different account from the graphical session is not enough
to inspect that graphical user's configuration. No other home is guessed. An
injected fixture root does not borrow the host's HOME or XDG_CONFIG_HOME;
tests must pass an explicit `config_home` inside that root when needed.

Each path has an explicit state, including absent, file, directory, symlink or
unknown. Component checks stop at symlinks without intentionally traversing them.
An unreadable/unexpected directory or uncertain ancestor makes inspection
incomplete. Symlinks used as individual service/config files are review hints;
they are not opened and may be legitimate masks. Config files and hooks are
reported for review, not declared broken simply because they exist.

These path checks are best-effort observations, not race-proof executor path
validation. Effective configuration, runtime unit state, other service search
paths, inherited environments, file contents and other users remain outside this
inspection. An observed result can never be interpreted as safe to apply.

## Planner behavior

`preflight` in plan JSON contains findings and blockers. Its status is one of
`observed`, `incomplete` or `review_required`; none means installable. Missing
preflight evidence in inventories from older callers is explicitly incomplete.
The text preview prints review paths and incomplete draft locations.

Existing entry names reserve IDs even when the entry is a broken symlink or an
unexpected file type that ordinary session inventory omits. Existing files or
directories in DesktopForge's dedicated launcher or selected-user config
namespace also reserve their basename. One shared suffixed ID is used across
all draft paths. Unreadable or symlinked namespaces cannot establish that any ID
is free; the resulting preview remains blocked and inspection is incomplete.

An observed OSTree boot marker suppresses operation proposals and session drafts
for the current DNF recipe. Its absence does not prove mutable Fedora support.
The initial catalog remains unverified. Filesystem state can change after
inspection; every path and conflict must be rechecked immediately before a future
approved write by a separately reviewed implementation.

## Validation

Offline fixtures cover the reference Ryoku bootstrap/router shape, masks,
symlinked directories, unknown access, missing user context, OSTree markers,
reserved namespace collisions and incomplete layout contracts. Tests verify
stable output and unchanged input/files; the live reference scan identifies the
installed hooks without touching them. Disposable VM login/lifecycle validation
and GPU checks are still pending.
