"""GUI VM-lab mode: only with the lab helper present; review, authenticate, report, rescan."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from desktopforge import install_records, labclient  # noqa: E402
from desktopforge.gui.window import DesktopForgeWindow  # noqa: E402
from tests.test_gui import app, inventory, scan, wait_for  # noqa: E402,F401
from tests.test_install_records import PACKAGES, make_record  # noqa: E402


class FakeClient:
    def __init__(self, preview=None, result=None):
        self.preview_result = preview or {'ok': True, 'status': 'ready', 'token': 't' * 64, 'plan_hash': 'h' * 64,
                                          'summary': ['Install from Fedora repositories: niri', 'Add login session']}
        self.result = result or {'ok': True, 'outcome': 'completed', 'created': ['packages: niri-0:26.04-2.fc45'],
                                 'record': '/var/lib/desktopforge/installs/x.json'}
        self.calls = []

    def preview(self, recipe):
        self.calls.append(('preview', recipe))
        return self.preview_result

    def apply(self, token, plan_hash, progress=None):
        self.calls.append(('apply', token, plan_hash))
        if progress:
            progress('operation_started', 'Downloading and installing packages…')
        return self.result


def make_window(inventory, client, available=True):
    widget = DesktopForgeWindow(detector=lambda: inventory, auto_refresh=False,
                                lab_available=lambda: available, lab_client_factory=lambda: client)
    widget.dialogs = []
    widget.confirm_lab = lambda kind, summary: widget.dialogs.append(('confirm', kind, summary)) or widget.confirm_answer
    widget.report_lab = lambda title, lines: widget.dialogs.append(('report', title, lines))
    widget.confirm_answer = True
    return widget


def close(app, widget):
    for worker in (widget._worker, widget._lab_worker):
        if worker is not None:
            worker.wait(5000)
    app.processEvents()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def finish(app, widget):
    wait_for(lambda: widget._lab_worker is not None and not widget._lab_worker.isRunning())
    app.processEvents()


def test_without_lab_helper_nothing_is_offered(app, inventory):
    widget = make_window(inventory, FakeClient(), available=False)
    try:
        scan(widget)
        assert widget.mode_badge.text() == 'READ-ONLY PREVIEW'
        assert not widget.install_button.isEnabled() and widget.install_button.text() == 'Installation unavailable'
    finally:
        close(app, widget)


def test_lab_mode_offers_install_only_for_lab_recipes(app, inventory):
    widget = make_window(inventory, FakeClient())
    try:
        scan(widget)
        assert widget.mode_badge.text() == 'VM LAB MODE'
        assert widget.install_button.isEnabled() and widget.install_button.text() == 'Install in VM lab…'
        widget.shell.setCurrentIndex(widget.shell.findData('dms'))
        assert not widget.install_button.isEnabled() and widget.install_button.text() == 'Installation unavailable'
    finally:
        close(app, widget)


def test_review_then_authenticate_then_report_and_rescan(app, inventory):
    client = FakeClient()
    widget = make_window(inventory, client)
    try:
        scan(widget)
        scans = []
        widget.refresh_inventory = lambda: scans.append(True)
        widget.install_button.click()
        wait_for(lambda: ('apply', 't' * 64, 'h' * 64) in client.calls)
        finish(app, widget)
        assert client.calls[0] == ('preview', 'fedora45-niri-noctalia-lab')
        assert widget.dialogs[0] == ('confirm', 'install', client.preview_result['summary'])
        title, lines = widget.dialogs[1][1:]
        assert title == 'Result' and lines[0] == 'Outcome: completed' and any('Record' in l for l in lines)
        assert scans == [True]
    finally:
        close(app, widget)


def test_progress_reaches_the_status_bar(app, inventory):
    seen = []
    widget = make_window(inventory, FakeClient())
    try:
        scan(widget)
        widget.refresh_inventory = lambda: None
        widget.status_label.setText = lambda text, original=widget.status_label.setText: (seen.append(text), original(text))
        widget.install_button.click()
        wait_for(lambda: any('Downloading' in s for s in seen))
        finish(app, widget)
    finally:
        close(app, widget)


def test_declining_the_review_never_applies(app, inventory):
    client = FakeClient()
    widget = make_window(inventory, client)
    try:
        scan(widget)
        widget.confirm_answer = False
        widget.install_button.click()
        finish(app, widget)
        assert [c[0] for c in client.calls] == ['preview'] and 'nothing changed' in widget.status_label.text()
    finally:
        close(app, widget)


@pytest.mark.parametrize('preview, title', [
    ({'ok': True, 'status': 'blocked', 'blockers': ['A pending offline system update would be cancelled']}, 'Blocked'),
    ({'ok': False, 'reason': 'unknown recipe'}, 'Request refused'),
])
def test_blocked_or_refused_preview_is_reported_without_apply(app, inventory, preview, title):
    client = FakeClient(preview=preview)
    widget = make_window(inventory, client)
    try:
        scan(widget)
        widget.install_button.click()
        finish(app, widget)
        assert [c[0] for c in client.calls] == ['preview']
        assert widget.dialogs == [('report', title, preview.get('blockers') or [preview['reason']])]
    finally:
        close(app, widget)


def test_recorded_installation_offers_removal(app, inventory):
    installed = deepcopy(inventory)
    summary = install_records.summarize(make_record(), Path('/nonexistent'), PACKAGES)
    summary['status'] = 'intact'
    installed['desktopforge_installations'] = {'installations': [summary]}
    installed['rendering'] = {'status': 'hardware', 'nodes': []}
    client = FakeClient()
    widget = make_window(installed, client)
    try:
        scan(widget)
        assert widget.install_button.text() == 'Remove from VM lab…'
        widget.refresh_inventory = lambda: None
        widget.install_button.click()
        finish(app, widget)
        assert client.calls[0] == ('preview', 'remove-' + summary['install_id'])
        assert widget.dialogs[0][1] == 'remove'
    finally:
        close(app, widget)


def test_window_does_not_close_while_a_lab_request_runs(app, inventory):
    import threading
    release = threading.Event()

    class SlowClient(FakeClient):
        def preview(self, recipe):
            release.wait(5)
            return super().preview(recipe)
    widget = make_window(inventory, SlowClient())
    try:
        scan(widget)
        widget.confirm_answer = False
        widget.install_button.click()
        wait_for(lambda: widget._lab_worker is not None and widget._lab_worker.isRunning())
        assert widget.close() is False and 'still running' in widget.status_label.text()
        release.set()
        finish(app, widget)
    finally:
        release.set()
        close(app, widget)


# ---- shared pieces ----------------------------------------------------------------------

def test_lab_action_mapping():
    assert labclient.lab_action({'target': {'compositor': 'niri', 'shell': 'noctalia'}}, True) == \
        ('install', 'fedora45-niri-noctalia-lab')
    assert labclient.lab_action({'target': {'compositor': 'niri', 'shell': 'noctalia'}}, False) is None
    assert labclient.lab_action({'target': {'compositor': 'hyprland', 'shell': 'dms'}}, True) is None
    plan = {'target': {}, 'existing_installation': {'install_id': 'ab' * 16, 'status': 'modified'}}
    assert labclient.lab_action(plan, True) == ('remove', 'remove-' + 'ab' * 16)


def test_lab_availability_is_false_without_pygobject_or_bus(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_gi(name, *args, **kwargs):
        if name.startswith('gi'):
            raise ImportError('no gi')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_gi)
    assert labclient.LabHelperClient.available() is False


@pytest.mark.parametrize('step, fields, text', [
    ('operation_started', {'op': 'install_packages'}, 'Downloading and installing packages (this can take a few minutes)…'),
    ('operation_started', {'op': 'remove_file', 'name': 'niri-noctalia.kdl'}, 'Removing niri-noctalia.kdl…'),
    ('failed_recoverable', {}, 'Failed; no changes were made'),
    ('something_new', {}, 'Something new'),
])
def test_helper_progress_text(step, fields, text):
    helper = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'lab/helper/desktopforge-lab-helper'))
    assert helper['progress_text'](step, fields) == text


def test_helper_declares_the_progress_signal():
    import xml.etree.ElementTree as ET
    helper = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'lab/helper/desktopforge-lab-helper'))
    signal = ET.fromstring(helper['INTROSPECTION']).find("./interface/signal[@name='Progress']")
    assert [a.get('type') for a in signal.findall('arg')] == ['s', 's']
