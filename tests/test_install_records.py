"""Install records: strict schema, live verification, and recognition by the planner/GUI/CLI."""
import copy
import hashlib
import json
import os

import pytest

from desktopforge import install_records
from desktopforge.helper import records
from desktopforge.planning import build_plan

ENTRY_TEXT = b'[Desktop Entry]\nName=Niri + Noctalia (DesktopForge)\n'
CONFIG_TEXT = b'spawn-at-startup "noctalia"\n'
INSTALL_ID = 'ab' * 16


def make_record(**overrides):
    fields = dict(
        install_id=INSTALL_ID, recorded_at='2026-11-15T08:40:00Z', state='completed',
        producer='desktopforge-lab-helper', recipe_id='fedora45-niri-noctalia-lab', revision=2,
        plan_hash='c' * 64, action='org.desktopforge.lab.install-session', uid=1000,
        compositor='niri', shell='noctalia', session_id='desktopforge-niri-noctalia',
        session_name='Niri + Noctalia (DesktopForge)',
        files=[{'path': '/usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop', 'role': 'session-entry',
                'sha256': hashlib.sha256(ENTRY_TEXT).hexdigest()},
               {'path': '/etc/desktopforge/sessions/niri-noctalia.kdl', 'role': 'session-config',
                'sha256': hashlib.sha256(CONFIG_TEXT).hexdigest()}],
        installed=[{'name': 'niri', 'evr': '0:26.04-2.fc45', 'arch': 'x86_64', 'repo': 'fedora',
                    'installtid': '1794800000', 'key_id': '655a4b02f577861e'}],
        reused=['noctalia'])
    fields.update(overrides)
    return records.build(**fields)


# ---- schema ------------------------------------------------------------------------

def test_round_trip_is_canonical():
    record = make_record()
    assert records.parse(records.serialize(record)) == record
    assert records.serialize(record) == records.serialize(copy.deepcopy(record))


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(schema=2),
    lambda r: r.update(extra='x'),
    lambda r: r.pop('journal'),
    lambda r: r.update(install_id='../../etc'),
    lambda r: r.update(state='rolled_back'),
    lambda r: r['files'].append({'path': '/etc/gdm/custom.conf', 'role': 'session-config', 'sha256': 'a' * 64}),
    lambda r: r['files'].append({'path': '/usr/share/wayland-sessions/gnome.desktop', 'role': 'session-entry',
                                 'sha256': 'a' * 64}),
    lambda r: r['files'].append({'path': '/etc/desktopforge/sessions/../../shadow.kdl', 'role': 'session-config',
                                 'sha256': 'a' * 64}),
    lambda r: r['files'].append(dict(r['files'][0])),
    lambda r: r['session'].update(name='x\ny'),
    lambda r: r['recipe'].update(revision=True),
    lambda r: r['packages']['installed'][0].update(name='niri; rm -rf /'),
    lambda r: r.update(journal='other.jsonl'),
    lambda r: r.update(files=[]),  # completed without its session entry
])
def test_schema_rejects_malformed_or_out_of_namespace_records(mutate):
    record = make_record()
    mutate(record)
    with pytest.raises(records.RecordError):
        records.validate(record)


def test_failed_record_need_not_include_a_session_entry():
    assert make_record(state='failed_manual_recovery', files=[])['state'] == 'failed_manual_recovery'


def test_parse_rejects_non_json():
    with pytest.raises(records.RecordError):
        records.parse(b'{not json')


# ---- live verification ---------------------------------------------------------------

def install_tree(root, record=None, entry=ENTRY_TEXT, config=CONFIG_TEXT):
    (root / 'usr/share/wayland-sessions').mkdir(parents=True)
    (root / 'etc/desktopforge/sessions').mkdir(parents=True)
    (root / 'var/lib/desktopforge/installs').mkdir(parents=True)
    if entry is not None:
        (root / 'usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop').write_bytes(entry)
    if config is not None:
        (root / 'etc/desktopforge/sessions/niri-noctalia.kdl').write_bytes(config)
    record = record or make_record()
    (root / f'var/lib/desktopforge/installs/{record["install_id"]}.json').write_bytes(records.serialize(record))
    return root


PACKAGES = {'packages': [
    {'name': 'niri', 'status': 'installed', 'records': [
        {'epoch': 0, 'version': '26.04', 'release': '2.fc45', 'architecture': 'x86_64'}]},
    {'name': 'noctalia', 'status': 'installed', 'records': [
        {'epoch': 0, 'version': '5.5.0', 'release': '3.fc45', 'architecture': 'x86_64'}]}]}


def test_intact_installation(tmp_path):
    result = install_records.inspect_installations(install_tree(tmp_path), PACKAGES)
    (inst,) = result['installations']
    assert result['status'] == 'observed' and inst['status'] == 'intact'
    assert {f['status'] for f in inst['files']} == {'intact'}
    assert inst['packages'] == {'installed': [{'name': 'niri', 'evr': '0:26.04-2.fc45', 'arch': 'x86_64',
                                               'status': 'present'}],
                                'reused': [{'name': 'noctalia', 'status': 'present'}]}


def test_edited_config_is_modified(tmp_path):
    root = install_tree(tmp_path, config=b'spawn-at-startup "something-else"\n')
    (inst,) = install_records.inspect_installations(root, PACKAGES)['installations']
    assert inst['status'] == 'modified'


def test_removed_entry_is_incomplete_and_symlink_is_unsafe(tmp_path):
    root = install_tree(tmp_path, entry=None)
    (inst,) = install_records.inspect_installations(root, PACKAGES)['installations']
    assert inst['status'] == 'incomplete'
    (root / 'usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop').symlink_to('/etc/passwd')
    (inst,) = install_records.inspect_installations(root, PACKAGES)['installations']
    assert {f['path'].rsplit('/', 1)[1]: f['status'] for f in inst['files']}[
        'desktopforge-niri-noctalia.desktop'] == 'unsafe'


def test_removed_or_upgraded_package_marks_modified(tmp_path):
    root = install_tree(tmp_path)
    upgraded = copy.deepcopy(PACKAGES)
    upgraded['packages'][0]['records'][0]['release'] = '3.fc45'
    assert install_records.inspect_installations(root, upgraded)['installations'][0]['status'] == 'modified'
    removed = copy.deepcopy(PACKAGES)
    removed['packages'][1] = {'name': 'noctalia', 'status': 'not_installed', 'records': []}
    inst = install_records.inspect_installations(root, removed)['installations'][0]
    assert inst['status'] == 'modified' and inst['packages']['reused'][0]['status'] == 'missing'


def test_bad_records_are_ignored_with_an_issue(tmp_path):
    root = install_tree(tmp_path)
    installs = root / 'var/lib/desktopforge/installs'
    (installs / ('cd' * 16 + '.json')).write_text('{"schema": 1}')
    (installs / 'wrongname.json').write_bytes(records.serialize(make_record(install_id='ef' * 16)))
    (installs / ('aa' * 16 + '.json')).symlink_to(installs / f'{INSTALL_ID}.json')
    result = install_records.inspect_installations(root, PACKAGES)
    assert len(result['installations']) == 1 and len(result['issues']) == 3


def test_no_directory_means_no_installations(tmp_path):
    assert install_records.inspect_installations(tmp_path)['status'] == 'none'


# ---- planner, CLI and GUI recognition ---------------------------------------------------

@pytest.fixture
def inventory(tmp_path):
    from desktopforge.detection import detect_system
    base = json.loads(json.dumps(detect_system(root=tmp_path, environ={}, which=lambda name: None)))
    base['distribution'].update(id='fedora', version_id='45')
    return base


def with_installation(inventory, status):
    root_inv = copy.deepcopy(inventory)
    inst = install_records.summarize(make_record(), __import__('pathlib').Path('/nonexistent'), PACKAGES)
    inst['status'] = status
    root_inv['desktopforge_installations'] = {'installations': [inst]}
    root_inv['sessions']['wayland'].append({'id': 'desktopforge-niri-noctalia', 'name': 'Niri + Noctalia (DesktopForge)',
                                            'path': '/usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop'})
    return root_inv


def test_planner_recognizes_its_own_intact_installation(inventory):
    plan = build_plan(with_installation(inventory, 'intact'), 'niri', 'noctalia')
    assert plan['status'] == 'installed' and plan['session_id_preview'] == 'desktopforge-niri-noctalia'
    assert plan['blockers'] == [] and plan['operations'] == []
    assert plan['existing_installation']['install_id'] == INSTALL_ID


def test_foreign_session_with_same_id_still_gets_a_new_id(inventory):
    inv = with_installation(inventory, 'intact')
    inv['desktopforge_installations'] = {'installations': []}
    assert build_plan(inv, 'niri', 'noctalia')['session_id_preview'] == 'desktopforge-niri-noctalia-2'


@pytest.mark.parametrize('status', ['modified', 'incomplete'])
def test_damaged_installation_is_blocked_with_specifics(inventory, status):
    plan = build_plan(with_installation(inventory, status), 'niri', 'noctalia')
    assert plan['status'] == 'blocked' and plan['session_id_preview'] == 'desktopforge-niri-noctalia'
    assert plan['blockers'][0].startswith(f'DesktopForge installation {INSTALL_ID} of this combination is {status}')
    assert plan['operations'] == []


def test_other_combinations_are_unaffected(inventory):
    plan = build_plan(with_installation(inventory, 'intact'), 'niri', 'dms')
    assert plan['status'] == 'blocked' and plan['existing_installation'] is None


def test_cli_exits_zero_for_an_intact_installation(monkeypatch, inventory, capsys):
    from desktopforge import cli
    monkeypatch.setattr(cli, 'detect_system', lambda: with_installation(inventory, 'intact'))
    assert cli.main(['plan', '--compositor', 'niri', '--shell', 'noctalia']) == 0
    out = capsys.readouterr().out
    assert 'plan: installed' in out and f'Installed by DesktopForge: Niri + Noctalia (DesktopForge) (install {INSTALL_ID}' in out
    monkeypatch.setattr(cli, 'detect_system', lambda: with_installation(inventory, 'modified'))
    assert cli.main(['plan', '--compositor', 'niri', '--shell', 'noctalia']) == 1


def test_installed_but_cannot_render_is_installed_with_a_warning(inventory):
    inv = with_installation(inventory, 'intact')
    inv['rendering'] = {'status': 'software-only', 'nodes': [{'renderer': 'llvmpipe (LLVM 21)'}]}
    plan = build_plan(inv, 'niri', 'noctalia')
    assert plan['status'] == 'installed' and plan['blockers'] == []
    assert len(plan['warnings']) == 1 and 'software rendering' in plan['warnings'][0]
    inv['rendering'] = {'status': 'hardware', 'nodes': []}
    assert build_plan(inv, 'niri', 'noctalia')['warnings'] == []


def test_failed_last_launch_becomes_a_warning_on_an_intact_install(tmp_path, inventory):
    from desktopforge import loginsession
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}
    loginsession.record_launch(env, 'niri-noctalia', 'no-display', 'The compositor had no usable display.',
                               now=1794800000)
    launches = install_records.read_launches(install_records.launch_state_directory(env))
    assert launches['desktopforge-niri-noctalia']['result'] == 'no-display'
    inv = with_installation(inventory, 'intact')
    inv['rendering'] = {'status': 'hardware', 'nodes': []}
    install_records.attach_launches(inv['desktopforge_installations'], launches)
    plan = build_plan(inv, 'niri', 'noctalia')
    assert plan['status'] == 'installed'
    assert plan['warnings'] == ['The last login to Niri + Noctalia (DesktopForge) (2026-11-16T03:33:20Z) did not '
                                'start: The compositor had no usable display. The login screen may still preselect '
                                'this session; choose another session there.']
    loginsession.record_launch(env, 'niri-noctalia', 'started', 'ok', now=1794800100)
    install_records.attach_launches(inv['desktopforge_installations'],
                                    install_records.read_launches(install_records.launch_state_directory(env)))
    assert build_plan(inv, 'niri', 'noctalia')['warnings'] == []


def test_malformed_launch_state_is_ignored(tmp_path):
    directory = tmp_path / 'desktopforge/launches'
    directory.mkdir(parents=True)
    (directory / 'a.json').write_text('{"session_id": "gnome", "events": [{"time": "x", "result": "started"}]}')
    (directory / 'b.json').write_text('not json')
    (directory / 'c.json').symlink_to(directory / 'a.json')
    assert install_records.read_launches(directory) == {}
    assert install_records.launch_state_directory({'HOME': 'relative'}) is None


# ---- every recorded package is re-verified, not just the tracked ones ----------------------

import subprocess  # noqa: E402


def rpm(lines, code=None):
    text = '\n'.join(lines) + '\n'
    missing = sum(l.startswith('package ') for l in lines)
    return lambda argv, **kw: subprocess.CompletedProcess(argv, missing if code is None else code, text, '')


ALL_PRESENT = ['niri\t0:26.04-2.fc45\tx86_64', 'noctalia\t0:5.5.0-3.fc45\tx86_64']


def deps_record():
    return make_record(installed=[
        {'name': 'niri', 'evr': '0:26.04-2.fc45', 'arch': 'x86_64', 'repo': 'fedora', 'installtid': '1', 'key_id': None},
        {'name': 'libseat', 'evr': '0:0.9.3-2.fc45', 'arch': 'x86_64', 'repo': 'fedora', 'installtid': '1', 'key_id': None}])


def test_removed_dependency_marks_installation_modified(tmp_path):
    root = install_tree(tmp_path, record=deps_record())
    runner = rpm(ALL_PRESENT + ['package libseat is not installed'])
    (inst,) = install_records.inspect_installations(root, PACKAGES, runner=runner)['installations']
    assert inst['status'] == 'modified'
    assert {p['name']: p['status'] for p in inst['packages']['installed']} == {'libseat': 'missing', 'niri': 'present'}


def test_all_dependencies_present_is_intact(tmp_path):
    root = install_tree(tmp_path, record=deps_record())
    runner = rpm(ALL_PRESENT + ['libseat\t0:0.9.3-2.fc45\tx86_64'])
    assert install_records.inspect_installations(root, PACKAGES, runner=runner)['installations'][0]['status'] == 'intact'


@pytest.mark.parametrize('runner', [
    rpm(ALL_PRESENT),                                           # libseat unaccounted for
    rpm(ALL_PRESENT + ['package libseat is not installed'], code=0),  # status does not match
    rpm(['garbage line']),
    lambda argv, **kw: (_ for _ in ()).throw(OSError('no rpm')),
])
def test_unclear_package_state_is_unverified_not_intact(tmp_path, runner):
    root = install_tree(tmp_path, record=deps_record())
    empty_inventory = {'packages': []}
    (inst,) = install_records.inspect_installations(root, empty_inventory, runner=runner)['installations']
    assert inst['status'] == 'unverified'


def test_planner_explains_unverified(inventory):
    inv = with_installation(inventory, 'unverified')
    inv['desktopforge_installations']['installations'][0]['packages']['installed'][0]['status'] = 'unknown'
    plan = build_plan(inv, 'niri', 'noctalia')
    assert plan['status'] == 'blocked' and 'package niri could not be checked' in plan['blockers'][0]
