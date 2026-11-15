from copy import deepcopy

import pytest

from desktopforge.errors import RecipeError
from desktopforge.requirements import parse_requirements, assess_requirements
from desktopforge.recipes import load_bundled_recipes
from desktopforge.planning import build_plan
from desktopforge.detection import detect_system


def requirement(**changes):
    return {'executable': 'noctalia', 'role': 'shell_launcher', 'package': 'noctalia',
            'version_major': 5, **changes}


def inventory(version='5.4.1', owner='noctalia'):
    return {'command_evidence': {'noctalia': {'found': True, 'path': '/usr/bin/noctalia'}},
            'package_inventory': {'packages': [{'name': 'noctalia', 'status': 'installed',
                                                'records': [{'version': version}]}],
                                  'executable_ownership': [{'executable': 'noctalia', 'path': '/usr/bin/noctalia',
                                                            'status': 'owned', 'owners': [owner]}]}}


@pytest.mark.parametrize('changes', [
    {'executable': '/bin/noctalia'}, {'executable': 'noctalia --daemon'}, {'role': 'run'},
    {'package': '../escape'}, {'version_major': True}, {'version_major': -1},
    {'version_major': '5'}, {'command': 'sh'},
])
def test_requirement_schema_rejects_unsafe_or_ambiguous_values(changes):
    with pytest.raises(RecipeError):
        parse_requirements([requirement(**changes)])


def test_duplicate_command_rejected():
    with pytest.raises(RecipeError):
        parse_requirements([requirement(), requirement(role='management')])


@pytest.mark.parametrize('version,status', [('5.4.1', 'observed'), ('50.0', 'mismatch'),
                                          ('4.9', 'mismatch'), ('6.0', 'mismatch'),
                                          ('5preview', 'unknown')])
def test_major_version_is_component_match_not_string_prefix(version, status):
    data = inventory(version)
    before = deepcopy(data)
    result = assess_requirements(parse_requirements([requirement()]), data)
    assert result['findings'][0]['status'] == status
    assert result['status'] == 'unverified'
    assert data == before


def test_management_command_cannot_satisfy_shell_launcher():
    data = inventory(owner='noctalia-cli')
    assert assess_requirements(parse_requirements([requirement()]), data)['findings'][0]['status'] == 'mismatch'
    data['command_evidence'] = {'noctalia-shell': {'found': True, 'path': '/usr/bin/noctalia-shell'}}
    assert assess_requirements(parse_requirements([requirement()]), data)['findings'][0]['status'] == 'unknown'


def test_uninspected_and_missing_are_distinct():
    reqs = parse_requirements([requirement()])
    assert assess_requirements(reqs, {})['findings'][0]['status'] == 'unknown'
    data = inventory()
    data['command_evidence']['noctalia'] = {'found': False, 'path': None}
    assert assess_requirements(reqs, data)['findings'][0]['status'] == 'missing'


def test_observed_requirements_never_enable_plan(tmp_path):
    data = detect_system(tmp_path, environ={}, which=lambda _: None)
    data['distribution'].update(id='fedora', version_id='45')
    data['display_manager']['name'] = 'sddm'
    recipe = next(r for r in load_bundled_recipes() if r.id == 'fedora45-niri-noctalia')
    data['command_evidence'] = {}
    data['package_inventory']['packages'] = []
    data['package_inventory']['executable_ownership'] = []
    for req in recipe.requirements:
        path = '/usr/bin/' + req.executable
        data['command_evidence'][req.executable] = {'found': True, 'path': path}
        data['package_inventory']['packages'].append({'name': req.package, 'status': 'installed',
            'records': [{'version': '5.4.1'}], 'reason': 'Fixture'})
        data['package_inventory']['executable_ownership'].append({'executable': req.executable,
            'component': req.executable, 'path': path, 'owners': [req.package], 'status': 'owned'})
    plan = build_plan(data, 'niri', 'noctalia')
    assert all(f['status'] == 'observed' for f in plan['requirement_assessment']['findings'])
    assert plan['status'] == 'blocked' and plan['executable'] is False


def test_ryoku_management_cli_does_not_satisfy_reference_launcher(tmp_path):
    data = detect_system(tmp_path, environ={}, which=lambda _: None)
    data['distribution'].update(id='fedora', version_id='45')
    data['display_manager']['name'] = 'sddm'
    data['command_evidence']['ryoku'] = {'found': True, 'path': '/usr/bin/ryoku'}
    data['command_evidence']['ryoku-shell'] = {'found': False, 'path': None}
    plan = build_plan(data, 'niri', 'ryoku')
    finding = next(f for f in plan['requirement_assessment']['findings'] if f['role'] == 'shell_launcher')
    assert finding['executable'] == 'ryoku-shell'
    assert finding['status'] == 'missing'
    assert plan['operations'] == []
    assert plan['status'] == 'blocked' and not plan['executable']
