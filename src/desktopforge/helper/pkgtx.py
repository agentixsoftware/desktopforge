"""Fixed DNF5/RPM adapter: resolve, install and record package transactions.

Package names and repository IDs come from reviewed recipes and are validated
again here. The argv is fixed; nothing is passed through a shell. Running the
commands with the right privileges is the caller's job (see `runner`).
Resolution output is parsed strictly and anything unexpected fails closed.
"""
import re

PACKAGE = re.compile(r'[a-z0-9][a-z0-9+._-]{0,99}')
REPOSITORY = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}')
KEY_ID = re.compile(r'[0-9a-f]{16}')
DNF5 = '/usr/bin/dnf5'
RPM = '/usr/bin/rpm'
ALLOWED_SECTIONS = {'Installing:', 'Installing dependencies:'}
KNOWN_SECTIONS = ALLOWED_SECTIONS | {
    'Installing weak dependencies:', 'Upgrading:', 'Downgrading:', 'Reinstalling:', 'Replacing:',
    'Removing:', 'Removing dependent packages:', 'Removing unused dependencies:',
    'Installing group/module packages:', 'Installing groups:', 'Installing environmental groups:'}
ROW = re.compile(r' (?P<name>\S+)\s+(?P<arch>\S+)\s+(?P<evr>\d+:\S+)\s+(?P<repo>\S+)\s+[\d.]+\s+\S+')
RPM_QUERY = ('%{NAME}\\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\t%{ARCH}\\t%{INSTALLTID}\\t'
             '%|RSAHEADER?{%{RSAHEADER:pgpsig}}:{none}|\\n')


class PackageError(Exception):
    pass


def _check(packages, repositories):
    if not packages or not all(isinstance(p, str) and PACKAGE.fullmatch(p) for p in packages):
        raise PackageError('invalid package name in recipe')
    if not repositories or not all(isinstance(r, str) and REPOSITORY.fullmatch(r) for r in repositories):
        raise PackageError('invalid repository ID in recipe')


def dnf5_argv(packages, repositories, simulate):
    """The only DNF5 command line this adapter produces."""
    _check(packages, repositories)
    return [DNF5, 'install', '--assumeno' if simulate else '--assumeyes',
            '--setopt=install_weak_deps=False', '--setopt=gpgcheck=True',
            '--setopt=localpkg_gpgcheck=True', *[f'--repo={r}' for r in repositories],
            '--', *packages]


def parse_resolution(text):
    """Parse DNF5's transaction table into (to_install, blockers).

    to_install: sorted list of {name, arch, evr, repo}. Any section other than
    plain installs, any warning, and any unparseable table line is a blocker or
    an error; nothing unexpected is ignored once the table has started.
    """
    lines = text.splitlines()
    blockers = []
    for line in lines:
        if line.startswith('Warning:'):
            if 'offline transaction' in line and 'invalidated' in line:
                blockers.append('A pending offline system update would be cancelled by this install; '
                                'apply or discard it first')
            else:
                blockers.append('Package manager warning: ' + line[len('Warning:'):].strip()[:200])
    if any(line.strip() == 'Nothing to do.' for line in lines):
        return [], blockers
    try:
        header = next(i for i, line in enumerate(lines)
                      if line.startswith('Package ') and 'Repository' in line)
        summary = next(i for i, line in enumerate(lines) if line.startswith('Transaction Summary:'))
    except StopIteration:
        raise PackageError('package resolution did not produce a transaction table') from None
    if summary < header:
        raise PackageError('malformed transaction table')
    rows, section = [], None
    for line in lines[header + 1:summary]:
        if not line.strip():
            continue
        if not line.startswith(' '):
            if line not in KNOWN_SECTIONS:
                raise PackageError(f'unrecognized transaction section {line[:80]!r}')
            section = line
            if line not in ALLOWED_SECTIONS:
                blockers.append(f'Transaction would include "{line[:-1]}"; only new installs are allowed')
            continue
        if section is None:
            raise PackageError('transaction row outside a section')
        if line.lstrip().lower().startswith('replacing'):
            blockers.append('Transaction would replace an installed package')
            continue
        match = ROW.fullmatch(line.rstrip())
        if not match:
            raise PackageError(f'unparseable transaction row {line.strip()[:80]!r}')
        if section in ALLOWED_SECTIONS:
            rows.append(match.groupdict())
    return sorted(rows, key=lambda r: (r['name'], r['arch'])), blockers


def resolve(packages, repositories, runner):
    """Simulate the install. Returns (to_install, blockers)."""
    code, output = runner(dnf5_argv(packages, repositories, simulate=True))
    try:
        to_install, blockers = parse_resolution(output)
    except PackageError as exc:
        tail = ' | '.join(output.strip().splitlines()[-3:])[-300:]
        raise PackageError(f'{exc} (status {code}; output: {tail or "none"})') from None
    if code not in (0, 1):
        raise PackageError(f'package resolution failed with status {code}')
    allowed = set(repositories)
    for row in to_install:
        if row['repo'] not in allowed:
            blockers.append(f'{row["name"]} would come from repository {row["repo"]}')
    return to_install, blockers


def parse_rpm_query(text):
    records, missing = {}, []
    for line in text.splitlines():
        if line.startswith('package ') and line.endswith(' is not installed'):
            missing.append(line[len('package '):-len(' is not installed')])
            continue
        parts = line.split('\t')
        if len(parts) != 5:
            raise PackageError('unexpected rpm query output')
        name, evr, arch, tid, signature = parts
        key = re.search(r'Key ID ([0-9a-f]{16})', signature)
        records.setdefault(name, []).append({
            'name': name, 'evr': evr, 'arch': arch, 'installtid': tid,
            'key_id': key.group(1) if key else None})
    return records, missing


def query_installed(names, runner):
    if not names or not all(PACKAGE.fullmatch(n) for n in names):
        raise PackageError('invalid package name')
    _code, output = runner([RPM, '--query', '--queryformat', RPM_QUERY, '--', *names])
    return parse_rpm_query(output)


def verify_installed(expected, runner, signer):
    """Every resolved package is installed at the resolved version, signed by signer."""
    if not KEY_ID.fullmatch(signer or ''):
        raise PackageError('recipe has no valid signing key ID')
    records, missing = query_installed(sorted({r['name'] for r in expected}), runner)
    problems = [f'{name} is not installed' for name in missing]
    for row in expected:
        found = [r for r in records.get(row['name'], []) if r['arch'] == row['arch']]
        if not any(r['evr'] == row['evr'] for r in found):
            problems.append(f'{row["name"]} is not installed at {row["evr"]}')
        elif not any(r['evr'] == row['evr'] and r['key_id'] == signer for r in found):
            problems.append(f'{row["name"]} is not signed by key {signer}')
    return records, problems


def install(packages, repositories, expected, runner, signer):
    """Re-resolve, require the reviewed set, install, then verify.

    Returns (records, output). Raises PackageError with what is known on failure.
    """
    current, blockers = resolve(packages, repositories, runner)
    if blockers or current != expected:
        raise PackageError('package resolution changed since preview; nothing was installed')
    if not expected:
        return {}, 'Nothing to do.'
    code, output = runner(dnf5_argv(packages, repositories, simulate=False))
    records, problems = verify_installed(expected, runner, signer)
    if code != 0 or problems:
        raise PackageError(f'package transaction status {code}; ' + ('; '.join(problems) or 'see journal'))
    return records, output
