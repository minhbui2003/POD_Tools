import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core import updater
from core.platform_utils import get_asset_path
from qt_gui.app import PODToolsWindow
from qt_gui.styles import build_app_style


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("POD Tools")
    app.setOrganizationName("POD Software")
    app.setStyleSheet(build_app_style(get_asset_path("checkmark.svg")))

    icon_path = get_asset_path("Logo_bg.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    updater.cleanup_update_artifacts()

    window = PODToolsWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
