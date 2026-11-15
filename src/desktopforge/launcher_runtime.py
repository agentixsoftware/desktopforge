"""Internal Linux launcher primitives, not an installed desktop session launcher.

Unlike the planner/model this module performs OS operations when explicitly called:
private runtime files, advisory locks, and owned child processes. Production CLI
commands never call it. Commands may come only from trusted Python code, never
recipe fields. No systemd/D-Bus/environment publication adapter exists yet.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
from typing import Mapping, Sequence
import uuid


class LauncherError(RuntimeError):
    """Runtime prerequisites or ownership checks failed."""


class RecoveryRequired(LauncherError):
    """An unfinished attempt or uncertain runtime object needs explicit review."""


def _private(fd: int, *, directory: bool) -> os.stat_result:
    info = os.fstat(fd)
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct_type or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise LauncherError('Runtime object must be private and owned by the current user')
    if not directory and info.st_nlink != 1:
        raise LauncherError('Runtime file must not be hard-linked')
    return info


def _open_directory(path: Path, *, private: bool = True) -> int:
    if not path.is_absolute() or '..' in path.parts:
        raise LauncherError('Runtime directory must be absolute without traversal')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if private:
            _private(fd, directory=True)
        else:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                raise LauncherError('Config base must be owned by the current user and not writable by others')
        return fd
    except BaseException:
        os.close(fd)
        raise


class SessionLease:
    """One cooperating DesktopForge attempt per user, shared by all session IDs.

    The lock inode persists. A separate fsynced attempt marker survives a crash.
    Exiting this context releases descriptors but NEVER removes an unfinished
    marker. clean_after_verified_shutdown is an explicit caller assertion and is
    not a production-ready session/descendant verifier.
    """

    def __init__(self, runtime_dir: Path, session_id: str):
        import re
        if not re.fullmatch(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+)*', session_id):
            raise LauncherError('Invalid session ID')
        self.runtime_dir = runtime_dir
        self.session_id = session_id
        self.attempt_id = uuid.uuid4().hex
        self._directory: int | None = None
        self._lock: int | None = None
        self._marker_identity: tuple[int, int] | None = None
        self._marker_payload: bytes | None = None
        self._entered = False

    def __enter__(self) -> SessionLease:
        if self._entered:
            raise LauncherError('A lease object cannot be reused')
        self._entered = True
        root_fd = _open_directory(self.runtime_dir)
        try:
            try:
                os.mkdir('desktopforge', mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            self._directory = os.open('desktopforge', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                      dir_fd=root_fd)
            _private(self._directory, directory=True)
            self._lock = os.open('session.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                 0o600, dir_fd=self._directory)
            _private(self._lock, directory=False)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LauncherError('Another DesktopForge session attempt holds the user lock') from exc
            try:
                marker = os.open('attempt.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=self._directory)
            except FileExistsError as exc:
                raise RecoveryRequired('An unfinished attempt marker exists; automatic takeover is refused') from exc
            try:
                info = _private(marker, directory=False)
                self._marker_identity = (info.st_dev, info.st_ino)
                payload = json.dumps({'schema_version': 1, 'session_id': self.session_id,
                                      'attempt_id': self.attempt_id, 'launcher_pid': os.getpid()}, sort_keys=True).encode()
                self._marker_payload = payload
                with os.fdopen(marker, 'wb', closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(marker)
                os.fsync(self._directory)
                os.fsync(root_fd)
            finally:
                os.close(marker)
            return self
        except BaseException:
            self._close()
            raise
        finally:
            os.close(root_fd)

    def clean_after_verified_shutdown(self) -> None:
        """Caller must prove all managed work stopped; no such production probe exists."""
        if self._directory is None or self._lock is None or self._marker_identity is None:
            raise LauncherError('No active attempt marker is owned')
        marker = None
        try:
            marker = os.open('attempt.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=self._directory)
            info = os.fstat(marker)
            if (info.st_dev, info.st_ino) != self._marker_identity:
                raise RecoveryRequired('Attempt marker identity changed; cleanup refused')
            try:
                _private(marker, directory=False)
            except LauncherError as exc:
                raise RecoveryRequired('Attempt marker permissions changed; cleanup refused') from exc
            if os.pread(marker, 4097, 0) != self._marker_payload:
                raise RecoveryRequired('Attempt marker content changed; cleanup refused')
        except OSError as exc:
            raise RecoveryRequired('Attempt marker is unavailable; cleanup refused') from exc
        finally:
            if marker is not None:
                os.close(marker)
        os.unlink('attempt.json', dir_fd=self._directory)
        os.fsync(self._directory)
        self._marker_identity = None
        self._marker_payload = None

    def _close(self) -> None:
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None
        if self._directory is not None:
            os.close(self._directory)
            self._directory = None

    def __exit__(self, *args: object) -> None:
        self._close()


def child_environment(parent: Mapping[str, str], config_path: Path) -> dict[str, str]:
    """Copy explicit child environment; do not publish or change parent/manager state."""
    if not config_path.is_absolute() or '..' in config_path.parts or '\x00' in str(config_path):
        raise LauncherError('Config path must be absolute without traversal')
    return {**parent, 'NIRI_CONFIG': str(config_path)}



class PinnedConfig:
    """Pin an existing private config inode, not its semantic correctness.

    No directory or file is created. A child inherits this read-only descriptor
    so replacing the pathname after validation cannot substitute another inode.
    Includes and spawn commands still require separate trusted config generation.
    """

    def __init__(self, config_home: Path, session_id: str):
        import re
        if not re.fullmatch(r'desktopforge-[a-z0-9]+(?:-[a-z0-9]+)*', session_id):
            raise LauncherError('Invalid session ID')
        self.config_home = config_home
        self.session_id = session_id
        self._fd: int | None = None

    def __enter__(self) -> PinnedConfig:
        if self._fd is not None:
            raise LauncherError('Config is already pinned')
        directory = _open_directory(self.config_home, private=False)
        try:
            for name in ('desktopforge', 'sessions', self.session_id):
                next_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=directory)
                os.close(directory)
                directory = next_fd
                _private(directory, directory=True)
            fd = os.open('niri.kdl', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=directory)
            try:
                _private(fd, directory=False)
            except BaseException:
                os.close(fd)
                raise
            self._fd = fd
            return self
        finally:
            os.close(directory)

    def fileno(self) -> int:
        if self._fd is None:
            raise LauncherError('Config is not pinned')
        return self._fd

    def environment(self, parent: Mapping[str, str]) -> dict[str, str]:
        return {**parent, 'NIRI_CONFIG': f'/proc/self/fd/{self.fileno()}'}

    def __exit__(self, *args: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def _timeout(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise LauncherError('Timeout must be a positive finite number')


class OwnedChild:
    """Control only a directly spawned child via pidfd, never PID/name heuristics.

    This does not supervise descendants or systemd services. It must not be used
    to assert that a compositor session has stopped or is ready for guard release.
    """

    def __init__(self, process: subprocess.Popen, pidfd: int):
        self._process = process
        self._pidfd: int | None = pidfd

    @classmethod
    def start(cls, argv: Sequence[str], environment: Mapping[str, str],
              *, config: PinnedConfig | None = None) -> OwnedChild:
        if (isinstance(argv, (str, bytes)) or not argv or not all(isinstance(arg, str) and '\x00' not in arg for arg in argv)
                or not Path(argv[0]).is_absolute()):
            raise LauncherError('Trusted child argv must start with an absolute executable')
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise LauncherError('Linux pidfd support is required; no PID fallback is allowed')
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise LauncherError('Custom SIGCHLD handling is incompatible with owned child supervision')
        # Probe kernel support before creating a child. Keep ownership private and
        # do not poll/wait/reap the child before acquiring its stable process handle.
        probe = os.pidfd_open(os.getpid())
        os.close(probe)
        child_env = dict(environment) if config is None else config.environment(environment)
        descriptors = () if config is None else (config.fileno(),)
        process = subprocess.Popen(tuple(argv), env=child_env, shell=False, close_fds=True,
                                   pass_fds=descriptors,
                                   start_new_session=True, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            pidfd = os.pidfd_open(process.pid)
        except BaseException:
            # With default SIGCHLD disposition and no poll/wait, even an exited
            # child retains its PID as a zombie until this owner reaps it.
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise
        return cls(process, pidfd)

    @property
    def pid(self) -> int:
        return self._process.pid

    def wait(self, timeout: float) -> int:
        _timeout(timeout)
        return self._process.wait(timeout=timeout)

    def _signal(self, number: int) -> None:
        if self._pidfd is None:
            raise LauncherError('Child handle is closed')
        try:
            signal.pidfd_send_signal(self._pidfd, number)
        except ProcessLookupError:
            pass  # The bound child is gone; never try its numeric PID.

    def stop(self, *, grace: float = 2, kill_timeout: float = 2) -> int:
        _timeout(grace)
        _timeout(kill_timeout)
        self._signal(signal.SIGTERM)
        try:
            return self.wait(grace)
        except subprocess.TimeoutExpired:
            self._signal(signal.SIGKILL)
            try:
                return self.wait(kill_timeout)
            except subprocess.TimeoutExpired as exc:
                raise RecoveryRequired('Owned child stop is unconfirmed') from exc

    def close(self) -> None:
        if self._pidfd is not None:
            if self._process.poll() is None:
                raise RecoveryRequired('Cannot discard a handle to a running child')
            os.close(self._pidfd)
            self._pidfd = None
