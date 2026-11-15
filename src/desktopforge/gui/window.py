"""Read-only GUI: inventory and plan rendering only; no launcher/executor calls."""
from __future__ import annotations

import html
import json
import os
import pwd
from typing import Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMainWindow,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from ..detection import detect_system
from ..planning import build_plan
from ..recipes import COMPOSITORS, SHELLS

LABELS = {'niri': 'Niri', 'hyprland': 'Hyprland', 'noctalia': 'Noctalia',
          'dms': 'DankMaterialShell (DMS)', 'ryoku': 'Ryoku'}

STYLE = '''
QWidget { color: #e5eaf2; font-size: 13px; }
QMainWindow, QWidget#canvas { background: #10151e; }
QFrame#card { background: #19212e; border: 1px solid #2b374a; border-radius: 12px; }
QLabel#brand { color: #f3f6fc; font-size: 22px; font-weight: 700; }
QLabel#title { font-size: 27px; font-weight: 700; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #a3b1c5; }
QLabel#eyebrow { color: #91a7c5; font-size: 11px; font-weight: 700; }
QLabel#previewBadge { background: #243543; color: #91dccd; border: 1px solid #395866;
    border-radius: 7px; padding: 7px 12px; font-weight: 600; }
QLabel#planStatus { color: #f0c477; font-size: 15px; font-weight: 600; }
QPushButton { background: #29364a; border: 1px solid #41516a; border-radius: 7px; padding: 9px 15px; }
QPushButton:hover { background: #344760; }
QPushButton:focus, QComboBox:focus { border: 1px solid #89d6c5; }
QPushButton:disabled { color: #8c98aa; background: #222b39; border-color: #344055; }
QPushButton#primary { color: #102320; background: #90d7c5; border: 1px solid #90d7c5; font-weight: 600; }
QPushButton#primary:disabled { color: #8c98aa; background: #222b39; border-color: #344055; }
QComboBox { background: #101722; border: 1px solid #40516c; border-radius: 7px; padding: 10px; min-height: 20px; }
QComboBox QAbstractItemView { background: #1c2736; selection-background-color: #344b65; }
QListWidget, QPlainTextEdit, QTextBrowser, QTableWidget { background: #131b27;
    border: 1px solid #2b374a; border-radius: 7px; padding: 7px; selection-background-color: #345b70; }
QTableWidget { gridline-color: #2b374a; }
QHeaderView::section { background: #202c3d; color: #aebed4; border: none; padding: 9px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #aab8cc; padding: 10px 15px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #91dccd; border-bottom: 2px solid #91dccd; }
QStatusBar { background: #151c28; color: #9daec5; }
QProgressBar { border: 1px solid #3a5063; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #90d7c5; }
QSplitter::handle { background: transparent; width: 12px; }
'''


def configure_application(app: QApplication) -> None:
    app.setApplicationName('DesktopForge')
    app.setOrganizationName('DesktopForge')
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor('#10151e'))
    palette.setColor(QPalette.ColorRole.WindowText, QColor('#e5eaf2'))
    palette.setColor(QPalette.ColorRole.Base, QColor('#131b27'))
    palette.setColor(QPalette.ColorRole.Text, QColor('#e5eaf2'))
    palette.setColor(QPalette.ColorRole.Button, QColor('#29364a'))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor('#e5eaf2'))
    palette.setColor(QPalette.ColorRole.Highlight, QColor('#345b70'))
    app.setPalette(palette)
    app.setFont(QFont('Sans Serif', 10))
    app.setStyleSheet(STYLE)


def label(text: str = '', role: str = '') -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName('card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    return frame, layout


class InventoryWorker(QThread):
    detected = Signal(object)
    failed = Signal(str)

    def __init__(self, detector: Callable, parent=None):
        super().__init__(parent)
        self.detector = detector

    def run(self) -> None:
        try:
            self.detected.emit(self.detector())
        except Exception as exc:
            self.failed.emit(str(exc))


class DesktopForgeWindow(QMainWindow):
    def __init__(self, *, detector: Callable = detect_system, planner: Callable = build_plan,
                 auto_refresh: bool = True):
        super().__init__()
        self.detector = detector
        self.planner = planner
        self.inventory: dict | None = None
        self.plan: dict | None = None
        self._worker: InventoryWorker | None = None
        self._closing = False
        self.setWindowTitle('DesktopForge — Desktop session planner')
        self.resize(1120, 880)
        self.setMinimumSize(880, 720)
        self._build_ui()
        self._set_choices_enabled(False)
        if auto_refresh:
            QTimer.singleShot(0, self.refresh_inventory)

    def _build_ui(self) -> None:
        canvas = QWidget()
        canvas.setObjectName('canvas')
        self.setCentralWidget(canvas)
        root = QVBoxLayout(canvas)
        root.setContentsMargins(26, 22, 26, 16)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(label('DesktopForge', 'brand'))
        header.addStretch()
        header.addWidget(label('READ-ONLY PREVIEW', 'previewBadge'))
        self.refresh_button = QPushButton('Refresh system')
        self.refresh_button.setObjectName('refreshButton')
        self.refresh_button.clicked.connect(self.refresh_inventory)
        header.addWidget(self.refresh_button)
        root.addLayout(header)
        root.addWidget(label('Explore your next desktop', 'title'))
        root.addWidget(label('Inspect your system, choose a combination, and see what a separate login session would require.', 'muted'))
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(14)
        self.system_card, system = card()
        self.system_card.setMinimumWidth(260)
        system.addWidget(label('YOUR SYSTEM', 'eyebrow'))
        self.distribution_label = label('Waiting for detection', 'section')
        system.addWidget(self.distribution_label)
        self.account_label = label(f'Inspecting account: {pwd.getpwuid(os.getuid()).pw_name}', 'muted')
        system.addWidget(self.account_label)
        self.facts = {}
        for key, title in (('display_manager', 'Display manager'), ('desktop', 'Current desktop'),
                           ('active_shell', 'Active shell')):
            system.addWidget(label(title.upper(), 'eyebrow'))
            self.facts[key] = label('Not scanned')
            system.addWidget(self.facts[key])
        system.addWidget(label('Registered login sessions', 'section'))
        self.sessions = QListWidget()
        self.sessions.setObjectName('registeredSessions')
        self.sessions.setMinimumHeight(100)
        self.sessions.setWordWrap(True)
        system.addWidget(self.sessions, 1)
        system.addWidget(label('A registered session or executable is evidence, not proof of a working installation.', 'muted'))
        split.addWidget(self.system_card)
        right = QWidget()
        content = QVBoxLayout(right)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        choose_card, choose = card()
        choose.addWidget(label('Choose a combination', 'section'))
        choose.addWidget(label('All combinations are research targets. None is validated for installation yet.', 'muted'))
        choices = QGridLayout()
        choices.addWidget(label('Compositor'), 0, 0)
        choices.addWidget(label('Desktop shell'), 0, 1)
        self.compositor = QComboBox()
        self.compositor.setObjectName('compositorChoice')
        self.compositor.setAccessibleName('Compositor')
        self.shell = QComboBox()
        self.shell.setObjectName('shellChoice')
        self.shell.setAccessibleName('Desktop shell')
        for value in COMPOSITORS:
            self.compositor.addItem(LABELS[value], value)
        for value in SHELLS:
            self.shell.addItem(LABELS[value], value)
        self.compositor.currentIndexChanged.connect(self.update_plan)
        self.shell.currentIndexChanged.connect(self.update_plan)
        choices.addWidget(self.compositor, 1, 0)
        choices.addWidget(self.shell, 1, 1)
        choose.addLayout(choices)
        self.component_evidence = label('Executable availability will appear after detection.', 'muted')
        choose.addWidget(self.component_evidence)
        content.addWidget(choose_card)
        preview_card, preview = card()
        heading = QHBoxLayout()
        heading.addWidget(label('Installation plan', 'section'))
        heading.addStretch()
        self.plan_status = label('Scan the system first', 'planStatus')
        heading.addWidget(self.plan_status)
        preview.addLayout(heading)
        self.plan_summary = label('Nothing will be installed or changed in this preview.', 'muted')
        preview.addWidget(self.plan_summary)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(250)
        self.operations_page = QWidget()
        operations_layout = QVBoxLayout(self.operations_page)
        operations_layout.setContentsMargins(0, 12, 0, 0)
        self.operations = QTableWidget(0, 3)
        self.operations.setObjectName('operationProposals')
        self.operations.setHorizontalHeaderLabels(['Proposal', 'Permissions needed', 'Details'])
        self.operations.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.operations.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.operations.setWordWrap(True)
        self.operations.verticalHeader().setVisible(False)
        self.operations.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.operations.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.operations.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.empty_operations = label('Waiting for system detection.', 'muted')
        operations_layout.addWidget(self.empty_operations)
        operations_layout.addWidget(self.operations, 1)
        self.tabs.addTab(self.operations_page, 'Proposals')
        self.requirements = QPlainTextEdit()
        self.requirements.setObjectName('reviewRequirements')
        self.requirements.setReadOnly(True)
        self.requirements.setPlaceholderText('Review requirements will appear here.')
        self.tabs.addTab(self.requirements, 'Requirements')
        self.sources = QTextBrowser()
        self.sources.setObjectName('recipeSources')
        self.sources.setOpenExternalLinks(True)
        self.tabs.addTab(self.sources, 'References')
        self.raw_json = QPlainTextEdit()
        self.raw_json.setObjectName('planJson')
        self.raw_json.setReadOnly(True)
        self.raw_json.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.raw_json, 'JSON details')
        self.packages = QPlainTextEdit()
        self.packages.setReadOnly(True)
        self.packages.setObjectName('packageEvidence')
        self.tabs.addTab(self.packages, 'Packages')
        preview.addWidget(self.tabs, 1)
        self.preservation = label('The plan must preserve your existing display manager, sessions and user configuration.', 'muted')
        preview.addWidget(self.preservation)
        actions = QHBoxLayout()
        self.copy_button = QPushButton('Copy plan JSON')
        self.copy_button.clicked.connect(self.copy_plan)
        self.copy_button.setEnabled(False)
        actions.addWidget(self.copy_button)
        actions.addStretch()
        self.review_button = QPushButton('Review requirements')
        self.review_button.setObjectName('primary')
        self.review_button.clicked.connect(self.show_requirements)
        self.review_button.setEnabled(False)
        actions.addWidget(self.review_button)
        preview.addLayout(actions)
        content.addWidget(preview_card, 1)
        footer = QHBoxLayout()
        footer.addWidget(label('Installation is unavailable until recipes and the privileged helper are validated.', 'muted'), 1)
        self.install_button = QPushButton('Installation unavailable')
        self.install_button.setObjectName('installButton')
        self.install_button.setEnabled(False)
        self.install_button.setToolTip('This GUI only detects and previews. It has no installation or desktop-launch action.')
        footer.addWidget(self.install_button)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(510)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 770])
        root.addWidget(split, 1)
        root.addLayout(footer)
        self.status_label = label('Ready to inspect this system', 'muted')
        self.statusBar().addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

    def _set_choices_enabled(self, enabled: bool) -> None:
        self.compositor.setEnabled(enabled)
        self.shell.setEnabled(enabled)

    def refresh_inventory(self) -> None:
        if self._closing or (self._worker is not None and self._worker.isRunning()):
            return
        self.inventory = None
        self.plan = None
        self._set_choices_enabled(False)
        self.copy_button.setEnabled(False)
        self.review_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.plan_status.setText('Detecting…')
        self.plan_summary.setText('Reading local system and package evidence. No installation actions are run.')
        self.operations.setRowCount(0)
        self.operations.hide()
        self.empty_operations.setText('Waiting for system detection.')
        self.empty_operations.show()
        self.packages.clear()
        self.requirements.clear()
        self.raw_json.clear()
        self.sources.clear()
        self.sessions.clear()
        self.distribution_label.setText('Detecting system…')
        for value in self.facts.values():
            value.setText('Detecting…')
        self.component_evidence.setText('Checking executable availability…')
        self.status_label.setText('Reading distribution, session files and process evidence…')
        self.progress.show()
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = InventoryWorker(self.detector, self)
        self._worker.detected.connect(self._inventory_ready)
        self._worker.failed.connect(self._scan_failed)
        self._worker.finished.connect(self._scan_finished)
        self._worker.start()

    def _inventory_ready(self, inventory: dict) -> None:
        if self._closing:
            return
        try:
            distro = inventory['distribution']
            self.distribution_label.setText(distro.get('name') or distro.get('id') or 'Unknown distribution')
            dm = inventory['display_manager']
            self.facts['display_manager'].setText(f"{({'sddm': 'SDDM', 'gdm': 'GDM', 'lightdm': 'LightDM'}.get(dm.get('name'), dm.get('name'))) or 'Unknown'} · {dm.get('confidence', 'unknown')}")
            session = inventory['current_session']
            self.facts['desktop'].setText(f"{session.get('desktop') or 'Unknown'} · {session.get('session_type') or 'type unknown'}")
            active = inventory['session_analysis']['active_shell']
            if active.get('name'):
                shell_text = f"{LABELS.get(active['name'], active['name'])} · {active['confidence']}"
            else:
                shell_text = 'Unknown (not confirmed)'
                correlation = inventory['session_analysis'].get('shell_correlation', {})
                hints = correlation.get('shell_candidates', [])
                if correlation.get('confidence') == 'corroborated_hints' and hints:
                    shell_text += '\nService hints: ' + ', '.join(LABELS.get(name, name) for name in hints)
            self.facts['active_shell'].setText(shell_text)
            self.facts['active_shell'].setToolTip(active.get('reason', ''))
            for kind in ('wayland', 'x11'):
                for entry in inventory['sessions'].get(kind, []):
                    self.sessions.addItem(f"{entry['name']}  ·  {kind.upper()}")
            if not self.sessions.count():
                self.sessions.addItem('No registered sessions found')
            self.inventory = inventory
            self._set_choices_enabled(True)
            self.status_label.setText('Inventory updated · read-only · no installation compatibility has been validated')
            self.update_plan()
        except Exception as exc:
            self._scan_failed(str(exc))

    def _scan_failed(self, message: str) -> None:
        self.inventory = None
        self.plan = None
        self._set_choices_enabled(False)
        self.copy_button.setEnabled(False)
        self.review_button.setEnabled(False)
        self.packages.clear()
        self.distribution_label.setText('Detection unavailable')
        for value in self.facts.values():
            value.setText('Unavailable')
        self.sessions.clear()
        self.component_evidence.setText('Executable evidence is unavailable until detection succeeds.')
        self.plan_status.setText('Detection unavailable')
        self.plan_summary.setText('Refresh to try again. A plan cannot be built from incomplete detection.')
        self.requirements.setPlainText(message or 'Unknown detection error')
        self.tabs.setCurrentIndex(1)
        self.status_label.setText('System inspection failed; no changes were made')

    def _scan_finished(self) -> None:
        self.progress.hide()
        if self._closing:
            self.close()
        else:
            self.refresh_button.setEnabled(True)

    def update_plan(self, *_args) -> None:
        if self.inventory is None or self._closing:
            return
        try:
            compositor = self.compositor.currentData()
            shell = self.shell.currentData()
            plan = self.planner(self.inventory, compositor, shell)
            self.plan = plan
            compatibility = {'unverified': 'Unverified target', 'unsupported': 'Outside current recipe scope'}.get(
                plan['compatibility'], 'Not validated')
            self.plan_status.setText(compatibility)
            self.plan_summary.setText(f"{LABELS[compositor]} + {LABELS[shell]} · Session ID preview: {plan['session_id_preview']}")
            evidence = plan['component_evidence']
            self.component_evidence.setText(
                f"{LABELS[compositor]}: {'found on PATH' if evidence['compositor_executable_found'] else 'not found on PATH'}  ·  "
                f"{LABELS[shell]}: {'found on PATH' if evidence['shell_executable_found'] else 'not found on PATH'}")
            operations = plan['operations']
            self.operations.setRowCount(len(operations))
            self.operations.setVisible(bool(operations))
            self.empty_operations.setVisible(not operations)
            self.empty_operations.setText('No operation recipe is available for this target. Requirements explain what is missing.')
            names = {'dependency_check': 'Dependency check', 'package_proposal': 'Package proposal', 'session_proposal': 'Session proposal'}
            for index, operation in enumerate(operations):
                permission = 'Administrator approval' if operation['privilege'] == 'system' else 'No extra permissions'
                for column, text in enumerate((f"{index + 1}. {names.get(operation['type'], operation['type'])}", permission, operation['summary'])):
                    self.operations.setItem(index, column, QTableWidgetItem(text))
            self.operations.resizeRowsToContents()
            blockers = plan['blockers']
            self.tabs.setTabText(1, f'Requirements ({len(blockers)})')
            self.requirements.setPlainText('\n\n'.join(f'{i + 1}. {reason}' for i, reason in enumerate(blockers)))
            assessment = plan.get('package_assessment', {})
            package_lines = []
            for package in assessment.get('packages', []):
                versions = ', '.join(f"{row['epoch']}:{row['version']}-{row['release']} ({row['architecture']})" for row in package['records'])
                package_lines.append(f"{package['name']}: {package['status']}" + (f' — {versions}' if versions else ''))
                package_lines.append(package['reason'])
                ownerships = package.get('executable_ownerships') or [package.get('executable_ownership', {})]
                for ownership in ownerships:
                    path = ownership.get('path') or 'path unavailable'
                    command = ownership.get('executable')
                    owner_text = ', '.join(ownership.get('owners', [])) or 'owner unknown'
                    match_text = 'matches package name' if ownership.get('owner_matches_package') else 'package match not established'
                    command_text = f"{command}: " if command else ''
                    package_lines.append(f"Executable owner: {command_text}{path} → {owner_text} · {match_text}")
                    package_lines.append(ownership.get('reason', ''))
                package_lines.append(('Reuse needs verification' if package['reuse'] == 'candidate_unverified' else 'No reuse candidate established') + '\n')
            requirements = plan.get('requirement_assessment', {})
            if requirements.get('findings'):
                package_lines.append('Recipe command requirements (reuse remains unverified):')
                roles = {'compositor': 'compositor', 'shell_launcher': 'shell launcher',
                         'session_launcher': 'session launcher', 'management': 'management command'}
                for finding in requirements['findings']:
                    version = f"major {finding['required_major']}" if finding['required_major'] is not None else 'version not constrained'
                    package_lines.append(f"{finding['executable']} · {roles[finding['role']]} · {finding['package']} · {version}: {finding['status']}")
                    package_lines.extend(finding['reasons'])
                package_lines.append('')
            package_lines.extend(assessment.get('limitations', []))
            self.packages.setPlainText('\n'.join(package_lines) or 'Package evidence unavailable.')
            sources = plan.get('recipe_sources', [])
            if sources:
                self.sources.setHtml('<p>Reviewed source references; these do not certify installation support.</p>' + ''.join(
                    f'<p><a style="color:#90d7c5" href="{html.escape(url, quote=True)}">{html.escape(url)}</a></p>' for url in sources))
            else:
                self.sources.setPlainText('No recipe source references are available for this target yet.')
            self.raw_json.setPlainText(json.dumps({'inventory': self.inventory, 'plan': plan}, indent=2, sort_keys=True))
            self.copy_button.setEnabled(True)
            self.review_button.setEnabled(True)
        except Exception as exc:
            self.plan = None
            self.operations.setRowCount(0)
            self.operations.hide()
            self.empty_operations.setText('Plan unavailable. Review the error and refresh to retry.')
            self.empty_operations.show()
            self.packages.clear()
            self.plan_status.setText('Plan unavailable')
            self.plan_summary.setText('No operations can be proposed for this selection.')
            self.requirements.setPlainText(str(exc))
            self.raw_json.clear()
            self.sources.clear()
            self.copy_button.setEnabled(False)
            self.review_button.setEnabled(False)
            self.tabs.setCurrentIndex(1)
        # No state, including malformed/optimistic core results, can enable apply.
        self.install_button.setEnabled(False)

    def show_requirements(self) -> None:
        self.tabs.setCurrentIndex(1)

    def copy_plan(self) -> None:
        if self.plan is not None:
            QApplication.clipboard().setText(json.dumps(self.plan, indent=2, sort_keys=True))
            self.status_label.setText('Plan JSON copied · preview only')

    def finish_pending_scan(self) -> None:
        self._closing = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._closing = True
            self._set_choices_enabled(False)
            self.refresh_button.setEnabled(False)
            self.status_label.setText('Finishing read-only inspection before closing…')
            event.ignore()
        else:
            event.accept()
