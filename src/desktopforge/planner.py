"""Compatibility API for upstream callers, backed by the shared planning core.

No operations are executed. Catalog entries are research targets only.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .planning import build_plan, compatibility_catalog
from .recipes import COMPOSITORS, DISTRIBUTIONS, SHELLS

TARGETS = {compositor: SHELLS for compositor in COMPOSITORS}
DISTROS = DISTRIBUTIONS


def list_targets(inventory: dict[str, Any]) -> dict[str, Any]:
    distro = inventory['distribution'].get('id')
    return {
        'distribution': distro,
        'targets': [
            {**entry, 'eligible_for_install': False,
             'reason': 'No validated version-specific installation recipe or integration test'}
            for entry in compatibility_catalog() if entry['distribution'] == distro
        ],
        'supported_for_install': [],
        'notice': 'Catalog entries are research targets, not tested compatibility claims.',
    }


def plan(inventory: dict[str, Any], compositor: str, shell: str) -> dict[str, Any]:
    """Preserve upstream preview fields while sharing version-aware resolution."""
    # The original API accepted partial inventory dictionaries. Fill absent evidence
    # with unknown values on a copy, never inventing a positive observation.
    data = deepcopy(inventory)
    data['distribution'].setdefault('version_id', None)
    data.setdefault('display_manager', {'name': None})
    data.setdefault('sessions', {})
    for category, names in (('compositor_executables', COMPOSITORS), ('shell_executables', SHELLS)):
        evidence = data.setdefault(category, {})
        for name in names:
            evidence.setdefault(name, {'found': False})
    if compositor in TARGETS and shell in TARGETS[compositor]:
        result = build_plan(data, compositor, shell)
    else:
        result = {
            'schema_version': 1, 'dry_run': True, 'status': 'blocked',
            'compatibility': 'unsupported', 'operations': [],
            'target': {'distribution': data['distribution'].get('id'),
                       'version_id': data['distribution']['version_id'],
                       'compositor': compositor, 'shell': shell},
            'blockers': ['Compositor/shell combination is not in the research catalog'],
        }
    registered = sorted(
        entry['name'] for entry in data.get('session_analysis', {}).get('registered_sessions', [])
        if compositor in entry.get('compositor_candidates', [])
        and shell in entry.get('shell_candidates', []))
    result['target']['version'] = result['target']['version_id']
    result.update({
        'executable': False, 'writes': [], 'package_commands': [],
        'display_manager_policy': 'preserve',
        'evidence': {
            'compositor_executable_found': bool(data['compositor_executables'].get(compositor, {}).get('found', False)),
            'shell_executable_found': bool(data['shell_executables'].get(shell, {}).get('found', False)),
            'matching_registered_sessions': registered,
        },
        'proposed_steps': [
            'Validate distribution/version and package provenance',
            'Verify compositor and shell dependencies and their integration',
            'Review unique session launcher and user configuration paths',
            'Back up files before any modification',
            'Request explicit approval before privileged operations',
            'Verify new session while preserving existing login options',
        ],
        'notice': 'Preview only: no packages, files, services or sessions are modified.',
    })
    return result
