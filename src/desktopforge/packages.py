"""Bounded, local-only installed RPM evidence. No repository or transaction commands."""
from __future__ import annotations

from pathlib import Path
import subprocess

TRACKED_PACKAGES = ('hyprland', 'niri', 'noctalia', 'noctalia-shell', 'dms', 'ryoku-shell')
RPM_FORMAT = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{VENDOR}\t%{SOURCERPM}\n'
LIMITATIONS = [
    'Installed RPM headers do not establish the originating repository or signature trust.',
    'Package presence and version do not establish compatibility or safe reuse.',
    'No repository metadata, dependency solver, package transaction or executable version command is run.',
    'Arch/CachyOS package inspection is not implemented; their package state remains unknown.',
]


def parse_rpm_records(text: str, name: str) -> list[dict]:
    """Reject ambiguous output instead of treating query failures as package absence."""
    records = []
    if not text or len(text) > 65536:
        raise ValueError('Empty or oversized RPM response')
    for line in text.splitlines():
        fields = line.split('\t')
        if (len(fields) != 7 or fields[0] != name or not fields[1].isdigit()
                or any(not field or len(field) > 4096 or any(ord(c) < 32 for c in field) for field in fields)
                or any(field == '(none)' for field in fields[2:5])):
            raise ValueError('Malformed RPM response')
        _, epoch, version, release, architecture, vendor, source = fields
        records.append({'epoch': int(epoch), 'version': version, 'release': release,
                        'architecture': architecture,
                        'vendor': None if vendor == '(none)' else vendor,
                        'source_rpm': None if source == '(none)' else source,
                        'origin_repository': None, 'signature_verification': 'not_performed'})
    return sorted(records, key=lambda row: (row['architecture'], row['epoch'], row['version'], row['release']))


def query_file_owners(path: str, *, runner=None) -> dict:
    """Ask the local RPM database who owns one discovered absolute file path."""
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
            or any(part in ('.', '..') for part in path.split('/'))
            or any(ord(char) < 32 for char in path) or len(path) > 4096):
        return {'path': path if isinstance(path, str) else None, 'status': 'unknown',
                'owners': [], 'reason': 'Executable path is not a safe absolute path.'}
    run = subprocess.run if runner is None else runner
    try:
        result = run(['/usr/bin/rpm', '--query', '--whatprovides', '--qf', '%{NAME}\\n', path],
                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3,
                     shell=False, cwd='/', env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/'})
        if result.returncode == 0 and not result.stderr:
            owners = result.stdout.splitlines()
            if owners and all(1 <= len(name) <= 256 and all(c.isalnum() or c in '._+-' for c in name)
                              for name in owners):
                return {'path': path, 'status': 'owned', 'owners': sorted(set(owners)),
                        'reason': 'Path is listed by the local RPM database.'}
        elif result.returncode == 1 and not result.stderr and not result.stdout.strip():
            return {'path': path, 'status': 'unowned', 'owners': [],
                    'reason': 'No owner was reported for this path by the local RPM database.'}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass
    return {'path': path, 'status': 'unknown', 'owners': [],
            'reason': 'RPM file-owner query failed or returned ambiguous diagnostics.'}


def inspect_packages(distribution: str | None, root: Path = Path('/'), *, runner=None,
                     executables: dict | None = None) -> dict:
    """Query a fixed allowlist only on the live Fedora root.

    Fixture roots never access the host RPM database. Tests may explicitly inject
    a runner implementing subprocess.run's interface, without spawning commands.
    No caller-controlled paths, package names or environment reach RPM.
    """
    supported = distribution == 'fedora'
    enabled = supported and (root == Path('/') or runner is not None)
    run = subprocess.run if runner is None else runner
    packages = []
    for name in sorted(TRACKED_PACKAGES):
        record = {'name': name, 'status': 'unknown', 'records': [],
                  'reason': 'Package inspection is unavailable for this distribution or fixture root.'}
        if enabled:
            try:
                result = run(['/usr/bin/rpm', '--query', '--noplugins', '--queryformat', RPM_FORMAT, name],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3,
                             shell=False, cwd='/', env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/'})
                if result.returncode == 0 and not result.stderr:
                    record.update(status='installed', records=parse_rpm_records(result.stdout, name),
                                  reason='Observed in the local RPM database; safe reuse is unverified.')
                elif (result.returncode == 1 and not result.stderr
                      and result.stdout.strip() == f'package {name} is not installed'):
                    record.update(status='not_installed', reason='Not present under this exact RPM package name.')
                else:
                    record['reason'] = 'RPM query failed or returned ambiguous diagnostics.'
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
                record['reason'] = 'RPM query unavailable, timed out or returned malformed evidence.'
        packages.append(record)
    paths = []
    if enabled and executables:
        for component, evidence in sorted(executables.items()):
            if isinstance(evidence, dict) and evidence.get('found'):
                path = evidence.get('path')
                if path:
                    paths.append({'component': component, **query_file_owners(path, runner=run)})
                else:
                    paths.append({'component': component, 'path': None, 'status': 'unknown',
                                  'owners': [], 'reason': 'Executable discovery did not provide its resolved path.'})
    return {'schema_version': 1, 'manager': 'rpm' if supported else None,
            'status': 'observed' if all(p['status'] != 'unknown' for p in packages) else 'incomplete',
            'packages': packages, 'executable_ownership': paths,
            'limitations': list(LIMITATIONS)}


def package_assessment(inventory: dict, compositor: str, shell: str) -> dict:
    """Report observed candidates without satisfying compatibility requirements."""
    names = (compositor, {'ryoku': 'ryoku-shell', 'noctalia': 'noctalia', 'dms': 'dms'}[shell])
    observed = {row['name']: row for row in inventory.get('package_inventory', {}).get('packages', [])}
    packages = []
    for name in names:
        row = observed.get(name, {'name': name, 'status': 'unknown', 'records': [],
                                  'reason': 'No installed-package evidence is available.'})
        component = compositor if name == compositor else f'shell:{shell}'
        owners = next((item for item in inventory.get('package_inventory', {}).get('executable_ownership', [])
                       if item.get('component') == component), None)
        ownership = {'status': 'unknown', 'path': None, 'owners': [],
                     'reason': 'No RPM executable-owner evidence is available.'} if owners is None else owners
        packages.append({**row, 'executable_ownership': ownership,
                         'owner_matches_package': name in ownership.get('owners', []),
                         'reuse': 'candidate_unverified' if row['status'] == 'installed' else 'unavailable'})
    return {'status': 'unverified', 'packages': packages,
            'limitations': list(LIMITATIONS)}
