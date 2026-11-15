from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from desktopforge.packages import TRACKED_PACKAGES, inspect_packages, package_assessment, parse_rpm_records


def response(name, version='5.4.1', arch='x86_64'):
    return f'{name}\t0\t{version}\t1.fc45\t{arch}\tFedora Project\t{name}-{version}-1.fc45.src.rpm\n'


def test_fixed_local_query_and_multilib_sorted(tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr='', stdout=response(args[-1]) + response(args[-1], arch='aarch64'))
    result = inspect_packages('fedora', tmp_path, runner=run)
    assert result['status'] == 'observed'
    assert len(calls) == len(TRACKED_PACKAGES)
    for args, kwargs in calls:
        assert args[:3] == ['/usr/bin/rpm', '--query', '--noplugins']
        assert args[-1] in TRACKED_PACKAGES
        assert kwargs['shell'] is False and kwargs['timeout'] == 3
        assert kwargs['env'] == {'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/'}
        assert kwargs['stdin'] == subprocess.DEVNULL
    for package in result['packages']:
        assert [r['architecture'] for r in package['records']] == ['aarch64', 'x86_64']
        assert all(r['origin_repository'] is None for r in package['records'])
        assert all(r['signature_verification'] == 'not_performed' for r in package['records'])


def test_fixture_and_unsupported_distribution_never_query_host(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('Host RPM database accessed')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert inspect_packages('fedora', tmp_path)['status'] == 'incomplete'
    assert inspect_packages('arch', Path('/'))['status'] == 'incomplete'


@pytest.mark.parametrize('rc,stdout,stderr,status', [
    (1, 'package niri is not installed\n', '', 'not_installed'),
    (1, 'package niri is not installed\n', 'database error', 'unknown'),
    (1, '', '', 'unknown'),
    (0, '', '', 'unknown'),
    (0, response('different'), '', 'unknown'),
    (0, response('niri'), 'warning', 'unknown'),
    (2, 'package niri is not installed\n', '', 'unknown'),
])
def test_absence_requires_unambiguous_response(tmp_path, rc, stdout, stderr, status):
    result = inspect_packages('fedora', tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr))
    assert next(p for p in result['packages'] if p['name'] == 'niri')['status'] == status


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('rpm', 3), UnicodeError()])
def test_query_errors_leave_state_unknown(tmp_path, error):
    def run(*args, **kwargs):
        raise error
    result = inspect_packages('fedora', tmp_path, runner=run)
    assert all(p['status'] == 'unknown' and not p['records'] for p in result['packages'])


def test_installed_is_only_an_unverified_reuse_candidate(tmp_path):
    result = inspect_packages('fedora', tmp_path, runner=lambda args, **k: SimpleNamespace(returncode=0, stderr='', stdout=response(args[-1])))
    assessment = package_assessment({'package_inventory': result}, 'niri', 'ryoku')
    assert assessment['status'] == 'unverified'
    assert [p['name'] for p in assessment['packages']] == ['niri', 'ryoku-shell']
    assert all(p['reuse'] == 'candidate_unverified' for p in assessment['packages'])
    assert package_assessment({}, 'niri', 'noctalia')['packages'][1]['status'] == 'unknown'


@pytest.mark.parametrize('text', [response('niri').replace('\t0\t', '\tbogus\t'), response('niri').replace('x86_64', '(none)'), response('niri') + '\n', response('niri').replace('Fedora Project', 'Fedora\x00Project')])
def test_malformed_header_rejected(text):
    with pytest.raises(ValueError):
        parse_rpm_records(text, 'niri')
