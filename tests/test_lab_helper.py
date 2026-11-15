"""VM-lab synthetic-recipe helper: fixed recipes, narrow bus surface and installer."""
import ast
import configparser
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

import pytest

REPO = Path(__file__).resolve().parents[1]
LAB = REPO / 'lab/helper'


@pytest.fixture(scope='module')
def helper():
    return runpy.run_path(str(LAB / 'desktopforge-lab-helper'))


@pytest.mark.parametrize('recipe', ['', 'LAB-SYNTHETIC-MARKER', '../etc', 'lab-synthetic-marker\n',
                                    'fedora45-niri-noctalia', None, 'x' * 65])
def test_only_built_in_synthetic_recipes_are_accepted(helper, recipe):
    with pytest.raises(helper['Rejected']):
        helper['build_plan'](recipe, [])


def test_plan_targets_only_the_lab_marker_directory(helper):
    for recipe_id in helper['RECIPES']:
        plan, blockers = helper['build_plan'](recipe_id, [])
        assert plan['target'] == '/var/lib/desktopforge-lab/markers' and blockers == []
        assert {op['op'] for op in plan['operations']} <= {'create_file', 'fail'}
        for op in plan['operations']:
            if op['op'] == 'create_file':
                assert '/' not in op['name'] and op['mode'] == 0o644


def test_existing_marker_blocks_preview_instead_of_overwriting(helper):
    plan, blockers = helper['build_plan']('lab-synthetic-marker',
                                          [{'name': 'desktopforge-lab-synthetic.marker'}])
    assert blockers and 'will not be overwritten' in blockers[0]


def test_summary_states_every_operation(helper):
    plan, _ = helper['build_plan']('lab-synthetic-fail', [])
    summary = helper['summarize'](plan)
    assert summary[0].startswith('Create new file /var/lib/desktopforge-lab/markers/')
    assert summary[1].startswith('Injected failure')


def test_interface_inputs_are_only_recipe_id_token_and_plan_hash(helper):
    node = ET.fromstring(helper['INTROSPECTION'])
    inputs = {m.get('name'): [a.get('type') for a in m.findall("arg[@direction='in']")]
              for m in node.findall('./interface/method')}
    assert inputs == {'Preview': ['s'], 'Apply': ['s', 's']}


def test_polkit_action_requires_admin_auth_in_active_session_only():
    action = ET.parse(LAB / 'org.desktopforge.lab.apply-synthetic.policy').getroot().find('action')
    assert action.get('id') == 'org.desktopforge.lab.apply-synthetic'
    assert {c.tag: c.text for c in action.find('defaults')} == {
        'allow_any': 'no', 'allow_inactive': 'no', 'allow_active': 'auth_admin'}


def test_bus_policy_allows_only_preview_apply_and_introspect():
    root = ET.parse(LAB / 'org.desktopforge.LabHelper1.conf').getroot()
    owners = [(p.attrib, a.attrib) for p in root.findall('policy') for a in p if 'own' in a.attrib]
    assert owners == [({'user': 'root'}, {'own': 'org.desktopforge.LabHelper1'})]
    allowed = {(a.get('send_interface'), a.get('send_member'))
               for a in root.find("policy[@context='default']").findall('allow')}
    assert allowed == {('org.desktopforge.LabHelper1', 'Preview'), ('org.desktopforge.LabHelper1', 'Apply'),
                       ('org.freedesktop.DBus.Introspectable', 'Introspect')}


def test_unit_is_sandboxed_with_only_its_state_directory_writable():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.optionxform = str
    unit.read(LAB / 'desktopforge-lab-helper.service')
    service = unit['Service']
    assert service['ExecStart'].startswith('/usr/bin/python3 -Is /usr/local/libexec/desktopforge-lab/')
    assert service['CapabilityBoundingSet'] == '' and service['ProtectSystem'] == 'strict'
    assert service['StateDirectory'] == 'desktopforge-lab' and 'ReadWritePaths' not in service
    assert service['PrivateNetwork'] == 'yes'


def test_service_imports_core_only_from_root_owned_location(helper):
    assert helper['CORE_PATH'] == '/usr/local/lib/desktopforge-lab/python'
    tree = ast.parse((LAB / 'desktopforge-lab-helper').read_text())
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m.startswith('desktopforge.') or m == 'desktopforge' for m in modules)


def test_installer_ships_every_core_module_and_helper_file():
    installer = runpy.run_path(str(REPO / 'scripts/vm/install-lab'))
    files = installer['COMPONENTS']['helper']['files']
    core = {p.name for p in (REPO / 'src/desktopforge/helper').glob('*.py')}
    assert core == set(installer['CORE_FILES'])
    lab = {p.name for p in LAB.iterdir()} - {'desktopforge-lab-client'}
    assert lab <= {Path(source).name for source in files}
    for relative in files:
        assert (REPO / relative).is_file(), relative
