# Fedora 45 multi-shell reference system

Status: **User-observed baseline; launcher details not yet collected.** This document intentionally does not claim that the detector has verified an active Ryoku process.

## Reported environment (2026-11-14)

- Distribution: Fedora Linux 45 (COSMIC)
- Display manager: SDDM (configured, not confirmed active)
- Current desktop: `niri`; Wayland session
- Registered Wayland sessions: COSMIC, Niri (DMS), Niri (Noctalia), Niri (Ryoku)
- Compositor executable detected: `niri`
- Shell executable detected by original prototype: `dms`
- User reports currently running **Ryoku**.
- Shell active according to original prototype: unknown.

## Engineering conclusions

1. A registered `.desktop` session is not proof its shell executable is installed.
2. `XDG_CURRENT_DESKTOP=niri` identifies a compositor but not necessarily its shell.
3. Executable-name checks are incomplete for shells launched via wrappers or non-PATH locations.
4. Process observations cannot identify the active login session unless associated with its session/cgroup/user.
5. Prefer an explicit `unknown` over an unsupported claim.

## Needed for live validation

On the reference laptop, collect (and redact personal paths if desired):

```bash
env | grep -Ei '^(XDG_CURRENT_DESKTOP|XDG_SESSION_DESKTOP|DESKTOP_SESSION|XDG_SESSION_TYPE)='
grep -H -E '^(Name|Exec|TryExec)=' /usr/share/wayland-sessions/*.desktop
ps -eo pid,comm,args | grep -Ei 'ryoku|noctalia|dms|quickshell|niri' | grep -v grep
```

The command is read-only. Its output will allow us to replace synthetic launch examples with real fixtures and improve session-to-process correlation.

## Test status

The synthetic fixture models the **observed session names**, not their actual launch commands. It asserts that DMS, Noctalia and Ryoku are discoverable as *registered candidates* while the active shell remains unknown absent stronger evidence. Live tests on this laptop remain pending.
