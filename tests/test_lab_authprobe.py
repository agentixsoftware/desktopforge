"""VM-lab authorization probe: fail-closed decisions and narrow policy files."""
from pathlib import Path
import configparser
import runpy
import xml.etree.ElementTree as ET

import pytest

REPO = Path(__file__).resolve().parents[1]
LAB = REPO / 'lab/authprobe'


@pytest.fixture(scope='module')
def probe():
    # Importing must not require PyGObject or a bus; the service code is lazy.
    return runpy.run_path(str(LAB / 'desktopforge-lab-authprobe'))


@pytest.mark.parametrize('sender', [':1.42', ':12.0'])
def test_accepts_only_bus_assigned_unique_names(probe, sender):
    assert probe['validate_sender'](sender) == sender


@pytest.mark.parametrize('sender', [None, '', 'org.desktopforge.LabAuthProbe1', ':1', ':1.2.3',
                                    ':1.2\n', ' :1.2', ':a.b', 1000, ':' + '9' * 11 + '.1'])
def test_rejects_well_known_or_malformed_senders(probe, sender):
    with pytest.raises(probe['ProbeRejected']):
        probe['validate_sender'](sender)


@pytest.mark.parametrize('uid', [-1, 2**32 - 1, 2**40, True, '1000', None, 1.0])
def test_rejects_invalid_bus_uids(probe, uid):
    with pytest.raises(probe['ProbeRejected']):
        probe['validate_uid'](uid)


@pytest.mark.parametrize('reply, expected', [
    ((True, False, {}), 'authorized'),
    ((False, True, {}), 'challenge'),
    ((False, False, {}), 'denied'),
    ((False, False, {'polkit.dismissed': 'true'}), 'dismissed'),
    # Malformed replies never authorize.
    ((1, False, {}), 'error'),
    (('true', False, {}), 'error'),
    ((True, False), 'error'),
    ((True, False, []), 'error'),
    (None, 'error'),
    (True, 'error'),
])
def test_classify_is_fail_closed(probe, reply, expected):
    assert probe['classify'](reply) == expected


@pytest.mark.parametrize('error, expected', [
    ('org.freedesktop.PolicyKit1.Error.Cancelled', 'cancelled'),
    ('org.freedesktop.PolicyKit1.Error.Failed', 'error'),
    ('org.freedesktop.DBus.Error.NoReply', 'error'),
    ('', 'error'),
])
def test_polkit_errors_never_authorize(probe, error, expected):
    assert probe['classify']((True, False, {}), error_name=error) == expected


@pytest.mark.parametrize('outcome', ['challenge', 'denied', 'dismissed', 'cancelled', 'error', 'AUTHORIZED'])
def test_only_authorized_outcome_sets_authorized(probe, outcome):
    record = probe['result_record'](':1.5', 1000, outcome)
    assert record['authorized'] is False and record['changes_made'] is False


def test_result_record_is_bounded_and_echoes_bus_identity(probe):
    record = probe['result_record'](':1.5', 1000, 'authorized')
    assert record == {'protocol': 1, 'action': 'org.desktopforge.lab.authprobe', 'sender': ':1.5',
                      'uid': 1000, 'outcome': 'authorized', 'authorized': True, 'changes_made': False}


def test_admission_bounds_pending_checks_and_tokens_are_unique(probe):
    admission = probe['Admission'](limit=2)
    first = admission.admit(':1.1')
    with pytest.raises(probe['ProbeRejected'], match='already pending'):
        admission.admit(':1.1')
    second = admission.admit(':1.2')
    with pytest.raises(probe['ProbeRejected'], match='too many'):
        admission.admit(':1.3')
    assert first != second and first.startswith('dfprobe-') and len(first) == 40
    admission.release(':1.1')
    admission.admit(':1.3')
    assert len(admission) == 2


def test_probe_method_takes_no_caller_arguments(probe):
    node = ET.fromstring(probe['INTROSPECTION'])
    methods = node.findall('./interface/method')
    assert [m.get('name') for m in methods] == ['Probe']
    assert [a.get('direction') for a in methods[0].findall('arg')] == ['out']
    assert node.findall('./interface/property') == []


def test_polkit_action_requires_fresh_admin_auth_for_active_sessions_only():
    action = ET.parse(LAB / 'org.desktopforge.lab.authprobe.policy').getroot().find('action')
    assert action.get('id') == 'org.desktopforge.lab.authprobe'
    defaults = {child.tag: child.text for child in action.find('defaults')}
    assert defaults == {'allow_any': 'no', 'allow_inactive': 'no', 'allow_active': 'auth_admin'}
    assert 'no system changes' in action.findtext('message')


def test_bus_policy_lets_only_root_own_and_others_call_only_probe():
    root = ET.parse(LAB / 'org.desktopforge.LabAuthProbe1.conf').getroot()
    owners = [(p.attrib, a.attrib) for p in root.findall('policy') for a in p if 'own' in a.attrib]
    assert owners == [({'user': 'root'}, {'own': 'org.desktopforge.LabAuthProbe1'})]
    default = root.find("policy[@context='default']")
    allowed = {(a.get('send_interface'), a.get('send_member')) for a in default.findall('allow')}
    assert allowed == {('org.desktopforge.LabAuthProbe1', 'Probe'),
                       ('org.freedesktop.DBus.Introspectable', 'Introspect')}
    assert all(a.get('send_destination') == 'org.desktopforge.LabAuthProbe1' for a in default)
    assert not root.findall(".//deny") and not root.findall(".//allow[@send_member='*']")


def test_service_unit_is_sandboxed_and_runs_installed_copy_isolated():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.optionxform = str
    unit.read(LAB / 'desktopforge-lab-authprobe.service')
    service = unit['Service']
    assert service['ExecStart'] == ('/usr/bin/python3 -Is '
                                    '/usr/local/libexec/desktopforge-lab/desktopforge-lab-authprobe')
    assert service['CapabilityBoundingSet'] == '' and service['NoNewPrivileges'] == 'yes'
    assert service['ProtectSystem'] == 'strict' and service['ProtectHome'] == 'yes'
    assert service['PrivateNetwork'] == 'yes' and service['RestrictAddressFamilies'] == 'AF_UNIX'


def test_installer_targets_fixed_root_locations_and_checks_guest(probe):
    installer = runpy.run_path(str(REPO / 'scripts/vm/install-authprobe'))
    assert installer['GUEST_HOSTNAME'] == 'desktopforge-fedora45'
    assert set(installer['FILES']) == {p.name for p in LAB.iterdir()}
    for destination, mode in installer['FILES'].values():
        assert destination.startswith(('/usr/local/libexec/desktopforge-lab/', '/etc/systemd/system/',
                                       '/etc/dbus-1/system.d/', '/usr/share/dbus-1/system-services/',
                                       '/usr/share/polkit-1/actions/'))
        assert mode in (0o644, 0o755)


def test_production_package_never_references_the_lab_probe():
    for path in (REPO / 'src').rglob('*'):
        if path.is_file() and path.suffix in ('.py', '.yaml', '.json'):
            text = path.read_text(errors='replace')
            assert 'LabAuthProbe' not in text and 'lab.authprobe' not in text, path
