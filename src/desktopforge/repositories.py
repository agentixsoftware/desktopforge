"""Static DNF repository declarations, without URLs, network or effective-policy claims."""
import configparser
import os
from pathlib import Path
import re
import stat

from .preflight import _state

REPOSITORY_DIRS = ('etc/yum.repos.d', 'etc/distro.repos.d', 'usr/share/dnf5/repos.d')
FLAGS = ('enabled', 'gpgcheck', 'pkg_gpgcheck', 'repo_gpgcheck')


def _read_regular(root: Path, relative: Path) -> str:
    """Read a bounded regular file through directory FDs without following symlinks."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(child).st_mode):
                raise ValueError('Not a regular file')
            with os.fdopen(child, 'rb', closefd=False) as stream:
                data = stream.read(262145)
            if len(data) > 262144:
                raise ValueError('Repository configuration exceeds inspection limit')
            return data.decode('utf-8')
        finally:
            os.close(child)
    finally:
        os.close(fd)


def parse_repository_declarations(text: str) -> list[dict]:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string(text)
    if parser.defaults():
        raise ValueError('Inherited defaults are outside this static parser')
    declarations = []
    for section in parser.sections():
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', section):
            raise ValueError('Invalid repository ID')
        row = {'id': section}
        for flag in FLAGS:
            value = parser.get(section, flag, fallback=None)
            if value is None:
                row[flag] = 'unspecified'
            elif value.strip().lower() in ('1', 'true', 'yes', 'on'):
                row[flag] = 'declared_on'
            elif value.strip().lower() in ('0', 'false', 'no', 'off'):
                row[flag] = 'declared_off'
            else:
                row[flag] = 'unknown'
        declarations.append(row)
    return sorted(declarations, key=lambda row: row['id'])


def inspect_repositories(root: Path, distribution: str | None) -> dict:
    coverage = []
    declarations = []
    if distribution == 'fedora':
        for directory in REPOSITORY_DIRS:
            relative = Path(directory)
            state = _state(root, relative)
            coverage.append({'path': '/' + directory, 'state': state})
            if state != 'directory':
                continue
            try:
                entries = sorted((root / relative).iterdir(), key=lambda path: path.name)
            except OSError:
                coverage[-1]['state'] = 'unknown'
                continue
            for entry in entries[:256]:
                if entry.suffix != '.repo':
                    continue
                path = relative / entry.name
                state = _state(root, path)
                record = {'path': '/' + str(path), 'state': state}
                coverage.append(record)
                if state != 'file':
                    continue
                try:
                    rows = parse_repository_declarations(_read_regular(root, path))
                except (OSError, UnicodeError, ValueError, configparser.Error):
                    # Never expose parser exceptions, raw lines, credentials or URLs.
                    record['state'] = 'unreadable_or_invalid'
                    continue
                declarations.extend({**row, 'path': '/' + str(path)} for row in rows)
            if len(entries) > 256:
                coverage.append({'path': '/' + directory, 'state': 'inspection_limit'})
    ids = [row['id'] for row in declarations]
    return {'status': 'static_only' if distribution == 'fedora' else 'unavailable',
            'declarations': sorted(declarations, key=lambda row: (row['id'], row['path'])),
            'duplicate_ids': sorted({name for name in ids if ids.count(name) > 1}),
            'coverage': coverage, 'installed_package_origin': 'unknown',
            'limitations': [
                'Declared flags are not effective DNF policy; defaults, custom reposdir, overrides and plugins are not resolved.',
                'Repository names and flags do not prove package origin, signing-key trust or package availability.',
                'Only fixed repository directories are inspected; URLs, credentials and key locations are not collected.',
                'No DNF commands, repository refreshes, downloads or configuration changes are performed.',
            ]}
