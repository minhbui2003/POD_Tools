BG = "#f5f7fa"
PANEL_BG = "#FFFFFF"
PANEL_BORDER = "#D6DCE5"
TEXT = "#000000"
MUTED = "#475569"
ACCENT = "#355C8A"

BUTTON_PRIMARY_BG = "#DCEEFF"
BUTTON_PRIMARY_BORDER = "#9FC3E8"
BUTTON_SECONDARY_BG = "#EAF0F6"
BUTTON_SECONDARY_BORDER = "#C7D0DB"
BUTTON_STOP_BG = "#FDE2E2"
BUTTON_STOP_BORDER = "#E7B3B3"
BUTTON_START_BG = "#DFF4EA"
BUTTON_START_BORDER = "#A9D8BD"


def build_app_style(checkmark_path=""):
    checkmark_rule = ""
    if checkmark_path:
        safe_path = checkmark_path.replace("\\", "/")
        checkmark_rule = f"""
QCheckBox::indicator:checked {{
    image: url("{safe_path}");
}}
QRadioButton::indicator:checked {{
    image: url("{safe_path}");
}}
"""

    return f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Arial";
    font-size: 10pt;
}}
QFrame#sidebar {{
    background: #FFFFFF;
    border-right: 1px solid {PANEL_BORDER};
}}
QLabel#appTitle {{
    background: transparent;
    color: {TEXT};
    font-size: 18pt;
    font-weight: 900;
}}
QLabel#sidebarFooter {{
    background: transparent;
    color: {TEXT};
    font-size: 9pt;
    font-weight: 600;
}}
QFrame[card="true"] {{
    background: {PANEL_BG};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
}}
QLineEdit, QComboBox {{
    background: #FFFFFF;
    color: {TEXT};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 6px;
}}
QPlainTextEdit, QTextEdit {{
    background: #FFFFFF;
    color: {TEXT};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 6px;
    font-family: "Consolas", "Menlo", monospace;
    font-size: 9pt;
}}
QPushButton {{
    background: {BUTTON_SECONDARY_BG};
    color: {TEXT};
    border: 1px solid {BUTTON_SECONDARY_BORDER};
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: {BUTTON_PRIMARY_BORDER};
}}
QPushButton:pressed {{
    background: #DDE6F0;
}}
QPushButton:disabled {{
    color: {TEXT};
    background: #F2F5F8;
    border-color: {PANEL_BORDER};
}}
QPushButton[startButton="true"] {{
    background: {BUTTON_START_BG};
    border-color: {BUTTON_START_BORDER};
}}
QPushButton[primaryButton="true"] {{
    background: {BUTTON_PRIMARY_BG};
    border-color: {BUTTON_PRIMARY_BORDER};
}}
QPushButton[stopButton="true"] {{
    background: {BUTTON_STOP_BG};
    border-color: {BUTTON_STOP_BORDER};
}}
QPushButton[navButton="true"] {{
    background: #FFFFFF;
    border-color: #FFFFFF;
    text-align: center;
    padding: 12px;
    font-size: 12pt;
    font-weight: 800;
}}
QPushButton[navButton="true"][active="true"] {{
    background: #DCEEFF;
    border-color: #9FC3E8;
}}
QCheckBox, QRadioButton {{
    color: {TEXT};
    spacing: 8px;
    padding: 4px;
}}
QCheckBox:checked, QRadioButton:checked {{
    font-weight: 700;
}}
QRadioButton:checked {{
    background: #F3F8FF;
    border: 1px solid {BUTTON_PRIMARY_BORDER};
    border-radius: 6px;
}}
QCheckBox:checked {{
    background: #F7FBFF;
    border-radius: 6px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid #8EA2B8;
    background: #FFFFFF;
}}
QRadioButton::indicator:hover {{
    border-color: {BUTTON_PRIMARY_BORDER};
}}
QRadioButton::indicator:checked {{
    border: 2px solid {ACCENT};
    background: {BUTTON_PRIMARY_BG};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid #8EA2B8;
    background: #FFFFFF;
}}
QCheckBox::indicator:hover {{
    border-color: {BUTTON_PRIMARY_BORDER};
}}
QCheckBox::indicator:checked {{
    border-color: {ACCENT};
    background: {BUTTON_PRIMARY_BG};
}}
{checkmark_rule}
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {{
    border-color: #94A3B8;
    background: #EAF0F6;
}}
QTabWidget::pane {{
    border: 0;
}}
QTabBar::tab {{
    background: #FFFFFF;
    color: {MUTED};
    border: 1px solid {PANEL_BORDER};
    border-radius: 6px;
    padding: 8px 14px;
    margin: 2px;
}}
QTabBar::tab:selected {{
    background: {BUTTON_PRIMARY_BG};
    color: {TEXT};
    border-color: {BUTTON_PRIMARY_BORDER};
}}
QProgressBar {{
    background: {BUTTON_SECONDARY_BG};
    border: 1px solid {PANEL_BORDER};
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {BUTTON_START_BG};
    border-radius: 4px;
}}
"""


APP_STYLE = build_app_style()
