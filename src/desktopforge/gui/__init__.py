"""Optional read-only Qt GUI. Importing the core/CLI never requires Qt."""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='desktopforge-gui', description='DesktopForge system inventory and plan preview')
    parser.add_argument('--version', action='version', version='DesktopForge 0.1.0')
    parser.parse_args(argv)
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from .window import DesktopForgeWindow, configure_application
    except ModuleNotFoundError as exc:
        if (exc.name or '').split('.')[0] != 'PySide6':
            raise
        print('The GUI requires the optional PySide6 dependency. Use scripts/desktopforge-gui '
              'with the prepared project environment, or install the project GUI extra in a virtual environment.',
              file=sys.stderr)
        return 1
    if (QApplication.instance() is None and not os.environ.get('WAYLAND_DISPLAY')
            and not os.environ.get('DISPLAY')
            and os.environ.get('QT_QPA_PLATFORM') not in ('offscreen', 'minimal')):
        print('No graphical display is available for this account. Open DesktopForge from a terminal '
              'in your normal desktop session.', file=sys.stderr)
        return 1
    app = QApplication.instance() or QApplication(['desktopforge-gui'])
    configure_application(app)
    window = DesktopForgeWindow()
    window.show()
    try:
        return app.exec()
    finally:
        window.finish_pending_scan()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
