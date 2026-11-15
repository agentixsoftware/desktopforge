"""Read-only inspection of DesktopForge install records against the live system.

Records are read from a fixed root-owned directory without following symlinks,
validated against the shared schema, and every recorded file is re-hashed.
Nothing here changes the system or trusts a record more than the evidence.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from .helper import records as schema

MAX_RECORDS = 64
MAX_RECORD_BYTES = 64 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024


def _open_nofollow(path: Path, flags=os.O_RDONLY):
    return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)


def file_status(root: Path, path: str, sha256: str) -> str:
    """intact | modified | missing | unsafe | unreadable for one recorded file."""
    target = root / path.lstrip('/')
    try:
        info = target.lstat()
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unreadable'
    if not stat.S_ISREG(info.st_mode):
        return 'unsafe'  # a symlink or other object replaced the recorded file
    if info.st_size > MAX_FILE_BYTES:
        return 'modified'
    try:
        fd = _open_nofollow(target)
    except OSError:
        return 'unreadable'
    with os.fdopen(fd, 'rb') as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    return 'intact' if digest == sha256 else 'modified'


RPM_QUERY = '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n'


def query_recorded_packages(names, runner=None) -> dict | None:
    """name -> set of (evr, arch) currently installed, for every recorded name, or None if unknown.

    Read-only, fixed argv, names already validated by the record schema. Every
    requested name must be accounted for and rpm's status must equal the number
    of missing packages; anything else means the answer is unknown.
    """
    names = sorted(set(names))
    if not names:
        return {}
    run = runner or subprocess.run
    try:
        result = run(['/usr/bin/rpm', '--query', '--noplugins', '--queryformat', RPM_QUERY, '--', *names],
                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10, shell=False, cwd='/',
                     env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/'})
    except (OSError, subprocess.SubprocessError):
        return None
    found, missing = {}, set()
    for line in result.stdout.splitlines():
        if line.startswith('package ') and line.endswith(' is not installed'):
            missing.add(line[len('package '):-len(' is not installed')])
            continue
        parts = line.split('\t')
        if len(parts) != 3:
            return None
        found.setdefault(parts[0], set()).add((parts[1], parts[2]))
    if set(found) | missing != set(names) or set(found) & missing or result.returncode != len(missing):
        return None
    return {name: found.get(name, set()) for name in names}


def package_status(package_inventory: dict | None, name: str, evr: str | None, arch: str | None,
                   live: dict | None = None) -> str:
    """Prefer a direct query of the recorded names; fall back to the inventory's tracked RPMs."""
    if live is not None and name in live:
        if not live[name]:
            return 'missing'
        if evr is None:
            return 'present'
        return 'present' if (evr, arch) in live[name] else 'changed'
    for package in (package_inventory or {}).get('packages', []):
        if package.get('name') != name:
            continue
        if package.get('status') == 'not_installed':
            return 'missing'
        if package.get('status') != 'installed':
            return 'unknown'
        if evr is None:
            return 'present'
        found = {(f"{r['epoch']}:{r['version']}-{r['release']}", r['architecture'])
                 for r in package.get('records', [])}
        return 'present' if (evr, arch) in found else 'changed'
    return 'unknown'


def summarize(record: dict, root: Path, package_inventory: dict | None, live: dict | None = None) -> dict:
    files = [{'path': f['path'], 'role': f['role'], 'status': file_status(root, f['path'], f['sha256'])}
             for f in record['files']]
    installed = [{'name': p['name'], 'evr': p['evr'], 'arch': p['arch'],
                  'status': package_status(package_inventory, p['name'], p['evr'], p['arch'], live)}
                 for p in record['packages']['installed']]
    reused = [{'name': n, 'status': package_status(package_inventory, n, None, None, live)}
              for n in record['packages']['reused']]
    if record['state'] != 'completed':
        overall = 'failed'
    elif any(f['status'] in ('missing', 'unsafe', 'unreadable') for f in files):
        overall = 'incomplete'
    elif any(f['status'] == 'modified' for f in files) or any(
            p['status'] in ('missing', 'changed') for p in installed + reused):
        overall = 'modified'
    elif any(p['status'] == 'unknown' for p in installed + reused):
        overall = 'unverified'  # files match, but package state could not be established
    else:
        overall = 'intact'
    return {'install_id': record['install_id'], 'recorded_at': record['recorded_at'], 'state': record['state'],
            'status': overall, 'recipe': dict(record['recipe']), 'target': dict(record['target']),
            'session': dict(record['session']), 'files': files,
            'packages': {'installed': installed, 'reused': reused}, 'producer': record['producer']}


def inspect_installations(root: Path = Path('/'), package_inventory: dict | None = None,
                          runner=None) -> dict:
    directory = root / schema.RECORDS_DIR.lstrip('/')
    result = {'schema_version': 1, 'directory': schema.RECORDS_DIR, 'status': 'none',
              'installations': [], 'issues': []}
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return result
    except OSError:
        return {**result, 'status': 'unavailable', 'issues': ['Install record directory is unreadable.']}
    if not stat.S_ISDIR(info.st_mode) or (root == Path('/') and (info.st_uid != 0 or info.st_mode & 0o022)):
        return {**result, 'status': 'unavailable',
                'issues': ['Install record directory is not a root-owned, non-writable directory; ignored.']}
    names = sorted(n for n in os.listdir(directory) if n.endswith('.json'))
    removals, parsed = {}, []
    if len(names) > MAX_RECORDS:
        result['issues'].append(f'Only the first {MAX_RECORDS} install records were read.')
    for name in names[:MAX_RECORDS]:
        path = directory / name
        try:
            entry = path.lstat()
            if not stat.S_ISREG(entry.st_mode) or entry.st_size > MAX_RECORD_BYTES:
                raise schema.RecordError('not a small regular file')
            if root == Path('/') and (entry.st_uid != 0 or entry.st_mode & 0o022):
                raise schema.RecordError('not root-owned or writable by others')
            fd = _open_nofollow(path)
            with os.fdopen(fd, 'rb') as stream:
                data = stream.read(MAX_RECORD_BYTES + 1)
            if name.endswith('.removal.json'):
                removal = schema.parse_removal(data)
                if name != removal['removal_id'] + '.removal.json':
                    raise schema.RecordError('file name does not match removal_id')
                removals.setdefault(removal['install_id'], []).append(removal)
                continue
            record = schema.parse(data)
            if name != record['install_id'] + '.json':
                raise schema.RecordError('file name does not match install_id')
        except (OSError, schema.RecordError) as exc:
            result['issues'].append(f'{name}: ignored ({exc})')
            continue
        parsed.append(record)
    live = None
    if root == Path('/') or runner is not None:
        names = [p['name'] for r in parsed for p in r['packages']['installed']]
        names += [n for r in parsed for n in r['packages']['reused']]
        live = query_recorded_packages(names, runner)
    result['installations'] = [summarize(r, root, package_inventory, live) for r in parsed]
    for installation in result['installations']:
        history = sorted(removals.get(installation['install_id'], []), key=lambda r: r['recorded_at'])
        if history:
            last = history[-1]
            installation['removal'] = {'removal_id': last['removal_id'], 'recorded_at': last['recorded_at'],
                                       'state': last['state'], 'kept': last['kept']}
            installation['status'] = 'removed' if last['state'] == 'completed' else 'partially-removed'
    result['installations'].sort(key=lambda r: r['recorded_at'])
    result['status'] = 'observed' if result['installations'] else ('none' if not result['issues'] else 'unavailable')
    return result


LAUNCH_RESULTS = ('started', 'no-display', 'start-failed', 'refused')
FAILED_LAUNCHES = ('no-display', 'start-failed', 'refused')


def launch_state_directory(environ: dict) -> Path | None:
    base = environ.get('XDG_STATE_HOME', '')
    if not Path(base).is_absolute():
        home = environ.get('HOME', '')
        if not home or not Path(home).is_absolute():
            return None
        base = str(Path(home) / '.local' / 'state')
    return Path(base) / 'desktopforge' / 'launches'


def read_launches(directory: Path | None) -> dict:
    """Last recorded launch per DesktopForge session ID, from the user's own state files."""
    latest = {}
    if directory is None:
        return latest
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith('.json'))[:16]
    except OSError:
        return latest
    for name in names:
        try:
            fd = _open_nofollow(directory / name)
            with os.fdopen(fd, 'rb') as stream:
                data = json.loads(stream.read(64 * 1024))
            session_id = data['session_id']
            event = data['events'][-1]
            if not (isinstance(session_id, str) and schema.SESSION_ID.fullmatch(session_id)
                    and event.get('result') in LAUNCH_RESULTS and isinstance(event.get('time'), str)
                    and schema.TIMESTAMP.fullmatch(event['time'])):
                continue
            latest[session_id] = {'time': event['time'], 'result': event['result'],
                                  'detail': str(event.get('detail', ''))[:300]}
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            continue
    return latest


def attach_launches(installations: dict, launches: dict) -> dict:
    for installation in installations.get('installations', []):
        installation['last_launch'] = launches.get(installation['session']['id'])
    return installations


def launch_warning(installation: dict) -> str | None:
    last = installation.get('last_launch') or {}
    if last.get('result') not in FAILED_LAUNCHES:
        return None
    return (f"The last login to {installation['session']['name']} ({last['time']}) did not start: "
            f"{last['detail']} The login screen may still preselect this session; choose another session there.")


def installation_for(inventory: dict, compositor: str, shell: str) -> dict | None:
    """Most recent completed DesktopForge installation of this combination, if any."""
    found = [i for i in (inventory.get('desktopforge_installations') or {}).get('installations', [])
             if i['target'] == {'compositor': compositor, 'shell': shell} and i['state'] == 'completed'
             and i['status'] != 'removed']
    return found[-1] if found else None
