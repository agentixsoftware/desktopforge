"""Install records: what a DesktopForge installation created, installed and reused.

One strict schema shared by the privileged writer and the unprivileged reader.
Records are evidence for recognizing, verifying and (later) repairing or
removing an installation; they never authorize anything by themselves.
"""
import json
import re

SCHEMA = 1
RECORDS_DIR = '/var/lib/desktopforge/installs'
STATES = ('completed', 'failed_recoverable', 'failed_manual_recovery')
ROLES = ('session-entry', 'session-config')
# Records may only describe files in DesktopForge-owned namespaces.
FILE_PATTERNS = {
    'session-entry': re.compile(r'/usr/share/wayland-sessions/desktopforge-[a-z0-9-]{1,80}\.desktop'),
    'session-config': re.compile(r'/etc/desktopforge/sessions/[a-z0-9][a-z0-9.-]{0,80}\.kdl'),
}
INSTALL_ID = re.compile(r'[0-9a-f]{32}')
HEX64 = re.compile(r'[0-9a-f]{64}')
NAME = re.compile(r'[a-z0-9][a-z0-9+._-]{0,99}')
IDENT = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
SESSION_ID = re.compile(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+){0,7}')
TEXT = re.compile(r'[^\x00-\x1f\x7f]{1,200}')
EVR = re.compile(r'\d+:[A-Za-z0-9._+~^-]{1,100}')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
MAX_FILES, MAX_PACKAGES = 16, 200


class RecordError(Exception):
    pass


def _require(condition, message):
    if not condition:
        raise RecordError(message)


def _keys(value, required, optional=()):
    _require(isinstance(value, dict), 'expected an object')
    keys = set(value)
    _require(set(required) <= keys and keys <= set(required) | set(optional),
             f'unexpected or missing keys: {sorted(keys ^ set(required))}')


def validate(record):
    """Return the record unchanged if it matches schema 1 exactly; raise otherwise."""
    _keys(record, ('schema', 'install_id', 'recorded_at', 'state', 'producer', 'recipe', 'plan_hash',
                   'authorization', 'target', 'session', 'files', 'packages', 'journal'))
    _require(record['schema'] == SCHEMA, 'unsupported record schema')
    _require(isinstance(record['install_id'], str) and INSTALL_ID.fullmatch(record['install_id']), 'install_id')
    _require(isinstance(record['recorded_at'], str) and TIMESTAMP.fullmatch(record['recorded_at']), 'recorded_at')
    _require(record['state'] in STATES, 'state')
    _require(isinstance(record['producer'], str) and IDENT.fullmatch(record['producer']), 'producer')
    _require(isinstance(record['plan_hash'], str) and HEX64.fullmatch(record['plan_hash']), 'plan_hash')
    _require(record['journal'] == record['install_id'] + '.jsonl', 'journal')
    recipe = record['recipe']
    _keys(recipe, ('id', 'revision'))
    _require(isinstance(recipe['id'], str) and IDENT.fullmatch(recipe['id']), 'recipe id')
    _require(type(recipe['revision']) is int and 0 < recipe['revision'] < 10**6, 'recipe revision')
    auth = record['authorization']
    _keys(auth, ('action', 'uid'))
    _require(isinstance(auth['action'], str) and re.fullmatch(r'[a-z0-9.-]{1,100}', auth['action']), 'action')
    _require(type(auth['uid']) is int and 0 <= auth['uid'] < 2**32 - 1, 'uid')
    target = record['target']
    _keys(target, ('compositor', 'shell'))
    _require(all(isinstance(v, str) and IDENT.fullmatch(v) for v in target.values()), 'target')
    session = record['session']
    _keys(session, ('id', 'name'))
    _require(isinstance(session['id'], str) and SESSION_ID.fullmatch(session['id']), 'session id')
    _require(isinstance(session['name'], str) and TEXT.fullmatch(session['name']), 'session name')
    files = record['files']
    _require(isinstance(files, list) and len(files) <= MAX_FILES, 'files')
    for item in files:
        _keys(item, ('path', 'role', 'sha256'))
        _require(item['role'] in ROLES, 'file role')
        _require(isinstance(item['path'], str) and FILE_PATTERNS[item['role']].fullmatch(item['path'])
                 and '..' not in item['path'], 'file path outside DesktopForge namespaces')
        _require(isinstance(item['sha256'], str) and HEX64.fullmatch(item['sha256']), 'file hash')
    _require(len({f['path'] for f in files}) == len(files), 'duplicate file path')
    entry = f'/usr/share/wayland-sessions/{session["id"]}.desktop'
    if record['state'] == 'completed':
        _require(any(f['path'] == entry and f['role'] == 'session-entry' for f in files),
                 'completed record must include its session entry')
    packages = record['packages']
    _keys(packages, ('installed', 'reused'))
    _require(isinstance(packages['installed'], list) and len(packages['installed']) <= MAX_PACKAGES, 'installed')
    for item in packages['installed']:
        _keys(item, ('name', 'evr', 'arch', 'repo', 'installtid', 'key_id'))
        _require(isinstance(item['name'], str) and NAME.fullmatch(item['name']), 'package name')
        _require(isinstance(item['evr'], str) and EVR.fullmatch(item['evr']), 'package evr')
        _require(isinstance(item['arch'], str) and re.fullmatch(r'[a-z0-9_]{1,20}', item['arch']), 'arch')
        _require(isinstance(item['repo'], str) and re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', item['repo']), 'repo')
        _require(item['installtid'] is None or (isinstance(item['installtid'], str)
                                                and item['installtid'].isdigit()), 'installtid')
        _require(item['key_id'] is None or (isinstance(item['key_id'], str)
                                            and re.fullmatch(r'[0-9a-f]{16}', item['key_id'])), 'key_id')
    reused = packages['reused']
    _require(isinstance(reused, list) and len(reused) <= MAX_PACKAGES
             and all(isinstance(n, str) and NAME.fullmatch(n) for n in reused), 'reused')
    return record


def build(*, install_id, recorded_at, state, producer, recipe_id, revision, plan_hash, action, uid,
          compositor, shell, session_id, session_name, files, installed, reused):
    record = {
        'schema': SCHEMA, 'install_id': install_id, 'recorded_at': recorded_at, 'state': state,
        'producer': producer, 'recipe': {'id': recipe_id, 'revision': revision}, 'plan_hash': plan_hash,
        'authorization': {'action': action, 'uid': uid},
        'target': {'compositor': compositor, 'shell': shell},
        'session': {'id': session_id, 'name': session_name},
        'files': sorted(files, key=lambda f: f['path']),
        'packages': {'installed': sorted(installed, key=lambda p: (p['name'], p['arch'])),
                     'reused': sorted(reused)},
        'journal': install_id + '.jsonl',
    }
    return validate(record)


def serialize(record):
    return (json.dumps(validate(record), indent=2, sort_keys=True) + '\n').encode()


def parse(data):
    try:
        return validate(json.loads(data))
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise RecordError(f'unreadable record: {exc}') from None
