"""Append-only, fsync'd JSON-lines journal written before each state change."""
import json
import os
import time
import uuid

from .fsops import check_name


class JournalError(Exception):
    """The journal could not be durably written; stop before further changes."""


class Journal:
    def __init__(self, dir_fd, install_id=None, clock=time.time):
        self.install_id = install_id or uuid.uuid4().hex
        self.name = check_name(f'{self.install_id}.jsonl')
        self.clock, self.sequence = clock, 0
        try:
            self.fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
                              | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
            os.fsync(dir_fd)
        except OSError as exc:
            raise JournalError(f'cannot create journal: {exc.strerror}') from exc

    def record(self, event, **fields):
        self.sequence += 1
        entry = {'seq': self.sequence, 'time': round(self.clock(), 3),
                 'install_id': self.install_id, 'event': event, **fields}
        line = (json.dumps(entry, sort_keys=True) + '\n').encode()
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(self.fd, view):]
            os.fsync(self.fd)
        except OSError as exc:
            raise JournalError(f'journal write failed: {exc.strerror}') from exc

    def close(self):
        os.close(self.fd)
