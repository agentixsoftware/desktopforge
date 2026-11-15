"""Conservative catalog and deterministic previews; no executable operations."""
from __future__ import annotations

from .packages import package_assessment
from .requirements import assess_requirements
from .preflight import preflight_preview
from .session_layout import session_layout_preview
from .operations import PackageProposal, SessionProposal, operation_preview, order_operations
from .errors import RecipeError
from .install_records import installation_for, launch_warning
from .rendering import rendering_blocker
from .recipes import (COMPOSITORS, DISTRIBUTIONS, SHELLS, Recipe,
                      load_bundled_recipes, resolve_compatibility)


def compatibility_catalog() -> list[dict[str, str]]:
    """Target scope only: no distro/version combination is validated yet."""
    return [
        {"distribution": distro, "compositor": compositor, "shell": shell,
         "status": "unverified"}
        for distro in DISTRIBUTIONS for compositor in COMPOSITORS for shell in SHELLS
    ]


def build_plan(inventory: dict, compositor: str, shell: str,
               recipes: tuple[Recipe, ...] | None = None) -> dict:
    """Build a stable preview from supplied evidence without performing changes."""
    if compositor not in COMPOSITORS or shell not in SHELLS:
        raise ValueError("Unknown compositor or shell")
    distro = inventory["distribution"]["id"]
    recipes = load_bundled_recipes() if recipes is None else recipes
    if len({recipe.id for recipe in recipes}) != len(recipes):
        raise RecipeError("Duplicate recipe IDs")
    resolution = resolve_compatibility(inventory, compositor, shell, recipes)
    status = resolution["status"]
    existing = {entry["id"] for group in inventory["sessions"].values() for entry in group}
    evidence = inventory.get("preflight_evidence")
    occupied = existing | set((evidence or {}).get("occupied_session_ids", []))
    preflight = preflight_preview(evidence)
    base = f"desktopforge-{compositor}-{shell}"
    installed = installation_for(inventory, compositor, shell)
    session_id = base
    suffix = 2
    while session_id in occupied and installed is None:
        session_id = f"{base}-{suffix}"
        suffix += 1
    if installed is not None:
        # DesktopForge's own installation: recognize it instead of proposing a new ID.
        session_id = installed["session"]["id"]
    blockers = ["No validated installation recipe is available."]
    render_problem = rendering_blocker(inventory.get("rendering"), compositor)
    if render_problem:
        blockers.append(render_problem)
    blockers.extend(resolution["reasons"])
    blockers.extend(preflight["blockers"])
    matched = [recipe for recipe in recipes if recipe.id in resolution["recipe_ids"]]
    operations = []
    selected_recipe = None
    recipe_sources = []
    session_configuration = None
    requirements = assess_requirements((), inventory)
    if len(matched) > 1:
        blockers.append("Multiple recipes match; select one explicitly before proposing operations.")
    elif matched:
        recipe = matched[0]
        requirements = assess_requirements(recipe.requirements, inventory)
        for finding in requirements['findings']:
            if finding['status'] != 'observed':
                blockers.append(f"{finding['executable']} ({finding['role']}): " + ' '.join(finding['reasons']))
        selected_recipe = {"id": recipe.id, "revision": recipe.revision}
        recipe_sources = list(recipe.sources)
        blockers.extend(recipe.review_blockers)
        operations = [operation_preview(op, session_id) for op in order_operations(recipe.operations)]
        for operation in recipe.operations:
            if isinstance(operation, SessionProposal):
                session_configuration = session_layout_preview(operation.template, session_id, compositor, shell)
                if session_configuration:
                    blockers.extend(session_configuration["blockers"])
        if (evidence or {}).get("ostree_boot_marker", "absent") not in ("absent", "unknown"):
            operations = []
            session_configuration = None
        if any(isinstance(op, PackageProposal) for op in recipe.operations):
            blockers.append("Package versions, provenance and installed-package reuse have not been validated.")
        if any(isinstance(op, SessionProposal) for op in recipe.operations):
            blockers.append("Session template, launcher integration and filesystem conflicts have not been validated.")
    status_value = "blocked"
    warnings = []
    if installed is not None:
        if installed["status"] == "intact":
            status_value, blockers, operations, session_configuration = "installed", [], [], None
            if render_problem:
                warnings.append(render_problem)
            updated = [p["name"] for p in installed["packages"]["installed"] + installed["packages"]["reused"]
                       if p["status"] == "updated"]
            if updated:
                warnings.append("Updated since installation: " + ", ".join(updated) + ". DesktopForge validated "
                                "this session with the recorded versions.")
            failed_launch = launch_warning(installed)
            if failed_launch:
                warnings.append(failed_launch)
        else:
            problems = [f"{f['path']} is {f['status']}" for f in installed["files"] if f["status"] != "intact"]
            problems += [f"package {p['name']} is {p['status']}" for p in
                         installed["packages"]["installed"] + installed["packages"]["reused"]
                         if p["status"] == "missing"]
            problems += [f"package {p['name']} could not be checked" for p in
                         installed["packages"]["installed"] + installed["packages"]["reused"]
                         if p["status"] == "unknown"]
            blockers.insert(0, f"DesktopForge installation {installed['install_id']} of this combination is "
                               f"{installed['status']}: " + "; ".join(problems or ["see its install record"])
                               + ". In VM lab mode it can be repaired or removed (docs/REPAIR.md, docs/REMOVAL.md).")
            operations, session_configuration = [], None
    return {
        "schema_version": 2,
        "dry_run": True,
        "status": status_value,
        "existing_installation": installed,
        "warnings": warnings,
        "target": {"distribution": distro,
                   "version_id": inventory["distribution"]["version_id"],
                   "compositor": compositor, "shell": shell},
        "compatibility": status,
        "compatibility_resolution": resolution,
        "blockers": blockers,
        "session_id_preview": session_id,
        "package_assessment": package_assessment(inventory, compositor, shell),
        "component_evidence": {
            "compositor_executable_found": inventory["compositor_executables"][compositor]["found"],
            "shell_executable_found": inventory["shell_executables"][shell]["found"],
        },
        "preserve": {"display_manager": inventory["display_manager"]["name"],
                     "existing_sessions": sorted(existing), "user_configuration": True},
        "selected_recipe": selected_recipe,
        "recipe_sources": recipe_sources,
        "preflight": preflight,
        "requirement_assessment": requirements,
        "repository_assessment": inventory.get("repository_evidence", {"status": "unavailable"}),
        "session_configuration_preview": session_configuration,
        "executable": False,
        "operations": operations,
        "limitations": ["Executable discovery does not validate compatibility or safe reuse.",
                        "Session ID is a preview; filesystem conflicts must be checked before any future apply."],
    }
