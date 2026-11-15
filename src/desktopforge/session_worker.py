"""Noctalia readiness handoff within the launcher's transient cgroup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('token')
    args = parser.parse_args(argv)
    if not re.fullmatch('[0-9a-f]{32}', args.token):
        parser.error('Invalid attempt token')
    from .launcher_runtime import _open_directory
    directory = _open_directory(args.directory)
    try:
        try:
            os.stat('shell.json', dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Shell readiness has already been published')
        pending = f'shell-{args.token}.pending'
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'w') as stream:
            try:
                result = subprocess.run(['/usr/bin/noctalia', '--daemon'], shell=False, timeout=30)
                status = {'token': args.token, 'ready': result.returncode == 0, 'exit_code': result.returncode}
                if status['ready']:
                    # Open a useful surface on this compositor's own IPC socket.
                    # The inherited WAYLAND_DISPLAY was set by this Niri instance.
                    try:
                        opened = subprocess.run(['/usr/bin/noctalia', 'msg', 'panel-toggle', 'launcher'],
                                                shell=False, timeout=5)
                        status['launcher_opened'] = opened.returncode == 0
                    except (OSError, subprocess.TimeoutExpired):
                        status['launcher_opened'] = False
            except (OSError, subprocess.TimeoutExpired):
                status = {'token': args.token, 'ready': False, 'exit_code': 1}
            json.dump(status, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, 'shell.json', src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.unlink(pending, dir_fd=directory)
        os.fsync(directory)
        return 0 if status['ready'] else 1
    finally:
        os.close(directory)


if __name__ == '__main__':
    raise SystemExit(main())
