"""Incomplete isolated-session design previews. No template execution or writes."""
from __future__ import annotations

import re

from .errors import RecipeError
from .lifecycle import lifecycle_contract


def session_layout_preview(template: str, session_id: str, compositor: str, shell: str) -> dict | None:
    if not re.fullmatch(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+)*', session_id):
        raise RecipeError('Invalid generated session ID')
    if (template, compositor, shell) != ('niri-noctalia-v5', 'niri', 'noctalia'):
        return None
    launcher = f'/usr/libexec/desktopforge/sessions/{session_id}/launch'
    relative_config = f'desktopforge/sessions/{session_id}/niri.kdl'
    return {
        'template': template, 'status': 'draft', 'complete': False, 'executable': False,
        'system_files': [
            {'path': f'/usr/share/wayland-sessions/{session_id}.desktop', 'overwrite': False,
             'content_preview': '[Desktop Entry]\nName=DesktopForge Niri (Noctalia)\n'
                                f'Exec={launcher}\nType=Application\nDesktopNames=niri\n'},
            {'path': launcher, 'overwrite': False, 'content_preview': None},
        ],
        'user_config': {'base': 'XDG_CONFIG_HOME (absolute), otherwise HOME/.config',
                        'relative_path': relative_config, 'overwrite': False,
                        'fragment_preview': 'spawn-at-startup "noctalia"\n',
                        'complete': False},
        'launch_contract': {
            'lifecycle_model': lifecycle_contract(),
            'runtime_candidate': {'entry_point': 'desktopforge-session',
                                  'status': 'experimental_unvalidated',
                                  'modes': ['nested', 'standalone_tty'],
                                  'strategy': 'unique transient user service and private D-Bus'},
            'compositor_argv': ['/usr/bin/niri', '--config', '<generated-private-config>'],
            'environment': {'XDG_CONFIG_HOME': 'private attempt config directory',
                            'DBUS_SESSION_BUS_ADDRESS': 'private D-Bus session'},
            'user_manager_environment_policy': 'Do not import or change the shared user-manager environment.',
            'requirements': [
                'Generate a complete, usable isolated config without copying or overwriting existing user configuration.',
                'Reject an already running compositor session and unreviewed service hooks.',
                'Validate template and every path component immediately before any future write.',
                'Keep shared manager environment unchanged and verify owned cgroup cleanup on failure, interruption and logout.',
            ],
        },
        'blockers': ['Installed login-session integration and real VM lifecycle validation remain unavailable; the runnable trial launcher is experimental.'],
    }
