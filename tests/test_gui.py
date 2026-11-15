"""Qt interaction tests, always offscreen; no desktop launcher or executor."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktopforge.detection import detect_system
from desktopforge.gui.window import DesktopForgeWindow, configure_application
from desktopforge.planning import build_plan


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Qt operation did not complete'


@pytest.fixture(scope='module')
def app():
    original = os.environ.get('QT_QPA_PLATFORM')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    configure_application(application)
    yield application
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if original is None:
        os.environ.pop('QT_QPA_PLATFORM', None)
    else:
        os.environ['QT_QPA_PLATFORM'] = original


@pytest.fixture
def inventory(tmp_path):
    (tmp_path / 'etc').mkdir()
    (tmp_path / 'etc/os-release').write_text('ID=fedora\nVERSION_ID=45\nPRETTY_NAME="Fedora Linux 45 (COSMIC)"\n')
    folder = tmp_path / 'usr/share/wayland-sessions'
    folder.mkdir(parents=True)
    for slug, title in (('cosmic', 'COSMIC'), ('niri-dms', 'Niri (DMS)'),
                        ('niri-noctalia', 'Niri (Noctalia)'), ('niri', 'Niri (Ryoku)')):
        (folder / f'{slug}.desktop').write_text(f'[Desktop Entry]\nName={title}\nExec=niri-session\n')
    dm = tmp_path / 'etc/systemd/system'
    dm.mkdir(parents=True)
    (dm / 'display-manager.service').symlink_to('/usr/lib/systemd/system/sddm.service')
    return detect_system(root=tmp_path,
        environ={'XDG_CURRENT_DESKTOP': 'niri', 'XDG_SESSION_TYPE': 'wayland', 'DESKTOP_SESSION': 'niri-ryoku'},
        which=lambda name: '/usr/bin/' + name if name in ('niri', 'noctalia', 'dnf5') else None)


@pytest.fixture
def window(app, inventory):
    widget = DesktopForgeWindow(detector=lambda: inventory, auto_refresh=False)
    widget.show()
    yield widget
    if widget._worker is not None:
        widget._worker.wait(5000)
        app.processEvents()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def scan(window):
    window.refresh_inventory()
    wait_for(lambda: window.inventory is not None and window.refresh_button.isEnabled())


def test_inventory_scan_and_default_plan_use_shared_core(window, inventory):
    saved = deepcopy(inventory)
    scan(window)
    assert window.distribution_label.text() == 'Fedora Linux 45 (COSMIC)'
    assert window.facts['display_manager'].text() == 'SDDM · configured'
    assert 'Ryoku' in window.facts['active_shell'].text()
    assert 'environment_hint' in window.facts['active_shell'].text()
    assert window.sessions.count() == 4
    assert window.plan == build_plan(inventory, 'niri', 'noctalia')
    assert window.operations.rowCount() == 5
    assert window.compositor.isEnabled() and window.shell.isEnabled()
    assert window.copy_button.isEnabled()
    assert not window.install_button.isEnabled()
    assert inventory == saved


def test_target_changes_refresh_proposals_and_details(window):
    scan(window)
    window.shell.setCurrentIndex(window.shell.findData('ryoku'))
    assert window.plan['target']['shell'] == 'ryoku'
    assert window.operations.rowCount() == 0
    assert 'No operation recipe' in window.empty_operations.text()
    assert json.loads(window.raw_json.toPlainText())['plan']['target']['shell'] == 'ryoku'
    window.compositor.setCurrentIndex(window.compositor.findData('hyprland'))
    assert window.plan['target']['compositor'] == 'hyprland'
    assert window.plan['status'] == 'blocked'
    assert not window.install_button.isEnabled()


def test_review_button_and_copy_json_are_functional(window, app):
    scan(window)
    QTest.mouseClick(window.review_button, Qt.MouseButton.LeftButton)
    assert window.tabs.currentIndex() == 1
    assert 'No validated installation recipe' in window.requirements.toPlainText()
    QTest.mouseClick(window.copy_button, Qt.MouseButton.LeftButton)
    assert json.loads(app.clipboard().text()) == window.plan
    assert 'copied' in window.status_label.text()


def test_scan_error_invalidates_old_plan_and_allows_retry(window, inventory):
    scan(window)
    def fail():
        raise OSError('fixture permission failure')
    window.detector = fail
    window.refresh_inventory()
    wait_for(lambda: window.refresh_button.isEnabled())
    assert window.inventory is None and window.plan is None
    assert window.plan_status.text() == 'Detection unavailable'
    assert window.distribution_label.text() == 'Detection unavailable'
    assert not window.compositor.isEnabled() and not window.copy_button.isEnabled()
    assert not window.raw_json.toPlainText()
    assert not window.install_button.isEnabled()
    assert 'fixture permission failure' in window.requirements.toPlainText()
    window.detector = lambda: inventory
    scan(window)
    assert window.operations.rowCount() == 5


def test_recipe_error_clears_stale_plan_without_disabling_inventory(window):
    scan(window)
    def fail(*args):
        raise ValueError('Malformed recipe fixture')
    window.planner = fail
    window.shell.setCurrentIndex(window.shell.findData('ryoku'))
    assert window.plan is None
    assert window.inventory is not None
    assert window.operations.rowCount() == 0
    assert 'Malformed recipe fixture' in window.requirements.toPlainText()
    assert not window.raw_json.toPlainText()
    assert not window.copy_button.isEnabled() and not window.install_button.isEnabled()


def test_untrusted_inventory_text_is_never_rich_text(window, inventory):
    inventory['distribution']['name'] = '<b>untrusted-name</b>'
    inventory['sessions']['wayland'][0]['name'] = '<img src="https://invalid.example/remote">'
    scan(window)
    assert window.distribution_label.textFormat() == Qt.TextFormat.PlainText
    assert window.distribution_label.text() == '<b>untrusted-name</b>'
    assert window.sessions.item(0).text().startswith('<img')


def test_even_an_optimistic_plan_cannot_enable_install(window):
    scan(window)
    def optimistic(*args):
        plan = build_plan(*args)
        plan.update(status='ready', executable=True, compatibility='verified')
        return plan
    window.planner = optimistic
    window.update_plan()
    assert window.plan_status.text() == 'Not validated'
    assert not window.install_button.isEnabled()


def test_refresh_ignores_duplicate_requests_and_close_waits_for_scan(app, inventory):
    entered = threading.Event()
    released = threading.Event()
    calls = []
    def slow():
        calls.append(1)
        entered.set()
        released.wait(3)
        return inventory
    window = DesktopForgeWindow(detector=slow, auto_refresh=False)
    window.show()
    try:
        window.refresh_inventory()
        wait_for(entered.is_set)
        first = window._worker
        window.refresh_inventory()
        assert window._worker is first
        assert not window.refresh_button.isEnabled()
        window.close()
        assert window.isVisible()
        assert window._closing
        released.set()
        wait_for(lambda: not window.isVisible())
        assert len(calls) == 1
        assert window.inventory is None  # late results cannot repopulate a closing UI
    finally:
        released.set()
        window._worker.wait(5000)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_no_desktop_runtime_can_be_called_by_the_gui(window, monkeypatch):
    from desktopforge.launcher_runtime import OwnedChild, SessionLease
    from desktopforge.transient_session import TransientSession
    def forbidden(*args, **kwargs):
        pytest.fail('GUI invoked desktop runtime')
    monkeypatch.setattr(OwnedChild, 'start', forbidden)
    monkeypatch.setattr(SessionLease, '__enter__', forbidden)
    monkeypatch.setattr(TransientSession, 'start', forbidden)
    scan(window)
    window.shell.setCurrentIndex(window.shell.findData('dms'))
    window.shell.setCurrentIndex(window.shell.findData('noctalia'))
    assert not window.install_button.isEnabled()


def test_small_window_keeps_plan_view_scrollable_and_visible(window, app):
    scan(window)
    window.resize(880, 720)
    app.processEvents()
    assert window.operations.viewport().height() >= 100
    assert window.install_button.isVisible()
    assert window.refresh_button.isVisible()


def test_gui_source_helper_resolves_environment_outside_repo(tmp_path):
    script = Path(__file__).parents[1] / 'scripts/desktopforge-gui'
    result = subprocess.run([sys.executable, str(script), '--version'], cwd=tmp_path,
                            env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert 'DesktopForge 0.1.0' in result.stdout


def test_real_gui_entrypoint_exits_cleanly_after_window_close(tmp_path):
    code = r"""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from desktopforge.detection import detect_system
from desktopforge.gui import main
from desktopforge.gui import window
original = window.DesktopForgeWindow
class ClosingWindow(original):
    def __init__(self):
        super().__init__(detector=lambda: detect_system(root=Path(sys.argv[1]), environ={}, which=lambda _: None))
        QTimer.singleShot(250, self.close)
window.DesktopForgeWindow = ClosingWindow
raise SystemExit(main([]))
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'shared QObject was deleted' not in result.stderr


def test_service_correlation_is_displayed_as_hint_not_confirmed_active(window, inventory):
    inventory['session_analysis']['active_shell'] = {'name': None, 'confidence': 'unknown', 'reason': 'Ownership unproven'}
    inventory['session_analysis']['shell_correlation'] = {'confidence': 'corroborated_hints', 'shell_candidates': ['ryoku']}
    scan(window)
    assert window.facts['active_shell'].text() == 'Unknown (not confirmed)\nService hints: Ryoku'
    assert window.facts['active_shell'].toolTip() == 'Ownership unproven'


def test_gui_without_display_context_fails_cleanly_instead_of_qt_abort():
    result = subprocess.run([sys.executable, '-m', 'desktopforge.gui'],
        env={'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'No graphical display is available for this account' in result.stderr
    assert 'Could not load the Qt platform plugin' not in result.stderr


def test_package_tab_shows_versions_without_enabling_install(window, inventory):
    inventory['package_inventory']['packages'] = [
        {'name': 'niri', 'status': 'installed', 'reason': 'Observed local RPM header.',
         'records': [{'epoch': 0, 'version': '26.04', 'release': '2.fc45', 'architecture': 'x86_64'}]},
        {'name': 'noctalia', 'status': 'unknown', 'reason': 'RPM query timed out.', 'records': []},
    ]
    scan(window)
    text = window.packages.toPlainText()
    assert '0:26.04-2.fc45 (x86_64)' in text
    assert 'Reuse needs verification' in text and 'RPM query timed out.' in text
    assert 'originating repository' in text
    assert not window.install_button.isEnabled()
    window._scan_failed('Read failed')
    assert window.packages.toPlainText() == ''


def test_packages_tab_displays_both_ryoku_command_owners(window, inventory):
    inventory['package_inventory']['executable_ownership'] = [
        {'component': 'shell:ryoku', 'executable': command, 'path': '/usr/bin/' + command,
         'status': 'owned', 'owners': [command], 'reason': 'Local RPM owner.'}
        for command in ('ryoku', 'ryoku-shell')]
    scan(window)
    window.shell.setCurrentIndex(window.shell.findData('ryoku'))
    text = window.packages.toPlainText()
    assert 'ryoku: /usr/bin/ryoku → ryoku · package match not established' in text
    assert 'ryoku-shell: /usr/bin/ryoku-shell → ryoku-shell · matches package name' in text
    assert not window.install_button.isEnabled()
    assert window.plan['status'] == 'blocked'


def test_packages_tab_explains_recipe_roles_and_static_repository_flags(window, inventory):
    inventory['repository_evidence'] = {
        'status': 'static_only', 'declarations': [
            {'id': 'fedora', 'enabled': 'declared_on', 'gpgcheck': 'unspecified',
             'pkg_gpgcheck': 'unspecified', 'repo_gpgcheck': 'declared_off'}],
        'duplicate_ids': [], 'limitations': ['Installed-package origin remains unknown.']}
    scan(window)
    text = window.packages.toPlainText()
    assert 'noctalia · shell launcher · noctalia · major 5' in text
    assert 'fedora · enabled: on, gpgcheck: unspecified' in text
    assert 'Installed-package origin remains unknown.' in text
    assert not window.install_button.isEnabled()


def test_all_plan_tabs_are_visible_at_minimum_window_width(window, app):
    window.resize(880, 720)
    scan(window)
    app.processEvents()
    bar = window.tabs.tabBar()
    assert window.tabs.count() == 5
    assert window.tabs.tabText(4) == 'Packages'
    for index in range(window.tabs.count()):
        assert bar.rect().contains(bar.tabRect(index)), window.tabs.tabText(index)


def test_application_has_a_desktopforge_wayland_app_id(app):
    # Seen in the Niri session: the window's app ID was "python3".
    from desktopforge.gui.window import configure_application
    configure_application(app)
    assert app.desktopFileName() == 'dev.desktopforge.DesktopForge'


def test_gui_shows_an_intact_desktopforge_installation(app, inventory):
    from pathlib import Path
    from desktopforge import install_records
    from tests.test_install_records import PACKAGES, make_record
    installed = deepcopy(inventory)
    summary = install_records.summarize(make_record(), Path('/nonexistent'), PACKAGES)
    summary['status'] = 'intact'
    installed['desktopforge_installations'] = {'installations': [summary]}
    installed['rendering'] = {'status': 'hardware', 'nodes': [{'renderer': 'virgl'}]}
    widget = DesktopForgeWindow(detector=lambda: installed, auto_refresh=False)
    try:
        scan(widget)
        assert widget.plan['status'] == 'installed'
        assert widget.plan_status.text() == 'Installed by DesktopForge'
        installed['rendering'] = {'status': 'software-only', 'nodes': [{'renderer': 'llvmpipe'}]}
        scan(widget)
        assert widget.plan_status.text() == 'Installed by DesktopForge · warning'
        assert 'software rendering' in widget.plan_status.toolTip()
        assert 'Niri + Noctalia (DesktopForge)' in widget.plan_summary.text()
        assert widget.operations.rowCount() == 0 and not widget.install_button.isEnabled()
        assert widget.empty_operations.text().startswith('Nothing to do: DesktopForge already installed')
    finally:
        if widget._worker is not None:
            widget._worker.wait(5000)
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_gui_shows_graphics_capability(app, inventory):
    shown = deepcopy(inventory)
    shown['rendering'] = {'status': 'software-only', 'nodes': [
        {'node': '/dev/dri/renderD128', 'renderer': 'llvmpipe (LLVM 21.1.0)', 'renderer_class': 'software',
         'device_software': True}]}
    widget = DesktopForgeWindow(detector=lambda: shown, auto_refresh=False)
    try:
        scan(widget)
        assert widget.facts['graphics'].text() == 'Software rendering only · llvmpipe (LLVM 21.1.0)'
        assert any('software rendering' in b for b in widget.plan['blockers'])
    finally:
        if widget._worker is not None:
            widget._worker.wait(5000)
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
