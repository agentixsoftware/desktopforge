# Privileged helper protocol proposal

Status: design for review and VM experiments. No production helper or policy
exists, no apply API is implemented, and this proposal does not enable Install.
A non-mutating [lab authorization probe](LAB_AUTHPROBE.md) has validated bus-derived
caller identity and Polkit checks (deny, dismiss, approve, no retention, caller
disconnect) inside the disposable VM only. A [lab helper](LAB_HELPER.md) implements
the request flow below for synthetic recipes: one-time grants, plan/caller
binding, expiry, post-authorization evidence recheck and journaling.

## Mechanism and caller identity

Use a separately packaged, system-bus-activated service with a small versioned
interface. Obtain the caller's unique bus name and UID from the system bus,
not client-supplied PID, UID, HOME, environment or filesystem paths. Authorize
that bus-name subject through Polkit's `CheckAuthorization`. Treat all client
arguments and recipe content as untrusted. The GUI remains unprivileged.

Start with administrator authentication for an active local session, no implicit
permission for inactive/other clients, and no retained authorization. These policy
choices need real graphical-session tests, including denial and cancellation.
Guest setup over administrator SSH is separate from testing GUI authorization.

## Proposed request flow

1. Client selects a bundled recipe ID/revision and asks for a preview. The helper
   loads its own root-owned catalog and recomputes system evidence. It must not
   accept client-authored operations, recipe files, shell text or arbitrary paths.
2. Return a bounded structured preview, blockers and a short-lived random request
   token bound to caller bus name, UID, recipe revision, plan hash and relevant
   inventory/filesystem fingerprint. A token alone grants no authorization.
3. After explicit plan approval, the client requests application of that token.
   Recheck the caller, token lifetime and recipe validation evidence. Check Polkit
   authorization for the sensitive operation class, including cancellation.
4. Immediately repeat preflight and compare the reviewed fingerprint. Changed
   evidence invalidates the request and requires a new preview and approval.
5. Serialize conflicting installations, journal each operation durably, create
   backups where applicable, execute the fixed operation set, then verify.
   Return precise results and recovery guidance. Client disconnect does not justify
   pretending a package transaction was rolled back.

## First operation scope

Begin with synthetic, guest-only authorization and filesystem tests. Production
registration must render only bundled session/launcher templates into unique,
allowlisted DesktopForge namespaces. Reject overwrites, unsafe symlinks, changed
parent directories, client-selected owners/modes and writes to display-manager or
existing user configuration. Per-user configuration creation needs its own design
before it can be enabled. Path checks must use filesystem handles across creation,
not a check-then-open sequence vulnerable to path replacement.

Package transactions need a separate operation class and review: fixed native
adapter, resolved packages/dependencies/repositories, version and trust evidence,
transaction effects, explicit approval and accurate partial-failure records.
Never enable an unvalidated recipe merely to exercise the helper. Experimental
VM test requests must be unreachable through production apply authorization.

## Evidence required before implementation is considered ready

Test forged caller claims, invalid/expired/replayed tokens, bus disconnects,
concurrent requests, inventory changes after approval, denied/cancelled Polkit
requests, path replacement, existing session IDs, journal failures and interruption
at every write boundary. Then perform the graphical preservation/lifecycle matrix
in [VM validation](VM_VALIDATION.md). Keep GUI installation unavailable until both
security boundaries and a concrete recipe meet their validation requirements.

Sources: [Polkit mechanism model](https://www.freedesktop.org/software/polkit/docs/latest/polkit.8.html)
and [Authority API and subjects](https://www.freedesktop.org/software/polkit/docs/latest/eggdbus-interface-org.freedesktop.PolicyKit1.Authority.html).
