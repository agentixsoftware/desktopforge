"""Filesystem operations through directory handles; never follow symlinks."""
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
MAX_HASH_BYTES = 4 * 1024 * 1024


class UnsafePath(Exception):
    """A path component is a symlink, wrongly owned, writable by others or malformed."""


class Conflict(Exception):
    """The destination already exists; it is never overwritten."""


def check_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in ('.', '..'):
        raise UnsafePath(f'unsafe path component {name!r}')
    return name


def _check_dir(fd, owners, what):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafePath(f'{what} is not a directory')
    if info.st_uid not in owners:
        raise UnsafePath(f'{what} has an untrusted owner')
    if info.st_mode & 0o022:
        raise UnsafePath(f'{what} is writable by group or others')


def _open_dir(name, dir_fd):
    try:
        return os.open(name, DIR_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        # ELOOP/ENOTDIR: symlink or non-directory in place of a directory.
        raise UnsafePath(f'cannot safely open {name!r}: {exc.strerror}') from exc


def open_anchor(path, expected_uid=0):
    """Open an absolute directory, checking every component from '/'.

    Ancestors must be owned by root or expected_uid and not writable by others;
    the final directory must be owned by expected_uid.
    """
    parts = PurePosixPath(path).parts
    if not parts or parts[0] != '/' or str(PurePosixPath(path)) != path:
        raise UnsafePath('anchor must be a normalized absolute path')
    fd = os.open('/', DIR_FLAGS)
    try:
        _check_dir(fd, {0}, '/')
        for part in parts[1:]:
            next_fd = _open_dir(check_name(part), fd)
            os.close(fd)
            fd = next_fd
            _check_dir(fd, {0, expected_uid}, part)
        _check_dir(fd, {expected_uid}, path)
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_child(dir_fd, name, expected_uid=0, create_mode=None):
    """Open (optionally create) a trusted subdirectory beneath a handle."""
    check_name(name)
    if create_mode is not None:
        try:
            os.mkdir(name, create_mode, dir_fd=dir_fd)
        except FileExistsError:
            pass
    fd = _open_dir(name, dir_fd)
    try:
        _check_dir(fd, {expected_uid}, name)
    except BaseException:
        os.close(fd)
        raise
    return fd


def create_file(dir_fd, name, data, mode=0o644):
    """Create a new file exclusively, write, fsync file and directory; return SHA-256."""
    check_name(name)
    if mode & ~0o644:
        raise UnsafePath('requested mode exceeds 0644')
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     mode, dir_fd=dir_fd)
    except FileExistsError as exc:
        raise Conflict(f'{name} already exists') from exc
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)
    return hashlib.sha256(data).hexdigest()


def describe(dir_fd, name):
    """Evidence record for one directory entry, without following symlinks."""
    check_name(name)
    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    record = {'name': name, 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    if stat.S_ISLNK(info.st_mode):
        record.update(type='symlink', target=os.readlink(name, dir_fd=dir_fd))
    elif stat.S_ISREG(info.st_mode):
        record.update(type='file', size=info.st_size)
        if info.st_size <= MAX_HASH_BYTES:
            record['sha256'] = hash_file(dir_fd, name)
    elif stat.S_ISDIR(info.st_mode):
        record['type'] = 'directory'
    else:
        record['type'] = 'other'
    return record


def hash_file(dir_fd, name):
    fd = os.open(check_name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1 << 16):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def read_small(dir_fd, name, limit=64 * 1024):
    """Read a regular file beneath a handle without following symlinks; bounded."""
    fd = os.open(check_name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafePath(f'{name} is not a regular file')
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise UnsafePath(f'{name} is larger than {limit} bytes')
    return data


class Mismatch(Exception):
    """The file is not the one that was recorded; it is kept."""


def remove_file(dir_fd, name, sha256):
    """Remove a regular file only if it still has the recorded content.

    The content is hashed through a no-follow handle and the name is checked to
    still refer to that same inode immediately before unlinking.
    """
    check_name(name)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        raise Mismatch(f'{name} is missing') from exc
    except OSError as exc:
        raise Mismatch(f'{name} cannot be opened safely: {exc.strerror}') from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Mismatch(f'{name} is not a regular file')
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1 << 16):
            digest.update(chunk)
        if digest.hexdigest() != sha256:
            raise Mismatch(f'{name} was modified')
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise Mismatch(f'{name} was replaced')
        os.unlink(name, dir_fd=dir_fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)
