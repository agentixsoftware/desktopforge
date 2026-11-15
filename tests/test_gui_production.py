"""Production mode: the GUI offers an action only when every gate passes, and says which one failed."""
from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip('PySide6')

from desktopforge import install_records, labclient  # noqa: E402
from desktopforge.gui.window import DesktopForgeWindow  # noqa: E402
from tests.test_gui import app, inventory, scan  # noqa: E402,F401
from tests.test_gui_lab import FakeClient, close, finish  # noqa: E402
from tests.test_install_records import PACKAGES, make_record  # noqa: E402

OFFERING = {'protocol': 1, 'profile': 'production', 'recipes': ['fedora45-niri-noctalia'],
            'targets': ['fedora45-niri-noctalia=niri/noctalia']}
HARDWARE = {'status': 'hardware', 'nodes': [{'renderer': 'Mesa Intel'}]}


def plan_for(compositor='niri', shell='noctalia', existing=None):
    return {'target': {'compositor': compositor, 'shell': shell}, 'existing_installation': existing}


@pytest.mark.parametrize('info, plan, inventory_, expected', [
    (None, plan_for(), {}, 'Install the desktopforge-helper package to enable installation.'),
    ({'protocol': 2}, plan_for(), {}, 'uses protocol 2; this version needs 1'),
    ({'protocol': None}, plan_for(), {}, 'uses protocol None'),
    ({**OFFERING, 'targets': []}, plan_for(), {'rendering': HARDWARE}, 'No approved recipe for Niri + Noctalia yet.'),
    (OFFERING, plan_for(shell='dms'), {'rendering': HARDWARE}, 'No approved recipe for Niri + Dms yet.'),
    (OFFERING, plan_for(), {'rendering': {'status': 'software-only'}}, 'reports software-only rendering'),
])
def test_gates_explain_the_first_failure(info, plan, inventory_, expected):
    action, reason = labclient.production_gates(info, plan, inventory_)
    assert action is None and expected in reason


def test_all_gates_pass_offers_install():
    assert labclient.production_gates(OFFERING, plan_for(), {'rendering': HARDWARE}) == \
        (('install', 'fedora45-niri-noctalia'), None)


def test_only_production_recorded_installations_are_offered_for_removal():
    prod = {'install_id': 'ab' * 16, 'status': 'intact', 'producer': 'desktopforge-helper'}
    lab = dict(prod, producer='desktopforge-lab-helper')
    assert labclient.production_gates(OFFERING, plan_for(existing=prod), {})[0] == ('remove', 'remove-' + 'ab' * 16)
    assert labclient.production_gates(OFFERING, plan_for(existing=lab), {'rendering': HARDWARE})[0] == \
        ('install', 'fedora45-niri-noctalia')


def window(inventory, info, client=None):
    widget = DesktopForgeWindow(detector=lambda: inventory, auto_refresh=False, lab_available=lambda: True,
                                production_info=lambda: info, production_client_factory=lambda: client,
                                lab_client_factory=lambda: pytest.fail('lab client used in production mode'))
    widget.dialogs = []
    widget.confirm_lab = lambda kind, summary: widget.dialogs.append(('confirm', kind, summary)) or True
    widget.report_lab = lambda title, lines: widget.dialogs.append(('report', title, lines))
    return widget


def test_production_helper_without_approved_recipe_explains_and_stays_disabled(app, inventory):
    widget = window(inventory, {**OFFERING, 'recipes': [], 'targets': []})
    try:
        scan(widget)
        assert widget.mode_badge.text() == 'HELPER INSTALLED'
        assert not widget.install_button.isEnabled()
        assert widget.footer_note.text() == 'No approved recipe for Niri + Noctalia yet.'
    finally:
        close(app, widget)


def test_production_install_uses_the_production_client(app, inventory):
    ready = deepcopy(inventory)
    ready['rendering'] = HARDWARE
    client = FakeClient()
    widget = window(ready, OFFERING, client)
    try:
        scan(widget)
        assert widget.install_button.isEnabled() and widget.install_button.text() == 'Install…'
        widget.refresh_inventory = lambda: None
        widget.install_button.click()
        finish(app, widget)
        assert client.calls[0] == ('preview', 'fedora45-niri-noctalia')
        assert widget.dialogs[0][:2] == ('confirm', 'install')
    finally:
        close(app, widget)


def test_production_mode_takes_precedence_over_lab_mode(app, inventory):
    widget = window(inventory, None)
    try:
        scan(widget)  # no production helper: lab mode (lab_available=True)
        assert widget.mode_badge.text() == 'VM LAB MODE'
    finally:
        close(app, widget)


def test_damaged_production_installation_offers_remove_and_repair(app, inventory):
    damaged = deepcopy(inventory)
    summary = install_records.summarize(make_record(producer='desktopforge-helper'), Path('/nonexistent'), PACKAGES)
    summary['status'] = 'incomplete'
    damaged['desktopforge_installations'] = {'installations': [summary]}
    widget = window(damaged, OFFERING, FakeClient())
    try:
        scan(widget)
        assert widget.install_button.text() == 'Remove…'
        assert not widget.repair_button.isHidden() and widget.repair_button.text() == 'Repair…'
    finally:
        close(app, widget)
