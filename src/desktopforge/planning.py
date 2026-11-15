"""Conservative catalog and deterministic previews; no executable operations."""
from __future__ import annotations

from .operations import PackageProposal, SessionProposal, operation_preview, order_operations
from .errors import RecipeError
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
    base = f"desktopforge-{compositor}-{shell}"
    session_id = base
    suffix = 2
    while session_id in existing:
        session_id = f"{base}-{suffix}"
        suffix += 1
    blockers = ["No validated installation recipe is available."]
    blockers.extend(resolution["reasons"])
    matched = [recipe for recipe in recipes if recipe.id in resolution["recipe_ids"]]
    operations = []
    selected_recipe = None
    if len(matched) > 1:
        blockers.append("Multiple recipes match; select one explicitly before proposing operations.")
    elif matched:
        recipe = matched[0]
        selected_recipe = {"id": recipe.id, "revision": recipe.revision}
        operations = [operation_preview(op, session_id) for op in order_operations(recipe.operations)]
        if any(isinstance(op, PackageProposal) for op in recipe.operations):
            blockers.append("Package versions, provenance and installed-package reuse have not been validated.")
        if any(isinstance(op, SessionProposal) for op in recipe.operations):
            blockers.append("Session template, launcher integration and filesystem conflicts have not been validated.")
    return {
        "schema_version": 2,
        "dry_run": True,
        "status": "blocked",
        "target": {"distribution": distro,
                   "version_id": inventory["distribution"]["version_id"],
                   "compositor": compositor, "shell": shell},
        "compatibility": status,
        "compatibility_resolution": resolution,
        "blockers": blockers,
        "session_id_preview": session_id,
        "component_evidence": {
            "compositor_executable_found": inventory["compositor_executables"][compositor]["found"],
            "shell_executable_found": inventory["shell_executables"][shell]["found"],
        },
        "preserve": {"display_manager": inventory["display_manager"]["name"],
                     "existing_sessions": sorted(existing), "user_configuration": True},
        "selected_recipe": selected_recipe,
        "executable": False,
        "operations": operations,
        "limitations": ["Executable discovery does not validate compatibility or safe reuse.",
                        "Session ID is a preview; filesystem conflicts must be checked before any future apply."],
    }
