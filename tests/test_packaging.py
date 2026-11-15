"""RPM packaging: production files match the production profile and stay as strict as the lab's."""
import configparser
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / 'packaging'
SPEC = (PKG / 'desktopforge.spec').read_text()
PROD = runpy.run_path(str(REPO / 'src/desktopforge/helperd/daemon.py'), init_globals={'PROFILE_NAME': 'production'},
                      run_name='daemon_production_packaging')


def unit(path):
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(path)
    return parser


def test_spec_installs_every_packaging_file_and_ships_no_lab_code():
    for name in ('desktopforge-helper', 'org.desktopforge.Helper1.conf', 'org.desktopforge.Helper1.service',
                 'desktopforge-helper.service', 'org.desktopforge.policy', 'desktopforge.desktop'):
        assert f'packaging/{name}' in SPEC, name
    assert 'src/desktopforge/loginsession.py %{buildroot}%{_libexecdir}/desktopforge/desktopforge-session' in SPEC
    assert 'lab/' not in SPEC and 'LabHelper' not in SPEC
    assert 'rm %{buildroot}%{_bindir}/desktopforge-session' in SPEC  # experimental trial not shipped


def test_paths_match_the_production_profile():
    assert PROD['SESSION_LAUNCHER'] == '/usr/libexec/desktopforge/desktopforge-session'
    assert PROD['TEMPLATES'] == '/usr/share/desktopforge/templates'
    assert '%{_datadir}/desktopforge/templates/niri-noctalia.kdl' in SPEC
    service = unit(PKG / 'desktopforge-helper.service')['Service']
    assert service['BusName'] == PROD['BUS_NAME'] == 'org.desktopforge.Helper1'
    assert service['ExecStart'] == '/usr/libexec/desktopforge/desktopforge-helper'
    assert service['StateDirectory'] == 'desktopforge desktopforge/installs'


def test_production_unit_is_as_sandboxed_as_the_lab_unit():
    lab = unit(REPO / 'lab/helper/desktopforge-lab-helper.service')['Service']
    prod = unit(PKG / 'desktopforge-helper.service')['Service']
    for key in ('CapabilityBoundingSet', 'NoNewPrivileges', 'ProtectSystem', 'ProtectHome', 'PrivateTmp',
                'PrivateDevices', 'PrivateNetwork', 'RestrictAddressFamilies', 'SystemCallFilter', 'ReadWritePaths',
                'ConfigurationDirectory', 'LockPersonality', 'RestrictNamespaces'):
        assert prod[key] == lab[key], key


def test_bus_policy_only_root_owns_and_clients_reach_three_methods():
    root = ET.parse(PKG / 'org.desktopforge.Helper1.conf').getroot()
    owners = [(p.attrib, a.attrib) for p in root.findall('policy') for a in p if 'own' in a.attrib]
    assert owners == [({'user': 'root'}, {'own': 'org.desktopforge.Helper1'})]
    allowed = {(a.get('send_interface'), a.get('send_member')) for a in root.find("policy[@context='default']")}
    assert allowed == {('org.desktopforge.Helper1', m) for m in ('Info', 'Preview', 'Apply')} | {
        ('org.freedesktop.DBus.Introspectable', 'Introspect')}


def test_polkit_actions_match_the_daemon_and_require_fresh_admin_auth():
    actions = {a.get('id'): {d.tag: d.text for d in a.find('defaults')}
               for a in ET.parse(PKG / 'org.desktopforge.policy').getroot().findall('action')}
    assert set(actions) == {PROD['INSTALL_ACTION_ID'], PROD['REMOVE_ACTION_ID'], PROD['REPAIR_ACTION_ID']}
    assert all(d == {'allow_any': 'no', 'allow_inactive': 'no', 'allow_active': 'auth_admin'} for d in actions.values())
    assert not any('lab' in a for a in actions)


def test_activation_file_points_to_the_unit():
    activation = unit(PKG / 'org.desktopforge.Helper1.service')['D-BUS Service']
    assert activation['Name'] == 'org.desktopforge.Helper1' and activation['SystemdService'] == 'desktopforge-helper.service'
    assert activation['User'] == 'root' and activation['Exec'] == '/bin/false'


def test_desktop_entry_launches_the_gui():
    entry = unit(PKG / 'desktopforge.desktop')['Desktop Entry']
    assert entry['Exec'] == 'desktopforge-gui' and entry['Type'] == 'Application'
