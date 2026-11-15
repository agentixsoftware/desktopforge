"""Repair: restore exactly what was recorded; never overwrite edits or change versions."""
import copy
import hashlib
import os
from pathlib import Path
import runpy

import pytest

from desktopforge import install_records, labclient
from desktopforge.helper import executor, fsops, records, repair, sessions
from desktopforge.helper.journal import Journal

REPO = Path(__file__).resolve().parents[1]
ENTRY = '/usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop'
CONFIG = '/etc/desktopforge/sessions/niri-noctalia.kdl'
INSTALL_ID = 'ab' * 16
RECIPE = 'fedora45-niri-noctalia-lab'


@pytest.fixture(scope='module')
def helper():
    return runpy.run_path(str(REPO / 'lab/helper/desktopforge-lab-helper'))


@pytest.fixture(scope='module')
def recipe_plan(helper):
    templates = {'niri-noctalia.kdl': (REPO / 'lab/helper/templates/niri-noctalia.kdl').read_text()}
    plan, _ = helper['build_plan'](RECIPE, {'markers': [], 'sessions': [], 'session-config': []}, {}, sessions.render,
                                   sessions.session_filename, resolve=lambda p, r: ([], []), templates=templates,
                                   rendering=lambda: {'status': 'hardware', 'nodes': []})
    return plan


@pytest.fixture(scope='module')
def expected(helper, recipe_plan):
    return repair.expected_files(recipe_plan, helper['TARGETS'], sessions.render, sessions.session_filename,
                                 helper['ALLOWED_COMMANDS'])


def record_for(expected, installed=None, reused=('noctalia',)):
    files = [{'path': path, 'role': 'session-entry' if path == ENTRY else 'session-config', 'sha256': digest}
             for path, (_op, digest) in expected.items()]
    return records.build(
        install_id=INSTALL_ID, recorded_at='2026-11-15T19:30:00Z', state='completed', producer='desktopforge-lab-helper',
        recipe_id=RECIPE, revision=2, plan_hash='c' * 64, action='org.desktopforge.lab.install-session', uid=1000,
        compositor='niri', shell='noctalia', session_id='desktopforge-niri-noctalia',
        session_name='Niri + Noctalia (DesktopForge)', files=files,
        installed=installed if installed is not None else [
            {'name': 'niri', 'evr': '0:26.04-2.fc45', 'arch': 'x86_64', 'repo': 'fedora', 'installtid': '1',
             'key_id': '655a4b02f577861e'}],
        reused=list(reused))


PRESENT = {'niri': [{'evr': '0:26.04-2.fc45', 'arch': 'x86_64'}], 'noctalia': [{'evr': '0:5.5.0-3.fc45', 'arch': 'x86_64'}]}
INTACT = {ENTRY: 'intact', CONFIG: 'intact'}


def no_resolve(names, repos):
    raise AssertionError('nothing should be resolved')


def ops(result):
    return [op['op'] for op in result['operations']]


def test_intact_installation_needs_nothing(expected, recipe_plan):
    result = repair.plan_repair(record_for(expected), INTACT, expected, PRESENT, no_resolve, recipe_plan)
    assert result['operations'] == [] and result['blockers'] == ['Nothing needs repair: the installation is intact.']


@pytest.mark.parametrize('missing, expected_ops', [
    ({ENTRY}, ['register_session']),
    ({CONFIG}, ['create_file', 'validate_config']),
    ({ENTRY, CONFIG}, ['create_file', 'validate_config', 'register_session']),
])
def test_missing_files_are_restored_in_safe_order(expected, recipe_plan, missing, expected_ops):
    states = {path: ('missing' if path in missing else 'intact') for path in INTACT}
    result = repair.plan_repair(record_for(expected), states, expected, PRESENT, no_resolve, recipe_plan)
    assert ops(result) == expected_ops and result['blockers'] == []
    assert sorted(result['restore']['files']) == sorted(missing)


@pytest.mark.parametrize('state, fragment', [('modified', 'was edited; repair does not overwrite it'),
                                             ('unsafe', 'is unsafe; repair will not replace it'),
                                             ('unreadable', 'is unreadable')])
def test_edited_or_replaced_files_block(expected, recipe_plan, state, fragment):
    result = repair.plan_repair(record_for(expected), {ENTRY: state, CONFIG: 'intact'}, expected, PRESENT,
                                no_resolve, recipe_plan)
    assert result['operations'] == [] and fragment in result['blockers'][0]


def test_file_is_not_restored_if_the_recipe_would_differ(expected, recipe_plan):
    record = record_for(expected)
    record['files'][0]['sha256'] = 'f' * 64  # recorded content no longer matches what the recipe renders
    states = {record['files'][0]['path']: 'missing', record['files'][1]['path']: 'intact'}
    result = repair.plan_repair(record, states, expected, PRESENT, no_resolve, recipe_plan)
    assert result['operations'] == [] and 'would now produce different content' in result['blockers'][0]


NIRI = {'name': 'niri', 'arch': 'x86_64', 'evr': '0:26.04-2.fc45', 'repo': 'fedora'}


def test_missing_package_is_reinstalled_at_the_recorded_version(expected, recipe_plan):
    calls = []

    def resolve(names, repos):
        calls.append((names, repos))
        return [NIRI], []
    result = repair.plan_repair(record_for(expected), INTACT, expected, {'noctalia': PRESENT['noctalia']},
                                resolve, recipe_plan)
    assert calls == [(['niri'], ['fedora', 'updates'])] and result['blockers'] == []
    assert result['operations'][0] == {'op': 'install_packages', 'packages': ['niri'],
                                       'repositories': ['fedora', 'updates'], 'expected': [NIRI]}


def test_unavailable_recorded_version_blocks(expected, recipe_plan):
    result = repair.plan_repair(record_for(expected), INTACT, expected, {'noctalia': PRESENT['noctalia']},
                                lambda n, r: ([dict(NIRI, evr='0:26.04-5.fc45')], []), recipe_plan)
    assert 'no longer available (the repositories offer 0:26.04-5.fc45); repair does not change versions' \
        in result['blockers'][0]


def test_unrecorded_extra_packages_block(expected, recipe_plan):
    extra = {'name': 'surprise', 'arch': 'x86_64', 'evr': '0:1-1.fc45', 'repo': 'fedora'}
    result = repair.plan_repair(record_for(expected), INTACT, expected, {'noctalia': PRESENT['noctalia']},
                                lambda n, r: ([NIRI, extra], []), recipe_plan)
    assert 'did not record: surprise' in result['blockers'][0]


def test_missing_reused_package_is_reinstalled(expected, recipe_plan):
    noctalia = {'name': 'noctalia', 'arch': 'x86_64', 'evr': '0:5.5.0-3.fc45', 'repo': 'updates'}
    result = repair.plan_repair(record_for(expected), INTACT, expected, {'niri': PRESENT['niri']},
                                lambda n, r: ([noctalia], []), recipe_plan)
    assert result['operations'][0]['packages'] == ['noctalia'] and result['blockers'] == []


def test_updated_package_is_not_considered_missing(expected, recipe_plan):
    updated = {'niri': [{'evr': '0:26.04-9.fc45', 'arch': 'x86_64'}], 'noctalia': PRESENT['noctalia']}
    result = repair.plan_repair(record_for(expected), INTACT, expected, updated, no_resolve, recipe_plan)
    assert result['operations'] == []


# ---- executor end to end ------------------------------------------------------------

def test_repair_restores_byte_identical_files(tmp_path, expected, recipe_plan):
    dirs = {}
    for name in ('sessions', 'session-config', 'journal'):
        (tmp_path / name).mkdir()
        dirs[name] = os.open(tmp_path / name, fsops.DIR_FLAGS)
    try:
        record = record_for(expected)
        result = repair.plan_repair(record, {ENTRY: 'missing', CONFIG: 'missing'}, expected, PRESENT, no_resolve,
                                    recipe_plan)
        plan = {'recipe': 'repair-' + INSTALL_ID, 'revision': 1, 'operations': result['operations']}
        adapters = executor.Adapters(None, None, {'niri': lambda fd, name: (True, 'ok')})
        outcome = executor.execute(plan, Journal(dirs['journal']), {k: dirs[k] for k in ('sessions', 'session-config')},
                                   {'/usr/local/libexec/desktopforge-lab/desktopforge-session',
                                    '/usr/local/libexec/desktopforge-lab/desktopforge-session niri-noctalia'}, adapters)
        assert outcome['state'] == 'completed'
        for item in record['files']:
            local = tmp_path / ('sessions' if item['role'] == 'session-entry' else 'session-config') / Path(item['path']).name
            assert hashlib.sha256(local.read_bytes()).hexdigest() == item['sha256']
    finally:
        for fd in dirs.values():
            os.close(fd)


# ---- records, reader, helper and GUI ----------------------------------------------------

def make_repair(**overrides):
    fields = dict(repair_id='cd' * 16, install_id=INSTALL_ID, recorded_at='2026-11-15T19:40:00Z', state='completed',
                  producer='desktopforge-lab-helper', action='org.desktopforge.lab.repair-session', uid=1000,
                  files=[{'path': ENTRY}], packages=[{'name': 'niri', 'evr': '0:26.04-2.fc45'}])
    fields.update(overrides)
    return records.build_repair(**fields)


@pytest.mark.parametrize('mutate', [lambda r: r.update(kind='removal'),
                                    lambda r: r['restored']['files'].append({'path': '/etc/shadow'}),
                                    lambda r: r['restored']['packages'].append({'name': 'x', 'evr': None})])
def test_repair_schema_is_strict(mutate):
    record = make_repair()
    mutate(record)
    with pytest.raises(records.RecordError):
        records.validate_repair(record)


def test_reader_attaches_the_last_repair(tmp_path):
    from tests.test_install_records import PACKAGES, install_tree
    root = install_tree(tmp_path)
    fix = make_repair()
    (root / f'var/lib/desktopforge/installs/{fix["repair_id"]}.repair.json').write_bytes(records.serialize_repair(fix))
    result = install_records.inspect_installations(root, PACKAGES)
    assert result['issues'] == [] and result['installations'][0]['last_repair']['repair_id'] == 'cd' * 16


def test_helper_repair_plan_guards_and_text(helper, expected):
    record = record_for(expected)
    common = (lambda r: None, lambda p: expected, lambda *a: {'operations': [], 'blockers': [], 'restore': {}})
    with pytest.raises(helper['Rejected']):
        helper['build_repair_plan']('repair-' + 'x' * 32, {INSTALL_ID: record}, set(), {}, {}, None, *common)
    _, blockers = helper['build_repair_plan']('repair-' + INSTALL_ID, {INSTALL_ID: record}, {INSTALL_ID}, {}, {},
                                              None, *common)
    assert 'was removed' in blockers[0]
    old = copy.deepcopy(record)
    old['recipe']['revision'] = 1
    _, blockers = helper['build_repair_plan']('repair-' + INSTALL_ID, {INSTALL_ID: old}, set(), {}, {}, None, *common)
    assert 'recipe changed since installation (revision 1)' in blockers[0]
    assert helper['action_for']('repair-' + INSTALL_ID) == 'org.desktopforge.lab.repair-session'
    text = helper['summarize']({'recipe': 'repair-' + INSTALL_ID, 'targets': helper['TARGETS'], 'operations': [
        {'op': 'install_packages', 'expected': [NIRI]}, {'op': 'create_file', 'target': 'session-config',
                                                          'name': 'niri-noctalia.kdl'}]})
    assert text[0] == 'Reinstall missing packages at their recorded versions: niri 0:26.04-2.fc45'
    assert text[-1] == 'Edited files are never overwritten, and installed versions are not changed.'


def test_repair_offered_only_for_damaged_installations():
    damaged = {'existing_installation': {'install_id': INSTALL_ID, 'status': 'modified'}}
    assert labclient.repair_action(damaged, True) == 'repair-' + INSTALL_ID
    assert labclient.repair_action(damaged, False) is None
    assert labclient.repair_action({'existing_installation': {'install_id': INSTALL_ID, 'status': 'intact'}}, True) is None


def test_gui_shows_repair_button_for_a_damaged_installation(app, inventory, expected):
    from tests.test_gui_lab import FakeClient, close, finish, make_window
    from tests.test_install_records import PACKAGES
    damaged = copy.deepcopy(inventory)
    summary = install_records.summarize(record_for(expected), Path('/nonexistent'), PACKAGES)
    summary['status'] = 'incomplete'
    damaged['desktopforge_installations'] = {'installations': [summary]}
    damaged['rendering'] = {'status': 'hardware', 'nodes': []}
    client = FakeClient()
    widget = make_window(damaged, client)
    try:
        from tests.test_gui import scan
        scan(widget)
        assert not widget.repair_button.isHidden() and widget.repair_button.isEnabled()
        assert widget.install_button.text() == 'Remove from VM lab…'
        widget.refresh_inventory = lambda: None
        widget.repair_button.click()
        finish(app, widget)
        assert client.calls[0] == ('preview', 'repair-' + INSTALL_ID) and widget.dialogs[0][1] == 'repair'
    finally:
        close(app, widget)


from tests.test_gui import app, inventory  # noqa: E402,F401


def test_repair_button_hidden_for_intact_installation(app, inventory, expected):
    from tests.test_gui_lab import FakeClient, close, make_window
    from tests.test_gui import scan
    from tests.test_install_records import PACKAGES
    intact = copy.deepcopy(inventory)
    summary = install_records.summarize(record_for(expected), Path('/nonexistent'), PACKAGES)
    summary['status'] = 'intact'
    intact['desktopforge_installations'] = {'installations': [summary]}
    intact['rendering'] = {'status': 'hardware', 'nodes': []}
    widget = make_window(intact, FakeClient())
    try:
        scan(widget)
        assert widget.repair_button.isHidden()
    finally:
        close(app, widget)
