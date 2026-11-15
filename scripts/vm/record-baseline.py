#!/usr/bin/python3
"""Read-only preservation evidence for the dedicated DesktopForge QEMU guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess


def describe(path):
    record = {'path': str(path)}
    try:
        metadata = path.lstat()
        record.update(mode=oct(stat.S_IMODE(metadata.st_mode)), uid=metadata.st_uid, gid=metadata.st_gid)
        if stat.S_ISLNK(metadata.st_mode):
            record.update(type='symlink', target=os.readlink(path))
        elif stat.S_ISREG(metadata.st_mode):
            with path.open('rb') as stream:
                record.update(type='file', sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
        else:
            record.update(type='other')
    except FileNotFoundError:
        record['type'] = 'absent'
    except OSError:
        record['type'] = 'unreadable'
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    if Path('/etc/hostname').read_text().strip() != 'desktopforge-fedora45':
        parser.error('Run only in the dedicated disposable VM')
    paths = {Path('/etc/gdm/custom.conf'), Path('/etc/sddm.conf'),
             Path('/etc/systemd/system/display-manager.service'),
             Path('/etc/systemd/system/default.target'),
             Path('/home/dfvm/.config/niri/config.kdl')}
    for directory, pattern in [('/usr/share/wayland-sessions', '*.desktop'),
                               ('/usr/share/xsessions', '*.desktop'),
                               ('/etc/sddm.conf.d', '*'),
                               ('/etc/systemd/user/niri.service.d', '*'),
                               ('/usr/lib/systemd/user/niri.service.d', '*')]:
        paths.update(Path(directory).glob(pattern))
    packages = subprocess.run(['rpm', '--query', '--noplugins', '--queryformat',
        '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n',
        'gnome-shell', 'gdm', 'niri', 'noctalia', 'python3-pyside6'],
        capture_output=True, text=True, timeout=30, env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/'})
    report = {'schema_version': 1, 'source_commit': args.source_commit,
              'hostname': platform.node(), 'architecture': platform.machine(),
              'os_release': Path('/etc/os-release').read_text(),
              'files': [describe(path) for path in sorted(paths)],
              'package_query': {'returncode': packages.returncode, 'output': packages.stdout,
                                'errors': packages.stderr},
              'notice': 'Static preservation evidence; this does not prove graphical login or lifecycle behavior.'}
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
