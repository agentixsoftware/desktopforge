"""Incomplete isolated-session design previews. No template execution or writes."""
from __future__ import annotations

import re

from .errors import RecipeError


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
            'compositor_argv': ['niri-session'],
            'environment': {'NIRI_CONFIG': 'absolute path to the isolated user config'},
            'user_manager_environment_policy': 'Snapshot owned values before startup; restore on normal exit and startup failure.',
            'requirements': [
                'Generate a complete, usable isolated config without copying or overwriting existing user configuration.',
                'Reject an already running compositor session and unreviewed service hooks.',
                'Validate template and every path component immediately before any future write.',
                'Define environment import scope and test cleanup on failure, interruption and logout.',
            ],
        },
        'blockers': ['Isolated session layout is an incomplete design draft; launcher code and lifecycle validation are unavailable.'],
    }
