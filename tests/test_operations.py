from copy import deepcopy
import json

import pytest

from desktopforge.cli import main
from desktopforge.detection import detect_system
from desktopforge.operations import parse_operations
from desktopforge.planning import build_plan
from desktopforge.recipes import RecipeError, load_recipe, parse_recipe


@pytest.fixture
def recipe_data():
    return {
        'schema_version': 2, 'id': 'synthetic-preview', 'revision': 1,
        'status': 'unverified',
        'constraints': {'distribution': 'fedora', 'versions': ['45'],
                        'compositor': 'niri', 'shell': 'ryoku', 'display_managers': ['sddm']},
        'operations': [
            {'id': 'session', 'type': 'session_proposal', 'depends_on': ['check'], 'template': 'synthetic-session'},
            {'id': 'check', 'type': 'dependency_check', 'depends_on': ['packages'], 'executable': 'synthetic-compositor'},
            {'id': 'packages', 'type': 'package_proposal', 'depends_on': [], 'package_manager': 'dnf5',
             'packages': ['synthetic-shell', 'synthetic-compositor']},
        ],
    }


@pytest.fixture
def system(tmp_path):
    result = detect_system(root=tmp_path, environ={}, which=lambda _: None)
    result['distribution'].update(id='fedora', version_id='45')
    result['display_manager']['name'] = 'sddm'
    return result


def test_proposals_are_ordered_deterministic_and_never_applied(recipe_data, system, tmp_path):
    recipe_path = tmp_path / 'synthetic.yaml'
    recipe_path.write_text(json.dumps(recipe_data))
    before = deepcopy(system)
    files_before = sorted(str(p) for p in tmp_path.rglob('*'))
    first = build_plan(system, 'niri', 'ryoku', (load_recipe(recipe_path),))
    recipe_data['operations'].reverse()
    recipe_data['operations'][0]['packages'].reverse()
    second = build_plan(system, 'niri', 'ryoku', (parse_recipe(recipe_data),))
    assert first == second
    assert [op['id'] for op in first['operations']] == ['packages', 'check', 'session']
    assert [op['privilege'] for op in first['operations']] == ['system', 'none', 'system']
    assert first['schema_version'] == 2
    assert first['status'] == 'blocked' and first['executable'] is False
    assert all(op['executable'] is False for op in first['operations'])
    assert first['operations'][-1]['overwrite'] is False
    assert first['selected_recipe'] == {'id': 'synthetic-preview', 'revision': 1}
    assert system == before
    assert sorted(str(p) for p in tmp_path.rglob('*')) == files_before
    assert any('provenance' in reason for reason in first['blockers'])
    assert any('template' in reason for reason in first['blockers'])


def test_independent_operations_have_lexical_order():
    entries = [{'id': name, 'type': 'dependency_check', 'depends_on': [], 'executable': name}
               for name in ['z', 'b', 'a']]
    assert [op.id for op in parse_operations(entries)] == ['a', 'b', 'z']


@pytest.mark.parametrize('case', ['duplicate', 'missing', 'self', 'cycle'])
def test_invalid_dependency_graph_rejected(recipe_data, case):
    operations = recipe_data['operations']
    if case == 'duplicate':
        operations.append(deepcopy(operations[0]))
    elif case == 'missing':
        operations[0]['depends_on'] = ['absent']
    elif case == 'self':
        operations[0]['depends_on'] = ['session']
    else:
        operations[2]['depends_on'] = ['session']
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)


@pytest.mark.parametrize('field,value', [
    ('type', 'run'), ('id', '../bad'), ('depends_on', ['check', 'check']),
    ('depends_on', 'check'), ('depends_on', [False]), ('privilege', 'none'),
    ('command', 'touch /tmp/unsafe'), ('path', '/etc/sddm.conf'),
    ('template', '../../launcher'), ('template', '/usr/bin/sh'),
])
def test_session_schema_rejects_unsafe_or_unknown_fields(recipe_data, field, value):
    recipe_data['operations'][0][field] = value
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)


@pytest.mark.parametrize('value', ['--help', '/usr/bin/niri', 'niri --session', '$(id)', '', None])
def test_dependency_is_basename_only(recipe_data, value):
    recipe_data['operations'][1]['executable'] = value
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)


@pytest.mark.parametrize('packages', [[], ['--allowerasing'], ['pkg;id'], ['https://example.com/pkg'],
                                      ['pkg', 'pkg'], [1], 'pkg'])
def test_package_names_are_plain_names(recipe_data, packages):
    recipe_data['operations'][2]['packages'] = packages
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)


def test_package_manager_matches_distro(recipe_data):
    recipe_data['operations'][2]['package_manager'] = 'pacman'
    with pytest.raises(RecipeError, match='distribution'):
        parse_recipe(recipe_data)


def test_operation_container_and_v1_compatibility(recipe_data):
    recipe_data['operations'] = [None]
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)
    recipe_data['operations'] = None
    with pytest.raises(RecipeError):
        parse_recipe(recipe_data)
    recipe_data['schema_version'] = 1
    del recipe_data['operations']
    assert parse_recipe(recipe_data).operations == ()


def test_mismatch_and_ambiguous_recipes_never_leak_operations(recipe_data, system):
    recipe = parse_recipe(recipe_data)
    system['distribution']['version_id'] = '46'
    assert build_plan(system, 'niri', 'ryoku', (recipe,))['operations'] == []
    system['distribution']['version_id'] = '45'
    recipe_data['id'] = 'another-recipe'
    second = parse_recipe(recipe_data)
    plan = build_plan(system, 'niri', 'ryoku', (recipe, second))
    assert plan['operations'] == []
    assert any('Multiple recipes' in blocker for blocker in plan['blockers'])
    with pytest.raises(RecipeError, match='Duplicate recipe IDs'):
        build_plan(system, 'niri', 'ryoku', (recipe, recipe))


def test_session_destination_uses_unique_generated_id(recipe_data, system):
    system['sessions']['wayland'] = [{'id': 'desktopforge-niri-ryoku'}]
    result = build_plan(system, 'niri', 'ryoku', (parse_recipe(recipe_data),))
    assert result['operations'][-1]['destination_preview'] == '/usr/share/wayland-sessions/desktopforge-niri-ryoku-2.desktop'


def test_cli_prints_proposal_permissions_and_changes(recipe_data, system, monkeypatch, capsys):
    result = build_plan(system, 'niri', 'ryoku', (parse_recipe(recipe_data),))
    monkeypatch.setattr('desktopforge.cli.detect_system', lambda: system)
    monkeypatch.setattr('desktopforge.cli.build_plan', lambda *args: result)
    args = ['plan', '--compositor', 'niri', '--shell', 'ryoku']
    assert main(args) == 1
    text = capsys.readouterr().out
    assert 'packages [system]' in text and 'check [none]' in text
    assert '/usr/share/wayland-sessions/desktopforge-niri-ryoku.desktop' in text
    assert 'not executed' in text
    assert main(args + ['--json']) == 1
    assert json.loads(capsys.readouterr().out) == result


def test_multiple_session_proposals_cannot_share_destination(recipe_data):
    extra = deepcopy(recipe_data['operations'][0])
    extra['id'] = 'second-session'
    recipe_data['operations'].append(extra)
    with pytest.raises(RecipeError, match='Only one session'):
        parse_recipe(recipe_data)
