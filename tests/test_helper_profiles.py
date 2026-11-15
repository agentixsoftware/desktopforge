"""Lab and production profiles of the shared daemon never overlap."""
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

import pytest

REPO = Path(__file__).resolve().parents[1]
DAEMON = REPO / 'src/desktopforge/helperd/daemon.py'


def load(profile):
    return runpy.run_path(str(DAEMON), init_globals={'PROFILE_NAME': profile}, run_name=f'daemon_{profile}')


@pytest.fixture(scope='module')
def lab():
    return load('lab')


@pytest.fixture(scope='module')
def prod():
    return load('production')


def test_profiles_have_disjoint_bus_names_actions_and_state(lab, prod):
    assert lab['BUS_NAME'] == 'org.desktopforge.LabHelper1' and prod['BUS_NAME'] == 'org.desktopforge.Helper1'
    lab_actions = {lab[k] for k in ('INSTALL_ACTION_ID', 'REMOVE_ACTION_ID', 'REPAIR_ACTION_ID', 'SESSION_ACTION_ID')}
    prod_actions = {prod[k] for k in ('INSTALL_ACTION_ID', 'REMOVE_ACTION_ID', 'REPAIR_ACTION_ID', 'SESSION_ACTION_ID')}
    assert lab_actions.isdisjoint(prod_actions)
    assert all(a.startswith('org.desktopforge.lab.') for a in lab_actions)
    assert prod['INSTALL_ACTION_ID'] == 'org.desktopforge.install-session'
    assert prod['STATE_DIR'] == '/var/lib/desktopforge' and lab['STATE_DIR'] == '/var/lib/desktopforge-lab'
    assert prod['SESSION_LAUNCHER'] == '/usr/libexec/desktopforge/desktopforge-session'
    assert prod['CORE_PATH'] is None and lab['CORE_PATH'] == '/usr/local/lib/desktopforge-lab/python'


def test_production_offers_only_approved_recipes(prod, lab):
    assert all(r['status'] == 'approved' for r in prod['RECIPES'].values())
    assert prod['RECIPES'] == {}  # nothing is approved yet: evidence and owner sign-off are pending
    assert not any(rid.startswith('lab-') for rid in prod['RECIPES'])
    assert 'markers' not in prod['TARGETS'] and 'markers' in lab['TARGETS']
    assert {'lab-synthetic-marker', 'fedora45-niri-noctalia-lab'} <= set(lab['RECIPES'])


def test_production_refuses_lab_recipes(prod):
    from desktopforge.helper import sessions
    with pytest.raises(prod['Rejected']):
        prod['build_plan']('lab-synthetic-marker', {'sessions': [], 'session-config': []}, {}, sessions.render,
                           sessions.session_filename)
    with pytest.raises(prod['Rejected']):
        prod['build_plan']('fedora45-niri-noctalia-lab', {'sessions': [], 'session-config': []}, {},
                           sessions.render, sessions.session_filename)


def test_info_reports_protocol_profile_and_offers(prod, lab):
    assert prod['info']() == {'protocol': 1, 'profile': 'production', 'recipes': []}
    assert lab['info']()['profile'] == 'lab' and 'fedora45-niri-noctalia-lab' in lab['info']()['recipes']
    node = ET.fromstring(prod['INTROSPECTION'])
    assert node.find("./interface[@name='org.desktopforge.Helper1']/method[@name='Info']") is not None


def test_records_name_their_producer(prod, lab):
    assert prod['PROFILE']['producer'] == 'desktopforge-helper'
    assert lab['PROFILE']['producer'] == 'desktopforge-lab-helper'


def test_default_profile_is_production():
    namespace = runpy.run_path(str(DAEMON), run_name='daemon_default')
    assert namespace['PROFILE_NAME'] == 'production'


def test_entry_points_select_their_profile():
    lab_entry = (REPO / 'lab/helper/desktopforge-lab-helper').read_text()
    prod_entry = (REPO / 'packaging/desktopforge-helper').read_text()
    assert "init_globals={'PROFILE_NAME': 'lab'}" in lab_entry
    assert "INSTALLED = '/usr/local/lib/desktopforge-lab/python/desktopforge/helperd/daemon.py'" in lab_entry
    assert 'from desktopforge.helperd import daemon' in prod_entry and 'lab' not in prod_entry.split('"""')[2]
    assert prod_entry.startswith('#!/usr/bin/python3 -Is') and lab_entry.startswith('#!/usr/bin/python3 -Is')


def test_installed_lab_entry_never_loads_from_a_checkout():
    entry = (REPO / 'lab/helper/desktopforge-lab-helper').read_text()
    assert "_here.startswith('/usr/local/libexec/')" in entry
