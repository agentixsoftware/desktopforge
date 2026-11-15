"""Typed recipe metadata and operation proposals; no command execution or writes."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .errors import RecipeError
from .operations import Operation, PackageProposal, parse_operations

DISTRIBUTIONS = ("fedora", "arch", "cachyos")
COMPOSITORS = ("niri", "hyprland")
SHELLS = ("noctalia", "dms", "ryoku")


def _keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise RecipeError(f"{label} must contain exactly: {', '.join(sorted(expected))}")
    return value


def _strings(value: object, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise RecipeError(f"{label} must be a list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RecipeError(f"{label} must contain nonempty strings")
    if len(set(value)) != len(value):
        raise RecipeError(f"{label} must not contain duplicates")
    return tuple(value)


@dataclass(frozen=True)
class Constraints:
    distribution: str
    versions: tuple[str, ...]
    compositor: str
    shell: str
    display_managers: tuple[str, ...]


@dataclass(frozen=True)
class Recipe:
    id: str
    revision: int
    constraints: Constraints
    # Only unverified metadata is accepted until validation provenance is designed.
    status: str = "unverified"
    operations: tuple[Operation, ...] = ()
    sources: tuple[str, ...] = ()
    review_blockers: tuple[str, ...] = ()


def parse_recipe(data: object) -> Recipe:
    """Reject unknown fields and unsupported operations rather than ignore them."""
    if not isinstance(data, dict):
        raise RecipeError("Recipe must be an object")
    version = data.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise RecipeError("Unsupported recipe schema_version")
    expected = {"schema_version", "id", "revision", "status", "constraints"}
    if version == 2:
        expected.add("operations")
        if "review" in data:
            expected.add("review")
    data = _keys(data, expected, "recipe")
    if not isinstance(data["id"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data["id"]):
        raise RecipeError("Recipe id must be a lowercase slug")
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise RecipeError("Recipe revision must be a positive integer")
    if data["status"] != "unverified":
        raise RecipeError("Only unverified recipe metadata is supported")
    fields = _keys(data["constraints"], {"distribution", "versions", "compositor", "shell", "display_managers"}, "constraints")
    for key, allowed in (("distribution", DISTRIBUTIONS), ("compositor", COMPOSITORS), ("shell", SHELLS)):
        if fields[key] not in allowed:
            raise RecipeError(f"Unsupported {key}")
    versions = _strings(fields["versions"], "versions", nonempty=False)
    if any(not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) for version in versions):
        raise RecipeError("Versions must be exact numeric release identifiers")
    if fields["distribution"] == "fedora" and not versions:
        raise RecipeError("Fedora requires explicit version constraints")
    managers = _strings(fields["display_managers"], "display_managers")
    if any(manager not in ("gdm", "sddm") for manager in managers):
        raise RecipeError("Unsupported display manager")
    operations = parse_operations(data["operations"]) if version == 2 else ()
    allowed_managers = ("dnf", "dnf5") if fields["distribution"] == "fedora" else ("pacman",)
    if any(isinstance(op, PackageProposal) and op.package_manager not in allowed_managers for op in operations):
        raise RecipeError("Package manager does not match recipe distribution")
    sources: tuple[str, ...] = ()
    review_blockers: tuple[str, ...] = ()
    if "review" in data:
        review = _keys(data["review"], {"sources", "blockers"}, "review")
        sources = tuple(sorted(_strings(review["sources"], "review.sources")))
        review_blockers = tuple(sorted(_strings(review["blockers"], "review.blockers")))
        for source in sources:
            try:
                url = urlsplit(source)
                valid = (url.scheme == "https" and bool(url.hostname) and not url.username
                         and not url.password and not any(char.isspace() for char in source))
            except ValueError:
                valid = False
            if not valid:
                raise RecipeError("Review sources must be HTTPS URLs without credentials")
    return Recipe(data["id"], data["revision"], Constraints(
        fields["distribution"], versions, fields["compositor"], fields["shell"], managers), operations=operations,
                  sources=sources, review_blockers=review_blockers)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError(f"Duplicate recipe key: {key}")
        result[key] = value
    return result


def load_recipe(path: Path) -> Recipe:
    """Read the JSON subset of YAML 1.2; tags and executable constructors are absent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RecipeError(f"Cannot load recipe {path.name}: {exc}") from exc
    return parse_recipe(data)


def load_bundled_recipes() -> tuple[Recipe, ...]:
    paths = sorted((Path(__file__).parent / "data/recipes").glob("*.yaml"))
    recipes = tuple(load_recipe(path) for path in paths)
    ids = [recipe.id for recipe in recipes]
    if len(ids) != len(set(ids)):
        raise RecipeError("Duplicate recipe IDs")
    return recipes


def resolve_compatibility(inventory: dict, compositor: str, shell: str,
                          recipes: tuple[Recipe, ...]) -> dict:
    """Exact distro/version matching. ID_LIKE never grants compatibility."""
    distribution = inventory["distribution"]
    distro = distribution["id"]
    if distro not in DISTRIBUTIONS:
        return {"status": "unsupported", "recipe_ids": [],
                "reasons": ["Distribution is outside the initial target catalog."]}
    candidates = sorted((recipe for recipe in recipes
                         if recipe.constraints.distribution == distro
                         and recipe.constraints.compositor == compositor
                         and recipe.constraints.shell == shell), key=lambda recipe: recipe.id)
    if not candidates:
        return {"status": "unverified", "recipe_ids": [],
                "reasons": ["No version-scoped recipe metadata is available for this target."]}
    matched = []
    for recipe in candidates:
        constraints = recipe.constraints
        if constraints.versions and distribution["version_id"] not in constraints.versions:
            continue
        if inventory["display_manager"]["name"] not in constraints.display_managers:
            continue
        matched.append(recipe.id)
    if not matched:
        return {"status": "unsupported", "recipe_ids": [],
                "reasons": ["Detected distribution version or display manager does not match recipe constraints."]}
    return {"status": "unverified", "recipe_ids": matched,
            "reasons": ["Matching recipe metadata exists but has no validated installation procedure."]}
