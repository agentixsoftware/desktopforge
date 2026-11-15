# Read-only recipes and operation proposals

Milestone 1 accepts version 1 metadata and version 2 operation proposals. There
is no executor or supported installation procedure. Bundled metadata cannot claim verified
status; validation provenance and VM integration results must be designed before
that status becomes available.

Files under `src/desktopforge/data/recipes/*.yaml` use the JSON subset of YAML 1.2.
This intentionally narrow syntax permits dependency-free loading with duplicate-key
rejection and no YAML tags or constructors. General YAML syntax is not accepted.
Recipes are bundled package data, not loaded from user-supplied CLI paths.

```json
{
  "schema_version": 1,
  "id": "fedora45-niri-ryoku",
  "revision": 1,
  "status": "unverified",
  "constraints": {
    "distribution": "fedora",
    "versions": ["45"],
    "compositor": "niri",
    "shell": "ryoku",
    "display_managers": ["sddm"]
  }
}
```

All fields shown are required for version 1; extra fields are rejected at both levels. IDs are lowercase
alphanumeric slugs separated by hyphens; revisions are positive integers. Version
and revision fields do not accept booleans. Versions are unique, exact numeric
release strings, without wildcards or inferred ranges. Fedora requires at least
one release. Arch/CachyOS may explicitly use an empty list for rolling releases;
this is unconstrained release metadata, not proof of compatibility.

The allowed distribution, compositor and shell names match the initial target
catalog. Display managers are GDM and SDDM. These lists express scope, not tested
support. Unknown operations, command fields and statuses such as `verified` are
rejected. Parse failures stop planning with exit code 2.

## Resolver behavior

- Exact distribution IDs are required; `ID_LIKE` does not grant support.
- Release-constrained metadata requires an exact `VERSION_ID` match.
- Configured display-manager evidence must match the recipe constraint. It does
  not prove the service is running.
- Matching recipe IDs are sorted, so input ordering does not change a preview.
- Missing metadata for an in-scope target is `unverified`.
- An out-of-scope distro or a mismatch against existing metadata is `unsupported`
  by this catalog. This is not a claim that upstream software cannot work.
- Matching metadata remains `unverified` and produces a blocked plan. Version 2
  proposals may be shown, but are never executable. Package presence and a
  working unmanaged setup cannot promote it.

The packaged Fedora 45 Niri/Ryoku/SDDM metadata records only the observed reference
scope. All other catalog combinations remain unverified targets. There are no
compositor/shell version constraints, validated package/repository decisions,
cross-recipe composition or validated installation recipes yet.

The planner accepts injected typed recipes for tests. The production CLI loads
only bundled files. Python callers are responsible for using `parse_recipe` or
`load_recipe` to validate external data before supplying typed objects.

## Version 2 operation proposals

Version 2 requires the same metadata fields plus an `operations` list (which may
be empty). Version 1 continues to reject that field. Each operation requires a
unique slug `id`, an allowlisted `type`, and an explicit `depends_on` list of IDs
within that recipe. The supported type-specific fields are:

| Type | Required extra fields | Proposed privilege |
| --- | --- | --- |
| `dependency_check` | `executable`: basename without arguments or path | none |
| `package_proposal` | `package_manager`: dnf/dnf5/pacman; `packages`: nonempty unique plain names | system |
| `session_proposal` | `template`: bundled template ID slug, not a file path | system |

For example, a synthetic version 2 recipe can include:

```json
"operations": [
  {"id": "packages", "type": "package_proposal", "depends_on": [],
   "package_manager": "dnf5", "packages": ["synthetic-compositor"]},
  {"id": "check", "type": "dependency_check", "depends_on": ["packages"],
   "executable": "synthetic-compositor"},
  {"id": "session", "type": "session_proposal", "depends_on": ["check"],
   "template": "synthetic-session"}
]
```

These names are illustrative test data, not installation instructions. No
operation executes, including dependency checks. Package proposals contain no
command lines, repository URLs, options or shell expressions. The package manager
must match the recipe distribution. Privileges are derived from type; recipe
fields cannot override them.

Missing dependencies, duplicate IDs, self-dependencies and cycles are errors.
Topological sorting uses lexical ID order to break ties. Package and dependency
lists are canonicalized so their input order cannot change the preview. More than
one matching recipe blocks operation selection instead of merging alternatives.
There is no cross-recipe dependency syntax yet.

Only one session proposal is allowed per recipe. The planner derives its path
under `/usr/share/wayland-sessions/` from the generated unique session ID and
reports `overwrite: false`. It does not read a template, produce a runnable launcher, reserve a name or
write a file. Read-only preflight evidence now checks fixed path components and
existing DesktopForge namespace entries for collision hints; that is not
executor path validation. Template availability, integration and
filesystem conflicts remain explicit blockers. Package provenance, versions and
safe reuse also remain unvalidated. These proposals are not authorization for a
future executor.

Plan output is schema version 2. Each operation includes a plain-English summary,
derived privilege, proposed changes and `executable: false`. Plan status remains
`blocked`, `dry_run: true`, and the CLI exits with code 1. JSON serialization is
stable for identical inventory and equivalent operation input. The bundled
Fedora reference remains version 1 with no speculative installation operations;
synthetic version 2 examples are exercised through temporary fixtures. The bundled
Fedora 45 Niri/Noctalia recipe now supplies a researched but still unverified
version 2 preview; see FEDORA45_NIRI_NOCTALIA_RESEARCH.md.

## Optional version 2 review information

Version 2 may include a `review` object with exactly two required fields:
`sources`, a nonempty list of unique HTTPS URLs without embedded credentials,
and `blockers`, a nonempty list of unique plain-language review requirements.
Both lists are sorted when parsed. Unknown review fields and malformed values are
rejected; version 1 rejects `review` entirely. A recipe can still omit the object,
which keeps existing version 2 fixtures compatible.

The selected recipe's review blockers are appended to the planner's built-in
blockers; they cannot remove them or grant support. Source URLs are exposed as
`recipe_sources` in plan JSON and as references in text output. They are never
fetched during planning and do not establish signed validation provenance.
Unmatched or ambiguous recipes contribute no operation proposals or sources.

The `niri-noctalia-v5` template ID now has an incomplete isolated layout preview.
Its launcher content is unavailable and its config fragment is not a complete
Niri configuration. See [session drafts and preflight](SESSION_PREFLIGHT.md) for
path selection, static evidence, schema changes and explicit limitations.
