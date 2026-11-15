"""Bounded, local-only installed RPM evidence. No repository or transaction commands."""
from __future__ import annotations

from pathlib import Path
import subprocess

TRACKED_PACKAGES = ('hyprland', 'niri', 'noctalia', 'noctalia-shell', 'dms', 'ryoku-shell')
RPM_FORMAT = '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{VENDOR}\t%{SOURCERPM}\n'
LIMITATIONS = [
    'Installed RPM headers do not establish the originating repository or signature trust.',
    'Package presence and version do not establish executable ownership, compatibility or safe reuse.',
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


def inspect_packages(distribution: str | None, root: Path = Path('/'), *, runner=None) -> dict:
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
    return {'schema_version': 1, 'manager': 'rpm' if supported else None,
            'status': 'observed' if all(p['status'] != 'unknown' for p in packages) else 'incomplete',
            'packages': packages, 'limitations': list(LIMITATIONS)}


def package_assessment(inventory: dict, compositor: str, shell: str) -> dict:
    """Report observed candidates without satisfying compatibility requirements."""
    names = (compositor, {'ryoku': 'ryoku-shell', 'noctalia': 'noctalia', 'dms': 'dms'}[shell])
    observed = {row['name']: row for row in inventory.get('package_inventory', {}).get('packages', [])}
    packages = []
    for name in names:
        row = observed.get(name, {'name': name, 'status': 'unknown', 'records': [],
                                  'reason': 'No installed-package evidence is available.'})
        packages.append({**row, 'reuse': 'candidate_unverified' if row['status'] == 'installed' else 'unavailable'})
    return {'status': 'unverified', 'packages': packages,
            'limitations': list(LIMITATIONS)}
