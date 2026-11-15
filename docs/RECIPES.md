# Read-only recipe metadata, schema version 1

Milestone 1 currently accepts metadata only. There is no executor, write operation
schema or supported installation procedure. Bundled metadata cannot claim verified
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

All fields are required; extra fields are rejected at both levels. IDs are lowercase
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
- Matching metadata remains `unverified` and produces a blocked plan with no
  operations. Package presence and a working unmanaged setup cannot promote it.

The packaged Fedora 45 Niri/Ryoku/SDDM metadata records only the observed reference
scope. All other catalog combinations remain unverified targets. There are no
compositor/shell version constraints, package/repository decisions, operation
composition or validated installation recipes yet.

The planner accepts injected typed recipes for tests. The production CLI loads
only bundled files. Python callers are responsible for using `parse_recipe` or
`load_recipe` to validate external data before supplying typed objects.
