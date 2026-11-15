"""Privileged-helper core: grants, handle-based writes, journal and executor."""
import ast
import json
import os
from pathlib import Path

import pytest

from desktopforge.helper import evidence, executor, fsops, grants
from desktopforge.helper.journal import Journal, JournalError

HELPER = Path(__file__).resolve().parents[1] / 'src/desktopforge/helper'
UID = os.getuid()
H1, H2 = 'a' * 64, 'b' * 64


# ---- grants -----------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def store():
    clock = Clock()
    s = grants.GrantStore(ttl=60, limit=3, per_uid=2, clock=clock)
    s.test_clock = clock
    return s


ALICE = grants.Caller(':1.10', 1000)


def test_grant_redeems_once_for_same_caller_and_plan(store):
    grant = store.issue(ALICE, 'r', 1, H1, H2)
    assert store.redeem(grant.token, ALICE, H1) == grant
    with pytest.raises(grants.GrantRejected, match='already used'):
        store.redeem(grant.token, ALICE, H1)


@pytest.mark.parametrize('caller', [grants.Caller(':1.11', 1000), grants.Caller(':1.10', 0)])
def test_other_connection_or_uid_cannot_use_grant_and_it_is_burned(store, caller):
    grant = store.issue(ALICE, 'r', 1, H1, H2)
    with pytest.raises(grants.GrantRejected, match='different caller'):
        store.redeem(grant.token, caller, H1)
    with pytest.raises(grants.GrantRejected, match='already used'):
        store.redeem(grant.token, ALICE, H1)


def test_tampered_plan_hash_is_rejected(store):
    grant = store.issue(ALICE, 'r', 1, H1, H2)
    with pytest.raises(grants.GrantRejected, match='does not match'):
        store.redeem(grant.token, ALICE, H2)


def test_expired_grant_is_rejected(store):
    grant = store.issue(ALICE, 'r', 1, H1, H2)
    store.test_clock.now += 60
    with pytest.raises(grants.GrantRejected, match='expired'):
        store.redeem(grant.token, ALICE, H1)


@pytest.mark.parametrize('token', ['', 'A' * 64, 'a' * 63, 'a' * 65, None, 'g' * 64])
def test_malformed_tokens_rejected(store, token):
    with pytest.raises(grants.GrantRejected, match='malformed'):
        store.redeem(token, ALICE, H1)


def test_outstanding_previews_are_bounded_and_expire(store):
    store.issue(ALICE, 'r', 1, H1, H2)
    store.issue(ALICE, 'r', 1, H1, H2)
    with pytest.raises(grants.GrantRejected, match='for this user'):
        store.issue(grants.Caller(':1.12', 1000), 'r', 1, H1, H2)
    store.issue(grants.Caller(':1.13', 1001), 'r', 1, H1, H2)
    with pytest.raises(grants.GrantRejected, match='too many outstanding'):
        store.issue(grants.Caller(':1.14', 1002), 'r', 1, H1, H2)
    store.test_clock.now += 61
    store.issue(ALICE, 'r', 1, H1, H2)
    assert len(store) == 1


def test_disconnect_drops_only_that_connections_grants(store):
    mine = store.issue(ALICE, 'r', 1, H1, H2)
    other = store.issue(grants.Caller(':1.20', 1001), 'r', 1, H1, H2)
    store.drop_sender(':1.10')
    assert mine.token not in store.grants and other.token in store.grants


def test_issue_rejects_malformed_hashes(store):
    with pytest.raises(grants.GrantRejected):
        store.issue(ALICE, 'r', 1, 'not-a-hash', H2)


# ---- handle-based filesystem operations --------------------------------------

@pytest.fixture
def target(tmp_path):
    base = tmp_path / 'state'
    base.mkdir(mode=0o755)
    fd = os.open(base, fsops.DIR_FLAGS)
    yield base, fd
    os.close(fd)


def test_create_file_is_exclusive_and_never_overwrites(target):
    base, fd = target
    digest = fsops.create_file(fd, 'marker', b'one')
    assert (base / 'marker').read_bytes() == b'one' and len(digest) == 64
    assert oct((base / 'marker').stat().st_mode & 0o777) == '0o644'
    with pytest.raises(fsops.Conflict):
        fsops.create_file(fd, 'marker', b'two')
    assert (base / 'marker').read_bytes() == b'one'


def test_create_file_refuses_existing_symlink(target, tmp_path):
    base, fd = target
    victim = tmp_path / 'victim'
    victim.write_text('keep')
    (base / 'marker').symlink_to(victim)
    with pytest.raises(fsops.Conflict):
        fsops.create_file(fd, 'marker', b'evil')
    assert victim.read_text() == 'keep'


@pytest.mark.parametrize('name', ['..', '.', 'a/b', '../x', '', '.hidden', 'x' * 129, 'a\nb'])
def test_names_cannot_traverse(target, name):
    _, fd = target
    with pytest.raises(fsops.UnsafePath):
        fsops.create_file(fd, name, b'x')


def test_mode_cannot_exceed_0644(target):
    _, fd = target
    with pytest.raises(fsops.UnsafePath):
        fsops.create_file(fd, 'marker', b'x', mode=0o4755)


def test_open_child_refuses_symlinked_directory(target, tmp_path):
    base, fd = target
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (base / 'markers').symlink_to(elsewhere)
    with pytest.raises(fsops.UnsafePath):
        fsops.open_child(fd, 'markers', expected_uid=UID, create_mode=0o755)


def test_open_child_refuses_writable_or_foreign_directory(target):
    base, fd = target
    (base / 'markers').mkdir()
    os.chmod(base / 'markers', 0o777)
    with pytest.raises(fsops.UnsafePath, match='writable'):
        fsops.open_child(fd, 'markers', expected_uid=UID)
    os.chmod(base / 'markers', 0o755)
    with pytest.raises(fsops.UnsafePath, match='owner'):
        fsops.open_child(fd, 'markers', expected_uid=UID + 1)
    os.close(fsops.open_child(fd, 'markers', expected_uid=UID))


def test_handle_survives_path_replacement(target, tmp_path):
    base, fd = target
    child = fsops.open_child(fd, 'markers', expected_uid=UID, create_mode=0o755)
    try:
        moved = tmp_path / 'moved'
        os.rename(base / 'markers', moved)
        (base / 'markers').symlink_to(tmp_path)  # attacker swaps the path
        fsops.create_file(child, 'marker', b'x')
        assert (moved / 'marker').exists() and not (tmp_path / 'marker').exists()
    finally:
        os.close(child)


def test_anchor_checks_every_component(tmp_path):
    with pytest.raises(fsops.UnsafePath):
        fsops.open_anchor('relative/path')
    with pytest.raises(fsops.UnsafePath):
        fsops.open_anchor('/usr/../etc')
    # The pytest tree sits under world-writable /tmp: not a trusted anchor.
    with pytest.raises(fsops.UnsafePath):
        fsops.open_anchor(str(tmp_path), expected_uid=UID)
    os.close(fsops.open_anchor('/usr', expected_uid=0))


# ---- evidence -----------------------------------------------------------------

def test_fingerprint_changes_with_contents_names_and_links(target, tmp_path):
    base, fd = target
    (base / 'gnome.desktop').write_text('a')
    first = evidence.fingerprint(evidence.directory_evidence(fd))
    assert first == evidence.fingerprint(evidence.directory_evidence(fd))
    (base / 'gnome.desktop').write_text('b')
    second = evidence.fingerprint(evidence.directory_evidence(fd))
    (base / 'new.desktop').symlink_to('/nonexistent')
    third = evidence.fingerprint(evidence.directory_evidence(fd))
    assert len({first, second, third}) == 3
    records = evidence.directory_evidence(fd)
    assert records[1] == {**records[1], 'type': 'symlink', 'target': '/nonexistent'}


@pytest.fixture(params=['tmp', 'checkout-filesystem'])
def any_fs_target(request, tmp_path):
    """tmp_path is often tmpfs; also run on the checkout's filesystem (btrfs here)."""
    if request.param == 'tmp':
        base = tmp_path / 'state'
    else:
        cache = getattr(request.config, 'cache', None)
        if cache is None:
            pytest.skip('pytest cache plugin disabled; no checkout-filesystem scratch dir')
        base = cache.mkdir('helper-fs') / f'state-{os.getpid()}-{id(request)}'
    base.mkdir(mode=0o755)
    fd = os.open(base, fsops.DIR_FLAGS)
    yield base, fd
    os.close(fd)
    for child in base.iterdir():
        child.unlink()
    base.rmdir()


def test_evidence_sees_entries_created_after_handle_was_opened(any_fs_target):
    # Regression: a long-lived directory handle missed new entries on btrfs,
    # letting a repeat preview pass although its marker already existed.
    base, fd = any_fs_target
    assert evidence.directory_evidence(fd) == []
    fsops.create_file(fd, 'late.marker', b'x')
    assert [r['name'] for r in evidence.directory_evidence(fd)] == ['late.marker']
    (base / 'later.marker').write_text('y')
    assert [r['name'] for r in evidence.directory_evidence(fd)] == ['late.marker', 'later.marker']


# ---- journal and executor ------------------------------------------------------

PLAN = {'recipe': 'lab', 'revision': 1, 'operations': [
    {'op': 'create_file', 'target': 'markers', 'name': 'one.marker', 'mode': 0o644, 'content': 'one\n'},
    {'op': 'create_file', 'target': 'markers', 'name': 'two.marker', 'mode': 0o644, 'content': 'two\n'}]}


def events(base, journal):
    lines = (base / journal.name).read_text().splitlines()
    return [json.loads(line) for line in lines]


@pytest.fixture
def journal_dir(tmp_path):
    path = tmp_path / 'journal'
    path.mkdir(mode=0o700)
    fd = os.open(path, fsops.DIR_FLAGS)
    yield path, fd
    os.close(fd)


def test_successful_execution_is_journaled_in_order(target, journal_dir):
    base, fd = target
    jpath, jfd = journal_dir
    journal = Journal(jfd)
    result = executor.execute(PLAN, journal, {'markers': fd})
    assert result['state'] == 'completed' and [c['name'] for c in result['created']] == ['one.marker', 'two.marker']
    names = [e['event'] for e in events(jpath, journal)]
    assert names == ['applying', 'operation_started', 'operation_succeeded',
                     'operation_started', 'operation_succeeded', 'verifying', 'completed']
    assert [e['seq'] for e in events(jpath, journal)] == list(range(1, 8))
    assert oct((jpath / journal.name).stat().st_mode & 0o777) == '0o600'


def test_failure_after_partial_change_reports_manual_recovery_not_rollback(target, journal_dir):
    base, fd = target
    _, jfd = journal_dir
    plan = {**PLAN, 'operations': [PLAN['operations'][0], {'op': 'fail', 'reason': 'injected'}]}
    result = executor.execute(plan, Journal(jfd), {'markers': fd})
    assert result['state'] == 'failed_manual_recovery' and result['rolled_back'] is False
    assert result['failed_index'] == 1 and 'one.marker' in result['recovery']
    assert (base / 'one.marker').exists()


def test_conflict_on_first_operation_changes_nothing(target, journal_dir):
    base, fd = target
    _, jfd = journal_dir
    (base / 'one.marker').write_text('user data')
    result = executor.execute(PLAN, Journal(jfd), {'markers': fd})
    assert result['state'] == 'failed_recoverable' and result['created'] == []
    assert (base / 'one.marker').read_text() == 'user data' and not (base / 'two.marker').exists()


def test_unknown_operation_is_refused(target, journal_dir):
    _, fd = target
    _, jfd = journal_dir
    plan = {**PLAN, 'operations': [{'op': 'run_command', 'name': 'x'}]}
    assert executor.execute(plan, Journal(jfd), {'markers': fd})['state'] == 'failed_recoverable'


class FailingJournal:
    def __init__(self, fail_at):
        self.fail_at, self.count = fail_at, 0

    def record(self, event, **_fields):
        self.count += 1
        if self.count >= self.fail_at:
            raise JournalError('disk full')


def test_journal_failure_before_first_change_makes_no_change(target):
    base, fd = target
    result = executor.execute(PLAN, FailingJournal(fail_at=2), {'markers': fd})
    assert result['state'] == 'failed_recoverable' and result['journal_complete'] is False
    assert list(base.iterdir()) == []


def test_journal_failure_mid_plan_stops_and_reports_created(target):
    base, fd = target
    result = executor.execute(PLAN, FailingJournal(fail_at=4), {'markers': fd})  # after op 1 succeeded
    assert result['state'] == 'failed_manual_recovery'
    assert [c['name'] for c in result['created']] == ['one.marker']
    assert not (base / 'two.marker').exists()


def test_journal_never_reuses_an_existing_file(journal_dir):
    _, jfd = journal_dir
    Journal(jfd, install_id='fixed')
    with pytest.raises(JournalError):
        Journal(jfd, install_id='fixed')


def test_plan_hash_is_canonical():
    reordered = {'operations': PLAN['operations'], 'revision': 1, 'recipe': 'lab'}
    assert executor.plan_hash(PLAN) == executor.plan_hash(reordered)
    assert executor.plan_hash(PLAN) != executor.plan_hash({**PLAN, 'revision': 2})


# ---- packaging boundary ---------------------------------------------------------

def test_core_uses_only_stdlib_and_relative_imports():
    allowed = {'dataclasses', 'hashlib', 'json', 'os', 'pathlib', 're', 'secrets', 'stat', 'time', 'uuid'}
    for path in HELPER.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert {a.name.split('.')[0] for a in node.names} <= allowed, path
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module.split('.')[0] in allowed, path


def test_gui_and_cli_do_not_use_the_helper():
    src = HELPER.parent
    for path in [*src.glob('*.py'), *(src / 'gui').glob('*.py')]:
        assert 'helper' not in {
            n.module.split('.')[-1] if isinstance(n, ast.ImportFrom) and n.module else ''
            for n in ast.walk(ast.parse(path.read_text()))}, path


# ---- login-session registration ---------------------------------------------------

from desktopforge.helper import sessions  # noqa: E402

GNOME = '/usr/bin/gnome-session'
ENTRY = {'Name': 'DesktopForge Lab (GNOME)', 'Exec': GNOME, 'TryExec': GNOME,
         'Type': 'Application', 'DesktopNames': 'GNOME'}


def test_render_is_fixed_order_and_minimal():
    assert sessions.render(ENTRY, {GNOME}).decode() == (
        '[Desktop Entry]\nName=DesktopForge Lab (GNOME)\nExec=/usr/bin/gnome-session\n'
        'TryExec=/usr/bin/gnome-session\nType=Application\nDesktopNames=GNOME\n')


@pytest.mark.parametrize('change', [
    {'Name': 'Evil\nExec=/bin/sh'},                 # newline injection
    {'Name': 'x\x00y'}, {'Comment': 'a\\nb'},       # control / escape sequences
    {'Name': ' padded'}, {'Name': 'x' * 201},
    {'Exec': '/bin/sh -c id'}, {'Exec': 'gnome-session'}, {'Exec': '/usr/bin/../bin/sh'},
    {'Exec': '/usr/bin/gnome-session %U'}, {'TryExec': '/usr/bin/other'},
    {'Type': 'Link'}, {'X-GNOME-Autostart': 'true'}, {'Hidden': 'false'},
])
def test_render_rejects_injection_and_unlisted_commands(change):
    with pytest.raises(sessions.InvalidEntry):
        sessions.render({**ENTRY, **change}, {GNOME, '/bin/sh'} - {'/bin/sh'})


def test_render_requires_name_exec_type():
    with pytest.raises(sessions.InvalidEntry):
        sessions.render({'Name': 'x', 'Type': 'Application'}, {GNOME})


@pytest.mark.parametrize('session_id', ['gnome', 'desktopforge-', 'desktopforge-Lab', 'desktopforge-a/b',
                                        'desktopforge-../x', 'desktopforge--x', 'x-desktopforge-a'])
def test_session_ids_stay_in_namespace(session_id):
    with pytest.raises(sessions.InvalidEntry):
        sessions.session_filename(session_id)


def test_register_session_creates_entry_and_never_replaces(target, journal_dir):
    base, fd = target
    _, jfd = journal_dir
    plan = {'recipe': 'lab', 'revision': 1, 'operations': [
        {'op': 'register_session', 'target': 'sessions', 'id': 'desktopforge-lab-gnome', 'entry': ENTRY}]}
    result = executor.execute(plan, Journal(jfd), {'sessions': fd}, allowed_commands={GNOME})
    assert result['state'] == 'completed'
    assert (base / 'desktopforge-lab-gnome.desktop').read_text().startswith('[Desktop Entry]\nName=DesktopForge')
    again = executor.execute(plan, Journal(jfd), {'sessions': fd}, allowed_commands={GNOME})
    assert again['state'] == 'failed_recoverable' and 'already exists' in again['error']


def test_register_session_without_allowlist_changes_nothing(target, journal_dir):
    base, fd = target
    _, jfd = journal_dir
    plan = {'recipe': 'lab', 'revision': 1, 'operations': [
        {'op': 'register_session', 'target': 'sessions', 'id': 'desktopforge-lab-gnome', 'entry': ENTRY}]}
    assert executor.execute(plan, Journal(jfd), {'sessions': fd})['state'] == 'failed_recoverable'
    assert list(base.iterdir()) == []


def test_operation_cannot_name_an_unknown_target(target, journal_dir):
    _, fd = target
    _, jfd = journal_dir
    plan = {'recipe': 'lab', 'revision': 1, 'operations': [
        {'op': 'create_file', 'target': 'etc', 'name': 'x', 'mode': 0o644, 'content': ''}]}
    assert executor.execute(plan, Journal(jfd), {'markers': fd})['error'] == 'unknown operation target'


def test_display_names_reads_regular_entries_only(target, tmp_path):
    base, fd = target
    (base / 'gnome.desktop').write_text('[Desktop Entry]\nName = GNOME \nExec=gnome-session\n')
    (base / 'other.desktop').write_text('[Other]\nName=Hidden\n[Desktop Entry]\nName[de]=Lokal\nExec=x\n')
    secret = tmp_path / 'secret'
    secret.write_text('[Desktop Entry]\nName=Leaked\n')
    (base / 'link.desktop').symlink_to(secret)
    (base / 'notes.txt').write_text('Name=ignored')
    names = sessions.display_names(fd, evidence.directory_evidence(fd))
    assert names == {'gnome.desktop': 'GNOME', 'link.desktop': None, 'other.desktop': None}


def test_read_small_is_bounded_and_refuses_symlinks(target, tmp_path):
    base, fd = target
    (base / 'big').write_bytes(b'x' * 11)
    with pytest.raises(fsops.UnsafePath):
        fsops.read_small(fd, 'big', limit=10)
    (base / 'link').symlink_to(tmp_path)
    with pytest.raises(OSError):
        fsops.read_small(fd, 'link')
