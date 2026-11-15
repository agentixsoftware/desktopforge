"""Deterministic fingerprints of the state a reviewed plan depends on."""
import hashlib
import json
import os

from .fsops import UnsafePath, check_name, describe

MAX_ENTRIES = 512


def directory_evidence(dir_fd):
    """Sorted, non-following records for every entry of one directory."""
    # List through a fresh open of the same directory. Reusing a long-lived
    # handle can miss entries created after it was opened (observed on btrfs).
    listing_fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        names = sorted(os.listdir(listing_fd))
    finally:
        os.close(listing_fd)
    if len(names) > MAX_ENTRIES:
        raise UnsafePath('directory has too many entries to fingerprint')
    records = []
    for name in names:
        try:
            check_name(name)
        except UnsafePath:
            records.append({'name': name, 'type': 'unexpected-name'})
            continue
        records.append(describe(dir_fd, name))
    return records


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def fingerprint(evidence):
    """SHA-256 of canonical JSON; any change in recorded evidence changes it."""
    return hashlib.sha256(canonical(evidence).encode()).hexdigest()
