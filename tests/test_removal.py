"""Removal of a recorded installation: only what it created or added, nothing it found."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy

import pytest

from desktopforge import install_records
from desktopforge.helper import executor, fsops, pkgtx, records, removal
from desktopforge.helper.journal import Journal
from tests.test_install_records import CONFIG_TEXT, ENTRY_TEXT, INSTALL_ID, PACKAGES, install_tree, make_record

ENTRY = '/usr/share/wayland-sessions/desktopforge-niri-noctalia.desktop'
CONFIG = '/etc/desktopforge/sessions/niri-noctalia.kdl'
NIRI_ROW = {'name': 'niri', 'arch': 'x86_64', 'evr': '0:26.04-2.fc45', 'repo': 'fedora'}


# ---- fsops.remove_file ---------------------------------------------------------------

@pytest.fixture
def folder(tmp_path):
    base = tmp_path / 'd'
    base.mkdir()
    fd = os.open(base, fsops.DIR_FLAGS)
    yield base, fd
    os.close(fd)


def test_remove_file_requires_the_recorded_content(folder):
    base, fd = folder
    (base / 'f').write_bytes(b'abc')
    with pytest.raises(fsops.Mismatch, match='modified'):
        fsops.remove_file(fd, 'f', hashlib.sha256(b'other').hexdigest())
    assert (base / 'f').exists()
    fsops.remove_file(fd, 'f', hashlib.sha256(b'abc').hexdigest())
    assert not (base / 'f').exists()


def test_remove_file_never_follows_or_removes_symlinks(folder, tmp_path):
    base, fd = folder
    victim = tmp_path / 'victim'
    victim.write_bytes(b'abc')
    (base / 'f').symlink_to(victim)
    with pytest.raises(fsops.Mismatch):
        fsops.remove_file(fd, 'f', hashlib.sha256(b'abc').hexdigest())
    assert victim.exists() and (base / 'f').is_symlink()


def test_remove_file_reports_missing(folder):
    _, fd = folder
    with pytest.raises(fsops.Mismatch, match='missing'):
        fsops.remove_file(fd, 'f', 'a' * 64)


# ---- planner ---------------------------------------------------------------------------

def resolver(rows=None, blockers=()):
    calls = []

    def resolve(names):
        calls.append(names)
        return (rows if rows is not None else [dict(NIRI_ROW, repo='@System')]), list(blockers)
    resolve.calls = calls
    return resolve


INTACT = {ENTRY: 'intact', CONFIG: 'intact'}
PRESENT = {'niri': [{'evr': '0:26.04-2.fc45', 'arch': 'x86_64'}]}


def test_plan_removes_files_entry_first_then_added_packages():
    plan = removal.plan_removal(make_record(), INTACT, PRESENT, resolver())
    assert [(op['op'], op.get('path')) for op in plan['operations']] == [
        ('remove_file', ENTRY), ('remove_file', CONFIG), ('remove_packages', None)]
    assert plan['operations'][2]['packages'] == ['niri'] and plan['blockers'] == []
    assert plan['kept'] == {'files': [], 'packages': [{'name': 'noctalia', 'evr': None, 'reason': 'reused'}]}


def test_edited_or_replaced_files_are_kept_with_reasons():
    plan = removal.plan_removal(make_record(), {ENTRY: 'intact', CONFIG: 'modified'}, PRESENT, resolver())
    assert [op.get('path') for op in plan['operations'] if op['op'] == 'remove_file'] == [ENTRY]
    assert plan['kept']['files'] == [{'path': CONFIG, 'reason': 'modified'}]
    plan = removal.plan_removal(make_record(), {ENTRY: 'unsafe', CONFIG: 'missing'}, PRESENT, resolver())
    assert {f['reason'] for f in plan['kept']['files']} == {'unsafe', 'missing'}


def test_reused_packages_are_never_removed():
    record = make_record(installed=[], reused=['niri', 'noctalia'])
    resolve = resolver()
    plan = removal.plan_removal(record, INTACT, PRESENT, resolve)
    assert resolve.calls == [] and all(op['op'] == 'remove_file' for op in plan['operations'])


def test_missing_package_is_kept_as_not_installed():
    plan = removal.plan_removal(make_record(), INTACT, {}, resolver())
    assert not any(op['op'] == 'remove_packages' for op in plan['operations'])
    assert {'name': 'niri', 'evr': '0:26.04-2.fc45', 'reason': 'not-installed'} in plan['kept']['packages']


def test_package_updated_since_installation_is_still_removed_at_its_current_version():
    updated = {'niri': [{'evr': '0:26.04-3.fc45', 'arch': 'x86_64'}]}
    resolve = resolver(rows=[dict(NIRI_ROW, evr='0:26.04-3.fc45')])
    plan = removal.plan_removal(make_record(), INTACT, updated, resolve)
    (op,) = [o for o in plan['operations'] if o['op'] == 'remove_packages']
    assert op['expected'][0]['evr'] == '0:26.04-3.fc45' and plan['blockers'] == []


def test_dependents_or_version_mismatch_block():
    plan = removal.plan_removal(make_record(), INTACT, PRESENT, resolver(blockers=['dependents']))
    assert plan['blockers'] == ['dependents']
    plan = removal.plan_removal(make_record(), INTACT, PRESENT,
                                resolver(rows=[dict(NIRI_ROW, evr='0:26.04-9.fc45')]))
    assert 'exactly the recorded packages' in plan['blockers'][0]


def test_nothing_removable_is_blocked():
    plan = removal.plan_removal(make_record(installed=[]), {ENTRY: 'modified', CONFIG: 'missing'}, {}, resolver())
    assert plan['operations'] == [] and plan['blockers'] == ['Nothing recorded by this installation can be removed safely.']


# ---- DNF5 removal ------------------------------------------------------------------------

REMOVE_TABLE = """Package            Arch   Version         Repository      Size
Removing:
 niri               x86_64 0:26.04-2.fc45  fedora      22.8 MiB
{extra}
Transaction Summary:
 Removing:           1 package
"""


def test_remove_argv_is_fixed():
    assert pkgtx.dnf5_remove_argv(['niri'], simulate=True) == [
        '/usr/bin/dnf5', 'remove', '--assumeno', '--setopt=clean_requirements_on_remove=False', '--', 'niri']
    with pytest.raises(pkgtx.PackageError):
        pkgtx.dnf5_remove_argv(['--oldinstallonly'], simulate=True)


def test_dependents_block_removal():
    text = REMOVE_TABLE.format(extra='Removing dependent packages:\n mypkg x86_64 0:1-1.fc45 fedora 1.0 MiB')
    rows, blockers = pkgtx.resolve_removal(['niri'], lambda argv: (1, text))
    assert [r['name'] for r in rows] == ['niri'] and 'Removing dependent packages' in blockers[0]


def test_removal_of_unrequested_packages_blocks():
    text = REMOVE_TABLE.format(extra=' other x86_64 0:1-1.fc45 fedora 1.0 MiB')
    _, blockers = pkgtx.resolve_removal(['niri'], lambda argv: (1, text))
    assert blockers == ['Removal would also remove packages DesktopForge did not install: other']


class FakeRemover:
    def __init__(self, status=0, leave=()):
        self.installed, self.status, self.leave, self.calls = {'niri'}, status, set(leave), []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0] == pkgtx.DNF5 and '--assumeno' in argv:
            return 1, REMOVE_TABLE.format(extra='')
        if argv[0] == pkgtx.DNF5:
            self.installed &= self.leave
            return self.status, 'Complete!'
        names = argv[argv.index('--') + 1:]
        lines = [f'{n}\t0:26.04-2.fc45\tx86_64\t1\tnone' if n in self.installed else f'package {n} is not installed'
                 for n in names]
        return sum(n not in self.installed for n in names), '\n'.join(lines) + '\n'


def test_remove_verifies_packages_are_gone():
    fake = FakeRemover()
    pkgtx.remove(['niri'], [NIRI_ROW], fake)
    assert fake.installed == set()


def test_remove_that_leaves_packages_is_transaction_ran():
    with pytest.raises(pkgtx.TransactionRan, match='still installed: niri'):
        pkgtx.remove(['niri'], [NIRI_ROW], FakeRemover(leave={'niri'}))


def test_remove_refuses_when_resolution_changed():
    fake = FakeRemover()
    with pytest.raises(pkgtx.PackageError, match='changed since preview'):
        pkgtx.remove(['niri'], [dict(NIRI_ROW, evr='0:26.04-1.fc45')], fake)
    assert not any('--assumeyes' in c for c in fake.calls)


# ---- executor -----------------------------------------------------------------------------

@pytest.fixture
def lab(tmp_path):
    root = install_tree(tmp_path)
    fds = {'sessions': os.open(root / 'usr/share/wayland-sessions', fsops.DIR_FLAGS),
           'session-config': os.open(root / 'etc/desktopforge/sessions', fsops.DIR_FLAGS)}
    (tmp_path / 'journal').mkdir()
    jfd = os.open(tmp_path / 'journal', fsops.DIR_FLAGS)
    yield root, fds, jfd
    for fd in [*fds.values(), jfd]:
        os.close(fd)


def removal_plan(fake=None):
    plan = removal.plan_removal(make_record(), INTACT, PRESENT, resolver(rows=[NIRI_ROW]))
    return {'recipe': 'remove-' + INSTALL_ID, 'revision': 1, 'operations': plan['operations']}


def test_executor_removes_files_and_packages(lab):
    root, fds, jfd = lab
    fake = FakeRemover()
    result = executor.execute(removal_plan(), Journal(jfd), fds, adapters=executor.Adapters(fake, 'a' * 16))
    assert result['state'] == 'completed' and result['rolled_back'] is False
    assert not (root / ENTRY.lstrip('/')).exists() and not (root / CONFIG.lstrip('/')).exists()
    assert fake.installed == set()


def test_edited_file_between_preview_and_apply_stops_before_packages(lab):
    root, fds, jfd = lab
    (root / CONFIG.lstrip('/')).write_bytes(b'edited\n')
    fake = FakeRemover()
    result = executor.execute(removal_plan(), Journal(jfd), fds, adapters=executor.Adapters(fake, 'a' * 16))
    assert result['state'] == 'failed_manual_recovery' and result['failed_index'] == 1
    assert (root / CONFIG.lstrip('/')).read_bytes() == b'edited\n' and fake.installed == {'niri'}
    assert 'removed sessions/desktopforge-niri-noctalia.desktop' in result['recovery']


def test_package_removal_failure_reports_unknown_state(lab):
    _, fds, jfd = lab
    result = executor.execute(removal_plan(), Journal(jfd), fds,
                              adapters=executor.Adapters(FakeRemover(leave={'niri'}), 'a' * 16))
    assert result['state'] == 'failed_manual_recovery' and result['rolled_back'] is False
    assert 'rpm -q niri' in result['recovery']


# ---- removal records and recognition ----------------------------------------------------------

def make_removal(**overrides):
    fields = dict(removal_id='cd' * 16, install_id=INSTALL_ID, recorded_at='2026-11-16T10:00:00Z', state='completed',
                  producer='desktopforge-lab-helper', action='org.desktopforge.lab.remove-session', uid=1000,
                  removed_files=[{'path': ENTRY}, {'path': CONFIG}],
                  removed_packages=[{'name': 'niri', 'evr': '0:26.04-2.fc45'}],
                  kept_files=[], kept_packages=[{'name': 'noctalia', 'evr': None, 'reason': 'reused'}])
    fields.update(overrides)
    return records.build_removal(**fields)


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(kind='install'),
    lambda r: r['removed']['files'].append({'path': '/etc/passwd'}),
    lambda r: r['kept']['files'].append({'path': CONFIG, 'reason': 'because'}),
    lambda r: r.update(journal='x.jsonl'),
])
def test_removal_schema_is_strict(mutate):
    record = make_removal()
    mutate(record)
    with pytest.raises(records.RecordError):
        records.validate_removal(record)


def test_removed_installation_is_recognized_and_no_longer_installed(tmp_path):
    root = install_tree(tmp_path, entry=None, config=None)
    removal_record = make_removal()
    (root / f'var/lib/desktopforge/installs/{removal_record["removal_id"]}.removal.json').write_bytes(
        records.serialize_removal(removal_record))
    result = install_records.inspect_installations(root, PACKAGES)
    (inst,) = result['installations']
    assert inst['status'] == 'removed' and inst['removal']['removal_id'] == 'cd' * 16
    assert result['issues'] == []
    assert install_records.installation_for({'desktopforge_installations': result}, 'niri', 'noctalia') is None


def test_partial_removal_is_reported(tmp_path):
    root = install_tree(tmp_path, entry=None)
    partial = make_removal(state='failed_manual_recovery', removed_files=[{'path': ENTRY}], removed_packages=[],
                           kept_files=[{'path': CONFIG, 'reason': 'modified'}])
    (root / f'var/lib/desktopforge/installs/{partial["removal_id"]}.removal.json').write_bytes(
        records.serialize_removal(partial))
    (inst,) = install_records.inspect_installations(root, PACKAGES)['installations']
    assert inst['status'] == 'partially-removed'


# ---- lab helper -------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def helper():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'lab/helper/desktopforge-lab-helper'))


def test_helper_removal_plan_and_preview_text(helper):
    record = make_record()
    plan, blockers = helper['build_removal_plan']('remove-' + INSTALL_ID, {INSTALL_ID: record}, set(),
                                                  INTACT, PRESENT, resolver(rows=[NIRI_ROW]), removal.plan_removal)
    assert blockers == [] and plan['install_id'] == INSTALL_ID
    assert helper['action_for']('remove-' + INSTALL_ID) == 'org.desktopforge.lab.remove-session'
    text = '\n'.join(helper['summarize'](plan))
    assert f'Remove {ENTRY} (unchanged since installation)' in text
    assert 'Remove packages this installation added: niri 0:26.04-2.fc45' in text
    assert 'Fedora\'s own "Niri" login session' in text
    assert 'Keep package noctalia: it was already installed before this installation' in text
    assert '~/.local/state/noctalia' in text and 'choose another session' in text


@pytest.mark.parametrize('recipe', ['remove-' + 'x' * 32, 'remove-' + 'ab' * 15, 'remove-../../etc'])
def test_helper_rejects_unknown_installations(helper, recipe):
    with pytest.raises(helper['Rejected']):
        helper['build_removal_plan'](recipe, {INSTALL_ID: make_record()}, set(), {}, {}, resolver(),
                                     removal.plan_removal)


def test_helper_refuses_repeat_removal(helper):
    _, blockers = helper['build_removal_plan']('remove-' + INSTALL_ID, {INSTALL_ID: make_record()}, {INSTALL_ID},
                                               INTACT, PRESENT, resolver(), removal.plan_removal)
    assert blockers == [f'Installation {INSTALL_ID} was already removed.']


def test_helper_removal_record(helper):
    plan, _ = helper['build_removal_plan']('remove-' + INSTALL_ID, {INSTALL_ID: make_record()}, set(),
                                           INTACT, PRESENT, resolver(rows=[NIRI_ROW]), removal.plan_removal)
    result = {'state': 'completed', 'created': [
        {'kind': 'removed-file', 'target': 'sessions', 'name': 'desktopforge-niri-noctalia.desktop'},
        {'kind': 'removed-file', 'target': 'session-config', 'name': 'niri-noctalia.kdl'},
        {'kind': 'removed-packages', 'packages': [{'name': 'niri', 'evr': '0:26.04-2.fc45'}]}]}
    out = helper['removal_record'](records, plan, result, 'ef' * 16, 1000, '2026-11-16T10:00:00Z')
    assert out['removed']['files'] == [{'path': CONFIG}, {'path': ENTRY}]
    assert out['kept']['packages'] == [{'name': 'noctalia', 'evr': None, 'reason': 'reused'}]


def test_reinstall_after_removal_is_not_blocked_as_already_installed(helper):
    from desktopforge.helper import sessions
    installed = [dict(make_record(), removed=True)]
    _, blockers = helper['build_plan'](make_record()['recipe']['id'], {'markers': [], 'sessions': []}, {},
                                       sessions.render, sessions.session_filename, resolve=lambda p, r: ([], []),
                                       templates={'niri-noctalia.kdl': 'x'}, installed=installed,
                                       rendering=lambda: {'status': 'hardware', 'nodes': []})
    assert not any('Already installed' in b for b in blockers)


def test_real_dnf5_removal_output_parses_to_the_seven_recorded_packages():
    # Captured in the guest: dnf5 remove --assumeno for the packages DesktopForge installed.
    text = (Path(__file__).parent / 'fixtures/dnf5/remove-niri-noctalia.txt').read_text()
    names = ['jemalloc', 'libqalculate', 'libseat', 'niri', 'noctalia', 'tomlplusplus', 'xwayland-satellite']
    rows, blockers = pkgtx.resolve_removal(names, lambda argv: (1, text))
    assert blockers == [] and [r['name'] for r in rows] == names
    assert next(r for r in rows if r['name'] == 'niri')['evr'] == '0:26.04-2.fc45'



def test_reinstall_explains_a_config_kept_by_an_earlier_removal(helper):
    from desktopforge.helper import sessions
    current = {'markers': [], 'sessions': [], 'session-config': [{'name': 'niri-noctalia.kdl'}]}
    _, blockers = helper['build_plan'](make_record()['recipe']['id'], current, {}, sessions.render,
                                       sessions.session_filename, resolve=lambda p, r: ([], []),
                                       templates={'niri-noctalia.kdl': 'x'}, installed=[],
                                       rendering=lambda: {'status': 'hardware', 'nodes': []},
                                       kept_paths={CONFIG: INSTALL_ID})
    assert blockers == [f'{CONFIG} was kept when installation {INSTALL_ID} was removed, because it had been edited. '
                        'It will not be overwritten: move or delete it to reinstall, or keep it as your own copy.']
