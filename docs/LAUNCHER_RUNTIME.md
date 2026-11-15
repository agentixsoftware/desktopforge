# Native launcher runtime foundation

Status: **internal, partial implementation; no production launch command**.
`launcher_runtime.py` implements real Linux operations. It is separate from the
pure lifecycle model and is never called by `detect`, `list` or `plan`. No session
entry, launcher executable, service or configuration has been installed.

The tests execute trusted Python fixture children and use temporary private
runtime/config directories. They do not execute Niri, Noctalia, Ryoku or systemd.

## Per-user session lease

`SessionLease` opens an explicitly supplied private runtime directory owned by
the execution UID. It creates only a private `desktopforge` subdirectory, a
persistent `session.lock` inode and a private `attempt.json` marker there.
Components are opened relative to directory descriptors with no symlink
following; directories/files must meet ownership and permission requirements.
Lock files must be regular and not hard-linked. Unsafe paths are rejected, never
repaired or chmodded automatically.

A nonblocking `flock` permits one cooperating DesktopForge attempt per runtime
directory across all session IDs. The lock inode is never unlinked during normal
cleanup; recreating lock files could otherwise split cooperating contenders
across different inodes. This does not exclude an unmanaged compositor or a
launcher using a different runtime directory. A production adapter still needs
an authenticated per-user runtime path and unmanaged-session checks.

A newly created attempt marker is fsynced before a caller may start work. It
contains a schema version, session ID, random attempt token and launcher PID.
It never records commands, environment snapshots or tokens from the login
session. The PID is diagnostic; no stale PID is used to signal or adopt a process.

A context exit closes descriptors and releases the lock but does not erase an
unfinished marker. A crashed process therefore leaves a marker that blocks a
later attempt from assuming cleanup succeeded. This persists only while the
runtime directory survives; it is not a reboot-persistent journal.

`clean_after_verified_shutdown()` is a narrow caller assertion, not a verifier.
It compares the owned marker inode, permissions and exact content before removal
and fsyncs the directory. Replaced/edited state is preserved for manual review.
A future full-session adapter must prove all managed work has stopped before
calling it; direct-child exit is insufficient for a desktop session. There is no
automatic recovery/delete-stale-marker command.

## Read-only isolated config descriptor

`PinnedConfig` opens an existing config under
`<config-home>/desktopforge/sessions/<session-id>/niri.kdl`. It creates nothing.
The config base must be owned by the execution UID and not writable by other
users; the dedicated namespace directories and final regular file must be
private. Symlinks, traversal, special files, hard-linked configs and missing
paths are refused.

The direct child inherits only the config descriptor via `pass_fds`, and its
`NIRI_CONFIG` points to `/proc/self/fd/<fd>`. Replacing the original pathname after
opening cannot substitute another inode for that child. This pins an inode, not
immutable bytes: in-place edits, config semantics and includes still require
separate trusted generation/validation. No content is interpreted by this helper.

**This descriptor technique is not wired to `niri-session` or a systemd service.**
A service started separately by the user manager would not inherit the direct
child's descriptor. Production handoff and environment scope remain unresolved;
calling the installed session wrapper with this config is not supported.

`child_environment` also supplies a simpler copied child-only override for trusted
callers. Neither helper changes `os.environ`, the systemd user-manager environment
or D-Bus activation state. These helpers cannot prevent an explicitly executed
program from changing those things itself, so production command selection must
remain constrained to reviewed launcher code.

## Owned direct child

`OwnedChild` accepts an explicit argv from trusted Python code and an explicit
environment mapping. This is not a recipe operation, privileged-helper API or CLI
command. It invokes no shell expansion. The executable path must be absolute;
file descriptors are closed except for an explicitly pinned config, and the
child starts in a new process session with test-oriented standard streams sent
to `/dev/null`.

The implementation probes Linux pidfd support before starting and obtains a
pidfd immediately after spawning. Signals go through `pidfd_send_signal`, tying
control to that process identity rather than a later reuse of its numeric PID.
There is no process-name matching or signaling fallback for ordinary control.
A failure to acquire the handle immediately after spawn kills and reaps only the
new unreaped child under the required default SIGCHLD disposition. Custom SIGCHLD
handlers are rejected.

`stop()` sends TERM, waits for a bounded grace period, then sends KILL if needed
and waits for confirmation. Invalid timeouts are rejected before any signal.
Unconfirmed stop raises a recovery error. A running handle cannot be discarded;
after exit it can be closed idempotently. Standard-stream/logging and TTY policy
still need review for a real desktop-session adapter.

This primitive supervises **only the direct child**. It does not stop escaped
children, user services or a compositor's entire cgroup, and it does not establish
compositor/shell readiness. Starting a new process session does not solve those
lifecycle requirements. No successful child exit is represented as a successful
desktop installation or full session shutdown.

## Remaining work before a production launcher

The installed `niri-session` inspected on the reference host imports the login
environment, starts the shared `niri.service`, and later starts a shared shutdown
target. Its global/user drop-ins can run other shell bootstrap code. The native
primitives do not make that path isolated merely by wrapping it in a lock.

A concrete adapter must still resolve:

1. Complete isolated config generation and a descriptor/path handoff that works
   with the selected compositor/service startup strategy.
2. Environment and D-Bus ownership without broad imports or unprovable
   compare-and-restore claims against an uncoordinated shared manager.
3. Attempt-correlated readiness and full descendant/service shutdown verification,
   using reviewed systemd/cgroup boundaries rather than guessed PIDs.
4. Signal/timeout orchestration, partial-operation failure handling and recovery
   across crashes/restarts, including state outside a volatile runtime directory.
5. Effective hook conflicts and disposable VM login/logout testing, followed by
   real GPU validation. Host installation/startup still needs separate approval.

The filesystem operations are descriptor-anchored checks in a private user
namespace. They are not a privileged helper or a complete defense against
arbitrary concurrent tampering by processes with the same UID.

## Verification and references

Tests cover real cross-process contention, a launcher exiting without cleanup,
unchanged stale/tampered markers, symlink/FIFO/hardlink rejection, pinned config
inode replacement, child environment isolation, child exit, TERM/KILL escalation,
post-spawn handle failure, distinct-child ownership and read-only CLI separation.

Python documents the underlying
[flock interface](https://docs.python.org/3/library/fcntl.html#fcntl.flock),
[pidfd handles](https://docs.python.org/3/library/os.html#os.pidfd_open) and
[pidfd signaling](https://docs.python.org/3/library/signal.html#signal.pidfd_send_signal).
The [Niri packaging guide](https://github.com/niri-wm/niri/wiki/Packaging-niri)
provides upstream context; local wrapper observations are installation-specific,
not a compatibility claim for all Niri versions.
