import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import config, updater
from core.platform_utils import get_asset_path
from qt_gui.crawl_page import CrawlPage
from qt_gui.resize_page import ResizePage
from qt_gui.update_dialog import UpdateDialog


class PODToolsWindow(QMainWindow):
    update_available = Signal(str, str, str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("POD Software - Tools")
        self.resize(1120, 820)
        self.setMinimumSize(980, 720)
        self.nav_buttons = {}

        self._set_icon()
        self._build_ui()
        self.update_available.connect(self._show_update_dialog)
        self._init_updater()

    def _set_icon(self):
        icon_path = get_asset_path("Logo_bg.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 28, 14, 14)
        sidebar_layout.setSpacing(8)

        title = QLabel("POD TOOLS")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(title)
        sidebar_layout.addSpacing(12)

        self.pages = QStackedWidget()
        self.crawl_page = CrawlPage()
        self.resize_page = ResizePage()
        self.pages.addWidget(self.crawl_page)
        self.pages.addWidget(self.resize_page)

        self._add_nav(sidebar_layout, "crawl", "Crawl Image", 0, "icon_crawl.png")
        self._add_nav(sidebar_layout, "resize", "Resize Image", 1, "icon_resize.png")
        sidebar_layout.addStretch(1)

        version = QLabel(f"Version {config.CURRENT_VERSION}")
        version.setObjectName("sidebarFooter")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version)

        credit = QLabel("By IT POD SOFTWARE")
        credit.setObjectName("sidebarFooter")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(credit)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.pages, 1)
        self._switch_page("crawl")

    def _add_nav(self, layout, key, text, page_index, icon_name=None):
        button = QPushButton(text)
        button.setProperty("navButton", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(44)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if icon_name:
            icon_path = get_asset_path(icon_name)
            if os.path.exists(icon_path):
                button.setIcon(QIcon(icon_path))
                button.setIconSize(QSize(22, 22))
        button.clicked.connect(lambda: self._switch_page(key))
        layout.addWidget(button)
        self.nav_buttons[key] = (button, page_index)

    def _switch_page(self, key):
        button, index = self.nav_buttons[key]
        self.pages.setCurrentIndex(index)
        for nav_button, _ in self.nav_buttons.values():
            nav_button.setProperty("active", nav_button is button)
            nav_button.style().unpolish(nav_button)
            nav_button.style().polish(nav_button)

    def _init_updater(self):
        def on_update_found(new_version, release_notes, download_url, sha256):
            self.update_available.emit(new_version, release_notes, download_url, sha256)

        updater.check_for_updates(
            on_update_found,
            dispatch_callback=lambda fn, *args: QTimer.singleShot(0, lambda: fn(*args)),
        )

    def _show_update_dialog(self, new_version, release_notes, download_url, sha256):
        dialog = UpdateDialog(self, new_version, release_notes, download_url, sha256)
        dialog.exec()
