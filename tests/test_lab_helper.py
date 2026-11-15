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


TEMPLATES = {'niri-noctalia.kdl': (LAB / 'templates/niri-noctalia.kdl').read_text()}
RESOLVED = [{'name': 'niri', 'arch': 'x86_64', 'evr': '0:26.04-2.fc45', 'repo': 'fedora'}]


def plan(helper, recipe, current=EMPTY, names=None, resolve=lambda p, r: (RESOLVED, [])):
    return helper['build_plan'](recipe, current, names or {}, sessions.render, sessions.session_filename,
                                resolve=resolve, templates=TEMPLATES)


@pytest.mark.parametrize('recipe', ['', 'LAB-SYNTHETIC-MARKER', '../etc', 'lab-synthetic-marker\n',
                                    'fedora45-niri-noctalia', None, 'x' * 65])
def test_only_built_in_lab_recipes_are_accepted(helper, recipe):
    with pytest.raises(helper['Rejected']):
        plan(helper, recipe)


def test_plans_target_only_lab_markers_and_the_session_directory(helper):
    for recipe_id in helper['RECIPES']:
        result, blockers = plan(helper, recipe_id)
        assert result['targets'] == {'markers': '/var/lib/desktopforge-lab/markers',
                                     'sessions': '/usr/share/wayland-sessions',
                                     'session-config': '/etc/desktopforge/sessions'} and blockers == []
        assert {op['op'] for op in result['operations']} <= {
            'install_packages', 'create_file', 'validate_config', 'register_session', 'fail'}
        for op in result['operations']:
            if op['op'] == 'create_file':
                assert op['target'] in ('markers', 'session-config') and '/' not in op['name']
                assert op['mode'] == 0o644 and 'template' not in op
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
    assert helper['action_for']('fedora45-niri-noctalia-lab') == 'org.desktopforge.lab.install-session'
    assert helper['action_for']('lab-session-gnome') == 'org.desktopforge.lab.register-session'
    assert helper['action_for']('lab-synthetic-marker') == 'org.desktopforge.lab.apply-synthetic'


def test_session_recipe_renders_with_the_lab_allowlist(helper):
    op = helper['RECIPES']['lab-session-gnome']['operations'][0]
    assert sessions.render(op['entry'], helper['ALLOWED_COMMANDS']).startswith(b'[Desktop Entry]\nName=')
    assert helper['ALLOWED_COMMANDS'] == frozenset({
        '/usr/bin/gnome-session', '/usr/bin/niri',
        '/usr/bin/niri --session --config /etc/desktopforge/sessions/niri-noctalia.kdl'})


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
                                       'org.desktopforge.lab.register-session',
                                       'org.desktopforge.lab.install-session'])
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
    assert service['ConfigurationDirectory'] == 'desktopforge'
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
    lab = {p.name for p in LAB.iterdir() if p.is_file()} - {'desktopforge-lab-client'}
    assert lab <= {Path(source).name for source in files}
    assert 'lab/helper/templates/niri-noctalia.kdl' in files
    for relative in files:
        assert (REPO / relative).is_file(), relative


# ---- Fedora 45 Niri + Noctalia lab recipe ------------------------------------------

import shutil  # noqa: E402
import subprocess  # noqa: E402


def test_niri_recipe_plan_embeds_resolution_and_config(helper):
    result, blockers = plan(helper, 'fedora45-niri-noctalia-lab')
    assert blockers == []
    ops = result['operations']
    assert [op['op'] for op in ops] == ['install_packages', 'create_file', 'validate_config', 'register_session']
    assert ops[0]['expected'] == RESOLVED and ops[0]['repositories'] == ['fedora', 'updates']
    assert ops[1]['content'] == TEMPLATES['niri-noctalia.kdl'] and result['signer'] == '655a4b02f577861e'
    assert ops[3]['entry']['Exec'] == '/usr/bin/niri --session --config /etc/desktopforge/sessions/niri-noctalia.kdl'


def test_niri_recipe_plan_hash_changes_with_resolution(helper):
    from desktopforge.helper import executor
    first, _ = plan(helper, 'fedora45-niri-noctalia-lab')
    newer = [dict(RESOLVED[0], evr='0:26.04-3.fc45')]
    second, _ = plan(helper, 'fedora45-niri-noctalia-lab', resolve=lambda p, r: (newer, []))
    assert executor.plan_hash(first) != executor.plan_hash(second)


def test_package_blockers_reach_the_preview(helper):
    _, blockers = plan(helper, 'fedora45-niri-noctalia-lab', resolve=lambda p, r: ([], ['pending offline update']))
    assert blockers == ['pending offline update']


def test_niri_recipe_summary_discloses_package_session_and_user_config(helper):
    summary = helper['summarize'](plan(helper, 'fedora45-niri-noctalia-lab')[0])
    text = '\n'.join(summary)
    assert 'niri 0:26.04-2.fc45 [fedora]' in text and 'no weak dependencies' in text
    assert 'Already installed and reused unchanged: noctalia' in text
    assert 'Fedora\'s own "Niri" login session' in text and '~/.local/state/noctalia' in text
    assert 'github.com/noctalia-dev' in text
    assert 'refuses software rendering' in text and 'choose another session' in text


def test_existing_config_blocks(helper):
    current = {'markers': [], 'sessions': [], 'session-config': [{'name': 'niri-noctalia.kdl'}]}
    _, blockers = plan(helper, 'fedora45-niri-noctalia-lab', current)
    assert blockers == ['niri-noctalia.kdl already exists; it will not be overwritten']


def test_session_config_has_no_environment_overrides_and_starts_noctalia():
    text = TEMPLATES['niri-noctalia.kdl']
    code = '\n'.join(line.split('//')[0] for line in text.splitlines())
    assert 'environment' not in code and 'spawn-sh' not in code and 'include' not in code
    assert 'spawn-at-startup "noctalia"' in code
    assert 'Mod+Shift+E { quit; }' in code


@pytest.mark.skipif(shutil.which('niri') is None, reason='niri not installed on this machine')
def test_session_config_passes_niri_validate():
    result = subprocess.run(['niri', 'validate', '--config', str(LAB / 'templates/niri-noctalia.kdl')],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_transient_package_unit_does_not_pass_stdio_to_pid1():
    # Regression: PID1 reset the connection whenever the sandboxed helper ran
    # systemd-run --pipe (any stdio fd). Output now goes to a root-only log file.
    source = (LAB / 'desktopforge-lab-helper').read_text()
    body = source[source.index('def run_root('):source.index('def runner(')]
    code = body.split('"""', 2)[2]
    assert "'--pipe'" not in code and 'StandardOutput=truncate:' in code
    assert "PACKAGE_LOGS = STATE_DIR + '/package-logs'" in source


def test_rpm_queries_also_run_outside_the_seccomp_sandbox():
    # Regression: rpm -q calls fchown(), which @privileged filtering kills (SIGSYS).
    source = (LAB / 'desktopforge-lab-helper').read_text()
    body = source[source.index('def runner('):source.index('def validate_niri(')]
    assert 'return run_root(argv)' in body and 'def run_query' not in source
