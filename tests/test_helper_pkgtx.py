"""Package adapter: fixed argv, strict DNF5 parsing, verification and executor wiring."""
import json
import os
from pathlib import Path

import pytest

from desktopforge.helper import executor, fsops, pkgtx
from desktopforge.helper.journal import Journal

FIXTURE = (Path(__file__).parent / 'fixtures/dnf5/install-niri-noctalia.txt').read_text()
NO_WARNING = '\n'.join(l for l in FIXTURE.splitlines() if not l.startswith('Warning:'))
KEY = '655a4b02f577861e'


def test_argv_is_fixed_and_rejects_option_injection():
    argv = pkgtx.dnf5_argv(['niri', 'noctalia'], ['fedora', 'updates'], simulate=True)
    assert argv == ['/usr/bin/dnf5', 'install', '--assumeno', '--setopt=install_weak_deps=False',
                    '--setopt=gpgcheck=True', '--setopt=localpkg_gpgcheck=True',
                    '--repo=fedora', '--repo=updates', '--', 'niri', 'noctalia']
    for bad in (['--nogpgcheck'], ['niri;rm'], ['-y'], ['Niri'], [], ['niri', '']):
        with pytest.raises(pkgtx.PackageError):
            pkgtx.dnf5_argv(bad, ['fedora'], simulate=True)
    for bad in (['*'], ['--enablerepo=x'], [], ['fedora updates']):
        with pytest.raises(pkgtx.PackageError):
            pkgtx.dnf5_argv(['niri'], bad, simulate=True)


def test_real_resolution_parses_seven_new_packages():
    rows, blockers = pkgtx.parse_resolution(NO_WARNING)
    assert blockers == []
    assert len(rows) == 7
    assert {r['name'] for r in rows} >= {'niri', 'noctalia', 'xwayland-satellite'}
    niri = next(r for r in rows if r['name'] == 'niri')
    assert niri == {'name': 'niri', 'arch': 'x86_64', 'evr': '0:26.04-2.fc45', 'repo': 'fedora'}


def test_pending_offline_update_is_a_blocker():
    _rows, blockers = pkgtx.parse_resolution(FIXTURE)
    assert blockers == ['A pending offline system update would be cancelled by this install; '
                        'apply or discard it first']


def test_any_other_warning_blocks():
    _rows, blockers = pkgtx.parse_resolution(NO_WARNING + '\nWarning: something new\n')
    assert blockers == ['Package manager warning: something new']


@pytest.mark.parametrize('section', ['Upgrading:', 'Removing:', 'Downgrading:', 'Installing weak dependencies:',
                                     'Reinstalling:', 'Removing dependent packages:'])
def test_non_install_sections_block(section):
    text = NO_WARNING.replace('Installing dependencies:', section)
    _rows, blockers = pkgtx.parse_resolution(text)
    assert blockers and section[:-1] in blockers[0]


def test_replacement_rows_block():
    text = NO_WARNING.replace(' jemalloc ', '   replacing  jemalloc ', 1)
    _rows, blockers = pkgtx.parse_resolution(text)
    assert 'replace' in blockers[0]


@pytest.mark.parametrize('mutate', [
    lambda t: t.replace('Installing dependencies:', 'Doing something else:'),
    lambda t: t.replace(' niri               x86_64 0:26.04-2.fc45  fedora      22.8 MiB', ' niri ???'),
    lambda t: t.replace('Transaction Summary:', 'Summary:'),
    lambda t: t.replace('Package             Arch', 'Pkg Arch'),
    lambda t: 'Failed to resolve the transaction:\nNo match for argument: x\n',
])
def test_unexpected_output_fails_closed(mutate):
    with pytest.raises(pkgtx.PackageError):
        pkgtx.parse_resolution(mutate(NO_WARNING))


def test_nothing_to_do():
    assert pkgtx.parse_resolution('Repositories loaded.\nPackage "x" is already installed.\n\nNothing to do.\n') == ([], [])


class FakeSystem:
    """Fake runner: dnf5 resolves from NO_WARNING, rpm reports installed state."""

    def __init__(self, resolution=NO_WARNING, install_status=0, installed_key=KEY, install_subset=None):
        self.resolution, self.install_status = resolution, install_status
        self.installed_key, self.install_subset = installed_key, install_subset
        self.installed, self.calls = {}, []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0] == pkgtx.DNF5 and '--assumeno' in argv:
            return 1, self.resolution if not self.installed else 'Nothing to do.\n'
        if argv[0] == pkgtx.DNF5:
            rows, _ = pkgtx.parse_resolution(self.resolution)
            for row in rows:
                if self.install_subset is None or row['name'] in self.install_subset:
                    self.installed[row['name']] = row
            return self.install_status, 'Complete!'
        names = argv[argv.index('--') + 1:]
        lines = []
        for name in names:
            row = self.installed.get(name)
            if row is None:
                lines.append(f'package {name} is not installed')
            else:
                lines.append(f'{name}\t{row["evr"]}\t{row["arch"]}\t1794800000\t'
                             f'RSA/SHA256, Sat 14 Nov 2026, Key ID {self.installed_key}')
        return 0, '\n'.join(lines) + '\n'


EXPECTED, _ = pkgtx.parse_resolution(NO_WARNING)


def test_install_resolves_installs_and_verifies_signer():
    fake = FakeSystem()
    records, _ = pkgtx.install(['niri', 'noctalia'], ['fedora', 'updates'], EXPECTED, fake, KEY)
    assert set(records) == {r['name'] for r in EXPECTED}
    assert [c[1] for c in fake.calls[:2]] == ['install', 'install']
    assert '--assumeno' in fake.calls[0] and '--assumeyes' in fake.calls[1]


def test_changed_resolution_installs_nothing():
    fake = FakeSystem(resolution=NO_WARNING.replace('0:26.04-2.fc45', '0:26.04-3.fc45'))
    with pytest.raises(pkgtx.PackageError, match='changed since preview'):
        pkgtx.install(['niri', 'noctalia'], ['fedora', 'updates'], EXPECTED, fake, KEY)
    assert not any('--assumeyes' in c for c in fake.calls)


def test_new_warning_at_apply_installs_nothing():
    fake = FakeSystem(resolution=FIXTURE)
    with pytest.raises(pkgtx.PackageError):
        pkgtx.install(['niri', 'noctalia'], ['fedora', 'updates'], EXPECTED, fake, KEY)
    assert not any('--assumeyes' in c for c in fake.calls)


def test_wrong_signer_fails_verification():
    fake = FakeSystem(installed_key='0123456789abcdef')
    with pytest.raises(pkgtx.PackageError, match='not signed by key'):
        pkgtx.install(['niri', 'noctalia'], ['fedora', 'updates'], EXPECTED, fake, KEY)


def test_resolve_blocks_packages_from_other_repositories():
    fake = FakeSystem(resolution=NO_WARNING.replace(' updates ', ' rpmfusion-free ', 1))
    _rows, blockers = pkgtx.resolve(['niri', 'noctalia'], ['fedora', 'updates'], fake)
    assert any('rpmfusion-free' in b for b in blockers)


# ---- executor wiring -------------------------------------------------------------

@pytest.fixture
def dirs(tmp_path):
    out = {}
    for name in ('config', 'journal'):
        (tmp_path / name).mkdir(mode=0o755)
        out[name] = os.open(tmp_path / name, fsops.DIR_FLAGS)
    yield tmp_path, out
    for fd in out.values():
        os.close(fd)


PLAN = {'recipe': 'lab', 'revision': 1, 'operations': [
    {'op': 'install_packages', 'packages': ['niri', 'noctalia'], 'repositories': ['fedora', 'updates'],
     'expected': EXPECTED},
    {'op': 'create_file', 'target': 'config', 'name': 'config.kdl', 'mode': 0o644, 'content': 'x\n'},
    {'op': 'validate_config', 'kind': 'niri', 'target': 'config', 'name': 'config.kdl'},
]}


def test_executor_installs_packages_and_records_them(dirs):
    base, fds = dirs
    fake = FakeSystem()
    adapters = executor.Adapters(fake, KEY, {'niri': lambda fd, name: (True, 'ok')})
    journal = Journal(fds['journal'])
    result = executor.execute(PLAN, journal, {'config': fds['config']}, adapters=adapters)
    assert result['state'] == 'completed'
    packages = result['created'][0]
    assert packages['kind'] == 'packages' and len(packages['packages']) == 7
    assert all(p['installtid'] == '1794800000' for p in packages['packages'])
    events = [json.loads(l)['event'] for l in (base / 'journal' / journal.name).read_text().splitlines()]
    assert events.count('operation_succeeded') == 3 and events[-1] == 'completed'


def test_rejected_config_after_install_is_manual_recovery_listing_packages(dirs):
    _base, fds = dirs
    adapters = executor.Adapters(FakeSystem(), KEY, {'niri': lambda fd, name: (False, 'bad kdl')})
    result = executor.execute(PLAN, Journal(fds['journal']), {'config': fds['config']}, adapters=adapters)
    assert result['state'] == 'failed_manual_recovery' and result['failed_index'] == 2
    assert 'niri-0:26.04-2.fc45' in result['recovery'] and 'config/config.kdl' in result['recovery']
    assert result['rolled_back'] is False


def test_failed_transaction_reports_what_actually_got_installed(dirs):
    _base, fds = dirs
    fake = FakeSystem(install_status=1, install_subset={'jemalloc'})
    result = executor.execute(PLAN, Journal(fds['journal']), {'config': fds['config']},
                              adapters=executor.Adapters(fake, KEY))
    assert result['state'] == 'failed_manual_recovery' and result['failed_index'] == 0
    (item,) = result['created']
    assert [p['name'] for p in item['packages']] == ['jemalloc']


def test_package_operation_without_adapter_changes_nothing(dirs):
    _base, fds = dirs
    result = executor.execute(PLAN, Journal(fds['journal']), {'config': fds['config']})
    assert result['state'] == 'failed_recoverable' and result['created'] == []


def test_missing_validator_fails(dirs):
    _base, fds = dirs
    result = executor.execute(PLAN, Journal(fds['journal']), {'config': fds['config']},
                              adapters=executor.Adapters(FakeSystem(), KEY))
    assert result['failed_index'] == 2 and 'no validator' in result['error']
