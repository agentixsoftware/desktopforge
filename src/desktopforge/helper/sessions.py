"""Login-session entries: strict rendering and conservative inspection."""
import re

from .fsops import UnsafePath, read_small

SESSION_ID = re.compile(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+){0,7}')
FIELDS = ('Name', 'Comment', 'Exec', 'TryExec', 'Type', 'DesktopNames')
REQUIRED = ('Name', 'Exec', 'Type')
TEXT = re.compile(r'[^\x00-\x1f\x7f\\]{1,200}')
PATH = re.compile(r'/[A-Za-z0-9._/-]{1,200}')
# An absolute program plus up to eight plain arguments: no quotes, %-codes or shell syntax.
COMMAND = re.compile(r'/[A-Za-z0-9._/-]{1,200}(?: [A-Za-z0-9._/=-]{1,200}){0,8}')


class InvalidEntry(Exception):
    pass


def session_filename(session_id):
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise InvalidEntry('session ID must be in the desktopforge- namespace')
    return session_id + '.desktop'


def render(entry, allowed_commands):
    """Render a [Desktop Entry] from fixed recipe values. No field codes, no shell."""
    if not isinstance(entry, dict) or set(entry) - set(FIELDS) or not set(REQUIRED) <= set(entry):
        raise InvalidEntry('entry has missing or unsupported keys')
    for key, value in entry.items():
        if not isinstance(value, str) or not TEXT.fullmatch(value) or value != value.strip():
            raise InvalidEntry(f'{key} contains unsupported characters')
    if entry['Type'] != 'Application':
        raise InvalidEntry('Type must be Application')
    for key, shape in (('Exec', COMMAND), ('TryExec', PATH)):
        # The allowlist holds exact strings; arguments are part of what was reviewed.
        if key in entry and (not shape.fullmatch(entry[key]) or '..' in entry[key]
                             or entry[key] not in allowed_commands):
            raise InvalidEntry(f'{key} is not an allowlisted absolute command')
    lines = ['[Desktop Entry]'] + [f'{key}={entry[key]}' for key in FIELDS if key in entry]
    return ('\n'.join(lines) + '\n').encode()


def display_names(dir_fd, records):
    """Name= values of existing .desktop entries, from regular files only.

    Unreadable or non-regular entries yield None so callers treat them as unknown.
    """
    names = {}
    for record in records:
        if not record['name'].endswith('.desktop'):
            continue
        if record.get('type') != 'file':
            names[record['name']] = None
            continue
        try:
            text = read_small(dir_fd, record['name']).decode('utf-8', 'replace')
        except (OSError, UnsafePath):
            names[record['name']] = None
            continue
        section, value = None, None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('['):
                section = line
            elif section == '[Desktop Entry]' and '=' in line:
                key, _, rest = line.partition('=')
                if key.strip() == 'Name':  # spaces around '=' are allowed; Name[xx] is not Name
                    value = rest.strip()
                    break
        names[record['name']] = value
    return names
