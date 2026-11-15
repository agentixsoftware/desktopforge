from copy import deepcopy
import json

import pytest

from desktopforge.detection import detect_system
from desktopforge.planning import build_plan
from desktopforge.recipes import (RecipeError, load_bundled_recipes, load_recipe,
                                  parse_recipe, resolve_compatibility)


@pytest.fixture
def metadata():
    return {
        'schema_version': 1, 'id': 'fedora45-niri-ryoku', 'revision': 1,
        'status': 'unverified',
        'constraints': {'distribution': 'fedora', 'versions': ['45'],
                        'compositor': 'niri', 'shell': 'ryoku',
                        'display_managers': ['sddm']},
    }


@pytest.fixture
def system(tmp_path):
    data = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    data['distribution'].update(id='fedora', version_id='45')
    data['display_manager']['name'] = 'sddm'
    return data


def test_bundled_metadata_matches_reference_without_claiming_support(system):
    recipes = load_bundled_recipes()
    assert recipes
    plan = build_plan(system, 'niri', 'ryoku')
    assert plan['compatibility_resolution']['recipe_ids'] == ['fedora45-niri-ryoku']
    assert plan['compatibility'] == 'unverified'
    assert plan['status'] == 'blocked'
    assert plan['operations'] == []


@pytest.mark.parametrize('key,value', [
    ('schema_version', True), ('schema_version', 2), ('revision', False),
    ('revision', 0), ('id', '../escape'), ('id', ''), ('status', 'verified'),
    ('steps', [{'type': 'run', 'command': 'touch /tmp/untrusted'}]),
])
def test_invalid_top_level_metadata_rejected(metadata, key, value):
    metadata[key] = value
    with pytest.raises(RecipeError):
        parse_recipe(metadata)


@pytest.mark.parametrize('key,value', [
    ('distribution', 'ubuntu'), ('compositor', 'unknown'), ('shell', 'unknown'),
    ('versions', []), ('versions', ['*']), ('versions', [45]),
    ('versions', ['45', '45']), ('versions', '45'),
    ('display_managers', []), ('display_managers', ['lightdm']),
    ('preserve_display_manager', False),
])
def test_invalid_constraints_rejected(metadata, key, value):
    metadata['constraints'][key] = value
    with pytest.raises(RecipeError):
        parse_recipe(metadata)


@pytest.mark.parametrize('version', ['44', '46', '450', '45.1', None])
def test_version_constraints_fail_closed(system, metadata, version):
    system['distribution']['version_id'] = version
    result = resolve_compatibility(system, 'niri', 'ryoku', (parse_recipe(metadata),))
    assert result['status'] == 'unsupported'
    assert result['recipe_ids'] == []


def test_display_manager_constraint_and_id_like_do_not_grant_support(system, metadata):
    recipes = (parse_recipe(metadata),)
    system['display_manager']['name'] = None
    assert resolve_compatibility(system, 'niri', 'ryoku', recipes)['status'] == 'unsupported'
    system['distribution'].update(id='derivative', id_like=['fedora'])
    assert resolve_compatibility(system, 'niri', 'ryoku', recipes)['status'] == 'unsupported'


def test_missing_metadata_is_unverified_and_resolution_is_order_independent(system, metadata):
    assert resolve_compatibility(system, 'niri', 'ryoku', ())['status'] == 'unverified'
    other = deepcopy(metadata)
    other['id'] = 'second-recipe'
    a, b = parse_recipe(metadata), parse_recipe(other)
    assert build_plan(system, 'niri', 'ryoku', (a, b)) == build_plan(system, 'niri', 'ryoku', (b, a))


def test_rolling_distribution_can_explicitly_omit_release_constraint(system, metadata):
    metadata['constraints'].update(distribution='arch', versions=[])
    system['distribution'].update(id='arch', version_id=None)
    assert resolve_compatibility(system, 'niri', 'ryoku', (parse_recipe(metadata),))['status'] == 'unverified'


def test_safe_loader_rejects_duplicate_keys_and_yaml_tags(tmp_path, metadata):
    path = tmp_path / 'recipe.yaml'
    path.write_text(json.dumps(metadata))
    assert load_recipe(path) == parse_recipe(metadata)
    for content in ['{"id":"first", "id":"second"}', '!!python/object/apply:os.system ["false"]', '{}']:
        path.write_text(content)
        with pytest.raises(RecipeError):
            load_recipe(path)
    with pytest.raises(RecipeError):
        load_recipe(tmp_path / 'missing.yaml')
