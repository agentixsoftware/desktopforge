"""Read-only filesystem evidence for planning; never follow inspected symlinks.

These are conflict-review hints, not an effective systemd/DM configuration parser
or an authorization/preflight gate for an executor.
"""
from __future__ import annotations

from pathlib import Path
import stat


def _state(anchor: Path, relative: Path) -> str:
    """lstat each component so a fixture or inspected link cannot escape its tree."""
    if relative.is_absolute() or '..' in relative.parts:
        return 'unknown'
    path = anchor
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            return 'symlink' if stat.S_ISLNK(mode) else 'unknown'
        for index, part in enumerate(relative.parts):
            path = path / part
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                return 'symlink'
            if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
                return 'unknown'
        if stat.S_ISDIR(mode):
            return 'directory'
        if stat.S_ISREG(mode):
            return 'file'
        return 'other'
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'unknown'


def inspect_preflight(root: Path, config_home: Path | None) -> dict:
    """Only inspect fixed paths and directory names; no file contents are evaluated.

    config_home is a path inside root, or None when user context is unavailable.
    PATH/HOME from another account must never be guessed or borrowed.
    """
    observations = []
    coverage = []
    occupied = set()

    def directory(relative: Path, category: str, *, session_names: bool = False) -> None:
        state = _state(root, relative)
        label = '/' + relative.as_posix()
        if state == 'directory':
            try:
                entries = sorted((root / relative).iterdir(), key=lambda entry: entry.name)
            except OSError:
                state = 'unknown'
            else:
                for entry in entries:
                    child_state = _state(root, relative / entry.name)
                    if child_state == 'unknown':
                        observations.append({'category': category, 'path': label + '/' + entry.name,
                                             'state': 'unknown'})
                    elif category != 'managed_namespace' and category != 'session_directory':
                        observations.append({'category': category, 'path': label + '/' + entry.name,
                                             'state': child_state})
                    if session_names:
                        if category == 'session_directory':
                            if entry.name.endswith('.desktop'):
                                occupied.add(entry.name[:-8])
                        else:
                            occupied.add(entry.name)
        coverage.append({'path': label, 'state': state, 'expected': 'directory'})
        if state not in ('directory', 'absent'):
            observations.append({'category': category, 'path': label, 'state': state})

    for path, category in (
        ('etc/systemd/user/niri.service.d', 'compositor_hook'),
        ('usr/lib/systemd/user/niri.service.d', 'compositor_hook'),
        ('etc/systemd/user/default.target.wants', 'user_service_hook'),
        ('etc/systemd/user/niri.service.wants', 'compositor_hook'),
        ('etc/sddm.conf.d', 'display_manager_config'),
        ('usr/lib/sddm/sddm.conf.d', 'display_manager_config'),
        ('etc/environment.d', 'environment_hook'),
        ('usr/lib/environment.d', 'environment_hook'),
    ):
        directory(Path(path), category)
    for path, category in (
        ('etc/systemd/user/niri.service', 'compositor_override'),
        ('etc/sddm.conf', 'display_manager_config'),
        ('etc/gdm/custom.conf', 'display_manager_config'),
    ):
        state = _state(root, Path(path))
        coverage.append({'path': '/' + path, 'state': state})
        if state != 'absent':
            observations.append({'category': category, 'path': '/' + path, 'state': state})
    marker = _state(root, Path('run/ostree-booted'))
    coverage.append({'path': '/run/ostree-booted', 'state': marker})
    directory(Path('usr/share/wayland-sessions'), 'session_directory', session_names=True)
    directory(Path('usr/libexec/desktopforge/sessions'), 'managed_namespace', session_names=True)
    user_context = 'unknown'
    if config_home is not None:
        try:
            relative_config = config_home.relative_to(root)
        except ValueError:
            relative_config = None
        if relative_config is not None and '..' not in relative_config.parts:
            user_context = 'provided'
            directory(relative_config / 'systemd/user/niri.service.d', 'compositor_hook')
            directory(relative_config / 'systemd/user/default.target.wants', 'user_service_hook')
            directory(relative_config / 'systemd/user/niri.service.wants', 'compositor_hook')
            directory(relative_config / 'environment.d', 'environment_hook')
            directory(relative_config / 'desktopforge/sessions', 'managed_namespace', session_names=True)
            for name in ('niri.service', 'ryoku-bootstrap.service'):
                relative = relative_config / 'systemd/user' / name
                state = _state(root, relative)
                coverage.append({'path': '/' + relative.as_posix(), 'state': state})
                if state != 'absent':
                    observations.append({'category': 'compositor_override',
                                         'path': '/' + relative.as_posix(), 'state': state})
    complete = user_context == 'provided' and all(
        item['state'] not in ('unknown', 'symlink', 'other')
        and (item.get('expected') != 'directory' or item['state'] in ('directory', 'absent'))
        for item in coverage)
    complete = complete and not any(item['state'] == 'unknown' for item in observations)
    return {
        'schema_version': 1,
        'user_context': user_context,
        'inspection_complete': complete,
        'ostree_boot_marker': marker,
        'occupied_session_ids': sorted(occupied),
        'observations': sorted(observations, key=lambda item: (item['category'], item['path'])),
        'coverage': sorted(coverage, key=lambda item: item['path']),
        'limitations': [
            'Names and path types only; file contents and effective configuration are not evaluated.',
            'An absent OSTree boot marker does not establish a supported mutable installation.',
            'User-manager environment, runtime units and other users are not inspected.',
            'Filesystem state may change after inspection; no names are reserved.',
        ],
    }


def preflight_preview(evidence: dict | None) -> dict:
    if evidence is None:
        return {'status': 'incomplete', 'findings': [],
                'blockers': ['Read-only preflight evidence is unavailable.']}
    findings = []
    blockers = []
    marker = evidence.get('ostree_boot_marker', 'unknown')
    if marker not in ('absent', 'unknown'):
        findings.append({'code': 'ostree_marker', 'path': '/run/ostree-booted',
                         'reason': 'OSTree boot marker observed; this DNF recipe is not applicable.'})
        blockers.append('OSTree boot marker observed; package installation proposals are not applicable.')
    for item in evidence.get('observations', []):
        findings.append({'code': 'review_required', 'path': item['path'],
                         'reason': f"Review {item['category']} ({item['state']}); do not change it automatically."})
    if evidence.get('observations'):
        blockers.append('Existing configuration hooks or uncertain paths require review before adding a session.')
    if not evidence.get('inspection_complete', False):
        blockers.append('Read-only preflight inspection is incomplete; user context or path access is uncertain.')
    return {'status': 'review_required' if findings else 'incomplete' if blockers else 'observed',
            'findings': findings, 'blockers': blockers,
            'notice': 'Static evidence only; an observed result never authorizes installation.'}
