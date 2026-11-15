"""VM-lab synthetic-recipe helper: fixed recipes, narrow bus surface and installer."""
import ast
import configparser
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

import pytest

from desktopforge.helper import sessions

REPO = Path(__file__).resolve().parents[1]
EMPTY = {'markers': [], 'sessions': []}
LAB = REPO / 'lab/helper'


@pytest.fixture(scope='module')
def helper():
    return runpy.run_path(str(LAB / 'desktopforge-lab-helper'))


def plan(helper, recipe, current=EMPTY, names=None):
    return helper['build_plan'](recipe, current, names or {}, sessions.render, sessions.session_filename)


@pytest.mark.parametrize('recipe', ['', 'LAB-SYNTHETIC-MARKER', '../etc', 'lab-synthetic-marker\n',
                                    'fedora45-niri-noctalia', None, 'x' * 65])
def test_only_built_in_lab_recipes_are_accepted(helper, recipe):
    with pytest.raises(helper['Rejected']):
        plan(helper, recipe)


def test_plans_target_only_lab_markers_and_the_session_directory(helper):
    for recipe_id in helper['RECIPES']:
        result, blockers = plan(helper, recipe_id)
        assert result['targets'] == {'markers': '/var/lib/desktopforge-lab/markers',
                                     'sessions': '/usr/share/wayland-sessions'} and blockers == []
        assert {op['op'] for op in result['operations']} <= {'create_file', 'register_session', 'fail'}
        for op in result['operations']:
            if op['op'] == 'create_file':
                assert op['target'] == 'markers' and '/' not in op['name'] and op['mode'] == 0o644
            if op['op'] == 'register_session':
                assert op['target'] == 'sessions' and op['id'].startswith('desktopforge-')


def test_existing_marker_blocks_preview_instead_of_overwriting(helper):
    _, blockers = plan(helper, 'lab-synthetic-marker',
                       {'markers': [{'name': 'desktopforge-lab-synthetic.marker'}], 'sessions': []})
    assert blockers and 'will not be overwritten' in blockers[0]


def test_session_file_collision_blocks(helper):
    _, blockers = plan(helper, 'lab-session-gnome',
                       {'markers': [], 'sessions': [{'name': 'desktopforge-lab-gnome.desktop'}]},
                       {'desktopforge-lab-gnome.desktop': 'Something else'})
    assert any('already exists' in b for b in blockers)


@pytest.mark.parametrize('existing', ['DesktopForge Lab (GNOME)', 'desktopforge lab (gnome)'])
def test_duplicate_display_name_blocks(helper, existing):
    _, blockers = plan(helper, 'lab-session-gnome', EMPTY, {'gnome.desktop': existing})
    assert blockers == ['A login session named "DesktopForge Lab (GNOME)" already exists']


def test_unreadable_session_name_blocks_conservatively(helper):
    _, blockers = plan(helper, 'lab-session-gnome', EMPTY, {'odd.desktop': None, 'gnome.desktop': 'GNOME'})
    assert blockers == ['Cannot read the display name of: odd.desktop']


def test_each_operation_class_has_its_own_polkit_action(helper):
    assert helper['action_for']('lab-session-gnome') == 'org.desktopforge.lab.register-session'
    assert helper['action_for']('lab-synthetic-marker') == 'org.desktopforge.lab.apply-synthetic'


def test_session_recipe_renders_with_the_lab_allowlist(helper):
    op = helper['RECIPES']['lab-session-gnome']['operations'][0]
    assert sessions.render(op['entry'], helper['ALLOWED_COMMANDS']).startswith(b'[Desktop Entry]\nName=')
    assert helper['ALLOWED_COMMANDS'] == frozenset({'/usr/bin/gnome-session'})


def test_summary_states_every_operation(helper):
    summary = helper['summarize'](plan(helper, 'lab-synthetic-fail')[0])
    assert summary[0].startswith('Create new file /var/lib/desktopforge-lab/markers/')
    assert summary[1].startswith('Injected failure')
    (line,) = helper['summarize'](plan(helper, 'lab-session-gnome')[0])
    assert '/usr/share/wayland-sessions/desktopforge-lab-gnome.desktop' in line
    assert 'Existing sessions are not changed' in line


def test_interface_inputs_are_only_recipe_id_token_and_plan_hash(helper):
    node = ET.fromstring(helper['INTROSPECTION'])
    inputs = {m.get('name'): [a.get('type') for a in m.findall("arg[@direction='in']")]
              for m in node.findall('./interface/method')}
    assert inputs == {'Preview': ['s'], 'Apply': ['s', 's']}


@pytest.mark.parametrize('action_id', ['org.desktopforge.lab.apply-synthetic',
                                       'org.desktopforge.lab.register-session'])
def test_polkit_actions_require_admin_auth_in_active_session_only(action_id):
    action = ET.parse(LAB / f'{action_id}.policy').getroot().find('action')
    assert action.get('id') == action_id
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


def test_unit_is_sandboxed_with_only_state_and_session_directories_writable():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.optionxform = str
    unit.read(LAB / 'desktopforge-lab-helper.service')
    service = unit['Service']
    assert service['ExecStart'].startswith('/usr/bin/python3 -Is /usr/local/libexec/desktopforge-lab/')
    assert service['CapabilityBoundingSet'] == '' and service['ProtectSystem'] == 'strict'
    assert service['StateDirectory'] == 'desktopforge-lab'
    assert service['ReadWritePaths'] == '/usr/share/wayland-sessions'
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
