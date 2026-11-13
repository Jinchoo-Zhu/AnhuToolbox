# -*- coding: utf-8 -*-
"""第一阶段 UI 设计规则，目前仅由 HTTP 页面使用。"""


FONT_UI = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

COLOR_PRIMARY = "#0078D4"
COLOR_PRIMARY_HOVER = "#106EBE"
COLOR_PRIMARY_SOFT = "#EAF4FF"
COLOR_PRIMARY_BORDER = "#B8D9F5"
COLOR_VARIABLE = "#00A6A6"
COLOR_PAGE_BG = "#F4F7FA"
COLOR_SURFACE = "#FFFFFF"
COLOR_SURFACE_SUBTLE = "#F8FAFC"
COLOR_SURFACE_HOVER = "#F1F6FB"
COLOR_BORDER = "#D8E0E8"
COLOR_BORDER_STRONG = "#C6D0DA"
COLOR_DIVIDER = "#E9EEF3"
COLOR_TEXT = "#1F2937"
COLOR_TEXT_SECONDARY = "#5F6B7A"
COLOR_TEXT_MUTED = "#8A96A3"
COLOR_DANGER = "#C42B1C"
COLOR_DANGER_SOFT = "#FDF3F2"
COLOR_DANGER_BORDER = "#E8C5C0"

RADIUS_SMALL = 4
RADIUS_CARD = 6

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16

ICON_SIZE = 16
CONTROL_HEIGHT = 32
TAB_CONTROL_SIZE = 30
TABLE_ROW_HEIGHT = 38
DOCUMENT_TAB_WIDTH = 220

HTTP_METHOD_COLORS = {
    "GET": "#0B8F58",
    "POST": "#D48806",
    "PUT": "#0078D4",
    "PATCH": "#8B5CF6",
    "DELETE": "#C42B1C",
    "HEAD": "#0086A8",
    "OPTIONS": "#6B7280",
}


HTTP_TABLE_STYLE = f"""
QTableWidget {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    gridline-color: {COLOR_DIVIDER};
    selection-background-color: {COLOR_PRIMARY_SOFT};
    selection-color: {COLOR_TEXT};
    font-family: "{FONT_UI}";
    font-size: 13px;
    outline: 0;
}}
QTableWidget::item {{
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid {COLOR_DIVIDER};
}}
QTableWidget::item:hover {{
    background-color: {COLOR_SURFACE_SUBTLE};
}}
QTableWidget::item:selected {{
    background-color: {COLOR_PRIMARY_SOFT};
    color: {COLOR_TEXT};
}}
QHeaderView::section {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-right: 1px solid {COLOR_DIVIDER};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 5px 8px;
    font-family: "{FONT_UI}";
    font-size: 12px;
    font-weight: 600;
}}
QHeaderView::section:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
"""


HTTP_CODE_EDITOR_STYLE = f"""
QPlainTextEdit {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 8px;
    selection-background-color: #C9E4FA;
    font-family: "{FONT_MONO}";
    font-size: 13px;
}}
QPlainTextEdit:hover {{
    border-color: {COLOR_BORDER_STRONG};
}}
QPlainTextEdit:focus {{
    border-color: {COLOR_PRIMARY};
}}
QPlainTextEdit:disabled {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_MUTED};
    border-color: {COLOR_DIVIDER};
}}
"""


HTTP_PAGE_STYLE = f"""
QWidget#httpPage {{
    background-color: {COLOR_PAGE_BG};
}}
QWidget#httpPage QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
}}
QLabel#httpSectionTitle {{
    color: {COLOR_TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#httpHint {{
    color: {COLOR_TEXT_MUTED};
    font-size: 12px;
}}
QWidget#httpTabSurface,
QWidget#httpRequestPanel,
QWidget#httpResponsePanel {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QToolButton[httpTabControl="true"] {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS_SMALL}px;
    color: {COLOR_TEXT_SECONDARY};
    padding: 0;
}}
QToolButton[httpTabControl="true"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QToolButton[httpTabControl="true"]:pressed {{
    background-color: {COLOR_PRIMARY_SOFT};
}}
QToolButton[httpTabControl="true"]:disabled {{
    background-color: transparent;
    color: #C4CDD6;
}}
QToolButton#httpNewDocument {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 0;
}}
QToolButton#httpNewDocument:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QToolButton#httpEnvironmentButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 0 24px 0 9px;
    font-size: 12px;
}}
QToolButton#httpEnvironmentButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_PRIMARY_BORDER};
    color: {COLOR_PRIMARY};
}}
QTabBar#httpDocuments {{
    background-color: transparent;
}}
QTabBar#httpDocuments::tab {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid transparent;
    border-radius: {RADIUS_SMALL}px;
    padding: 5px 12px;
    margin-right: 3px;
    font-size: 12px;
}}
QTabBar#httpDocuments::tab:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QTabBar#httpDocuments::tab:selected {{
    background-color: {COLOR_PRIMARY_SOFT};
    color: {COLOR_TEXT};
    border-color: {COLOR_PRIMARY_BORDER};
    font-weight: 600;
}}
QLineEdit,
QSpinBox,
QComboBox {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px 9px;
    min-height: 22px;
    font-family: "{FONT_UI}";
    font-size: 13px;
    font-weight: 400;
}}
QComboBox QAbstractItemView {{
    font-family: "{FONT_UI}";
    font-size: 13px;
    font-weight: 400;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    min-height: 28px;
    font-family: "{FONT_UI}";
    font-size: 13px;
    font-weight: 400;
}}
QComboBox QAbstractItemView::item:selected {{
    font-weight: 400;
}}
QWidget#httpUrlShell {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
}}
QWidget#httpUrlShell:hover {{
    border-color: {COLOR_PRIMARY_BORDER};
}}
QWidget#httpUrlShell[focused="true"] {{
    border-color: {COLOR_PRIMARY};
}}
QWidget#httpUrlShell QPlainTextEdit#httpUrlEditor {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    padding: 5px 9px;
}}
QWidget#httpUrlShell QComboBox#httpVersionCombo {{
    background-color: transparent;
    border: none;
    border-left: 1px solid {COLOR_DIVIDER};
    border-radius: 0;
    padding: 0 8px;
    min-height: 30px;
    color: {COLOR_TEXT_SECONDARY};
}}
QWidget#httpUrlShell QComboBox#httpVersionCombo:hover,
QWidget#httpUrlShell QComboBox#httpVersionCombo:focus {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QPlainTextEdit#httpUrlEditor {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 5px 9px;
    selection-background-color: #C9E4FA;
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QPlainTextEdit#httpUrlEditor:hover {{
    border-color: {COLOR_PRIMARY_BORDER};
}}
QPlainTextEdit#httpUrlEditor:focus {{
    border-color: {COLOR_PRIMARY};
}}
QLineEdit:hover,
QSpinBox:hover,
QComboBox:hover,
QLineEdit:focus,
QSpinBox:focus,
QComboBox:focus {{
    border-color: {COLOR_PRIMARY_BORDER};
}}
QLineEdit:focus,
QSpinBox:focus,
QComboBox:focus {{
    border-color: {COLOR_PRIMARY};
}}
QLineEdit:disabled,
QSpinBox:disabled,
QComboBox:disabled {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_MUTED};
    border-color: {COLOR_DIVIDER};
}}
QPushButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px 12px;
    min-height: 22px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_PRIMARY_BORDER};
    color: {COLOR_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {COLOR_PRIMARY_SOFT};
}}
QPushButton:disabled {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_MUTED};
    border-color: {COLOR_DIVIDER};
}}
QPushButton#httpSend {{
    background-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    border-color: {COLOR_PRIMARY};
    padding: 4px 18px;
    font-weight: 600;
}}
QPushButton#httpSend:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border-color: {COLOR_PRIMARY_HOVER};
    color: #FFFFFF;
}}
QPushButton#httpSend:disabled {{
    background-color: #B7C9DB;
    border-color: #B7C9DB;
    color: #FFFFFF;
}}
QToolButton#httpRowDelete {{
    background-color: transparent;
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 0;
}}
QToolButton#httpRowDelete:hover {{
    background-color: {COLOR_DANGER_SOFT};
}}
QWidget#httpRowActionHost {{
    background-color: transparent;
}}
QTabWidget#httpRequestTabs::pane,
QTabWidget#httpResponseTabs::pane,
QTabWidget#httpActualTabs::pane {{
    background-color: {COLOR_SURFACE};
    border: none;
    border-top: 1px solid {COLOR_DIVIDER};
}}
QTabWidget#httpRequestTabs QTabBar::tab,
QTabWidget#httpResponseTabs QTabBar::tab,
QTabWidget#httpActualTabs QTabBar::tab {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 13px;
    font-size: 13px;
}}
QTabWidget#httpRequestTabs QTabBar::tab:hover,
QTabWidget#httpResponseTabs QTabBar::tab:hover,
QTabWidget#httpActualTabs QTabBar::tab:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QTabWidget#httpRequestTabs QTabBar::tab:selected,
QTabWidget#httpResponseTabs QTabBar::tab:selected,
QTabWidget#httpActualTabs QTabBar::tab:selected {{
    color: {COLOR_PRIMARY};
    border-bottom-color: {COLOR_PRIMARY};
    font-weight: 400;
}}
QRadioButton {{
    color: {COLOR_TEXT_SECONDARY};
    spacing: 5px;
    font-size: 13px;
}}
QRadioButton:hover {{
    color: {COLOR_TEXT};
}}
QCheckBox {{
    color: {COLOR_TEXT_SECONDARY};
    spacing: 6px;
    font-size: 13px;
}}
QCheckBox:hover {{
    color: {COLOR_TEXT};
}}
{HTTP_CODE_EDITOR_STYLE}
QSplitter#httpWorkspace::handle {{
    background-color: {COLOR_PAGE_BG};
    height: 8px;
}}
"""


HTTP_ENVIRONMENT_DIALOG_STYLE = f"""
QDialog#httpEnvironmentDialog {{
    background-color: {COLOR_PAGE_BG};
}}
QDialog#httpEnvironmentDialog QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QDialog#httpEnvironmentDialog QLabel#httpDialogTitle {{
    color: {COLOR_TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QDialog#httpEnvironmentDialog QLabel#httpEnvironmentHint {{
    color: {COLOR_TEXT_MUTED};
    font-size: 12px;
}}
QWidget#httpEnvironmentPanel {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QListWidget#httpEnvironmentList {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px;
    outline: 0;
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QListWidget#httpEnvironmentList::item {{
    min-height: 30px;
    padding: 3px 9px;
    margin: 2px;
    border-radius: {RADIUS_SMALL}px;
}}
QListWidget#httpEnvironmentList::item:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QListWidget#httpEnvironmentList::item:selected {{
    background-color: {COLOR_PRIMARY_SOFT};
    color: #0067B8;
}}
QDialog#httpEnvironmentDialog QLineEdit {{
    min-height: 24px;
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QDialog#httpEnvironmentDialog QPushButton {{
    min-height: 28px;
    padding: 3px 12px;
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QDialog#httpEnvironmentDialog QPushButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_PRIMARY_BORDER};
    color: {COLOR_PRIMARY};
}}
QDialog#httpEnvironmentDialog QPushButton#httpEnvironmentPrimary {{
    background-color: {COLOR_PRIMARY};
    border-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    font-weight: 600;
}}
QDialog#httpEnvironmentDialog QPushButton#httpEnvironmentPrimary:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border-color: {COLOR_PRIMARY_HOVER};
    color: #FFFFFF;
}}
"""


PROTOCOL_WORKSPACE_STYLE = f"""
QWidget#mqttPage,
QWidget#websocketPage {{
    background-color: {COLOR_PAGE_BG};
}}
QWidget#protocolCard {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#mqttPage QLabel,
QWidget#websocketPage QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QLabel#protocolSectionTitle {{
    color: {COLOR_TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#protocolHint {{
    color: {COLOR_TEXT_MUTED};
    font-size: 12px;
}}
QWidget#mqttPage QLineEdit,
QWidget#mqttPage QSpinBox,
QWidget#mqttPage QComboBox,
QWidget#websocketPage QLineEdit,
QWidget#websocketPage QSpinBox,
QWidget#websocketPage QComboBox {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px 8px;
    min-height: 22px;
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QWidget#mqttPage QLineEdit:hover,
QWidget#mqttPage QSpinBox:hover,
QWidget#mqttPage QComboBox:hover,
QWidget#websocketPage QLineEdit:hover,
QWidget#websocketPage QSpinBox:hover,
QWidget#websocketPage QComboBox:hover {{
    border-color: {COLOR_PRIMARY_BORDER};
}}
QWidget#mqttPage QLineEdit:focus,
QWidget#mqttPage QSpinBox:focus,
QWidget#mqttPage QComboBox:focus,
QWidget#websocketPage QLineEdit:focus,
QWidget#websocketPage QSpinBox:focus,
QWidget#websocketPage QComboBox:focus {{
    border-color: {COLOR_PRIMARY};
}}
QWidget#mqttPage QPushButton,
QWidget#websocketPage QPushButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px 12px;
    min-height: 22px;
    font-family: "{FONT_UI}";
    font-size: 13px;
    font-weight: 500;
}}
QWidget#mqttPage QPushButton:hover,
QWidget#websocketPage QPushButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_PRIMARY_BORDER};
    color: {COLOR_PRIMARY};
}}
QWidget#mqttPage QPushButton:disabled,
QWidget#websocketPage QPushButton:disabled {{
    background-color: {COLOR_SURFACE_SUBTLE};
    color: {COLOR_TEXT_MUTED};
    border-color: {COLOR_DIVIDER};
}}
QWidget#mqttPage QPushButton[protocolPrimary="true"],
QWidget#websocketPage QPushButton[protocolPrimary="true"] {{
    background-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    border-color: {COLOR_PRIMARY};
    font-weight: 600;
}}
QWidget#mqttPage QPushButton[protocolPrimary="true"]:hover,
QWidget#websocketPage QPushButton[protocolPrimary="true"]:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border-color: {COLOR_PRIMARY_HOVER};
    color: #FFFFFF;
}}
QWidget#websocketPage QPushButton[protocolPrimary="true"][connected="true"] {{
    background-color: {COLOR_DANGER};
    border-color: {COLOR_DANGER};
    color: #FFFFFF;
}}
QWidget#websocketPage QPushButton[protocolPrimary="true"][connected="true"]:hover {{
    background-color: #A4262C;
    border-color: #A4262C;
}}
QWidget#mqttPage QCheckBox,
QWidget#websocketPage QCheckBox {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QWidget#mqttPage QPlainTextEdit,
QWidget#websocketPage QPlainTextEdit {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 8px;
    selection-background-color: #C9E4FA;
    font-family: "{FONT_MONO}";
    font-size: 13px;
}}
QWidget#mqttPage QPlainTextEdit:focus,
QWidget#websocketPage QPlainTextEdit:focus {{
    border-color: {COLOR_PRIMARY};
}}
QGroupBox#protocolGroupCard {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_CARD}px;
    margin-top: 22px;
    padding: 12px 10px 10px 10px;
    font-family: "{FONT_UI}";
    font-size: 13px;
    font-weight: 600;
    color: {COLOR_TEXT};
}}
QGroupBox#protocolGroupCard::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: 4px;
    padding: 4px 6px;
    color: {COLOR_TEXT};
    background-color: {COLOR_SURFACE};
    font-size: 13px;
}}
QSplitter#protocolSplit::handle {{
    background-color: {COLOR_PAGE_BG};
    width: 8px;
}}
"""


PROTOCOL_SETTINGS_STYLE = f"""
QWidget#mqttSettingsPage,
QWidget#websocketSettingsPage {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#mqttSettingsPage QLabel,
QWidget#websocketSettingsPage QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QWidget#mqttSettingsPage QLineEdit,
QWidget#mqttSettingsPage QSpinBox,
QWidget#mqttSettingsPage QComboBox,
QWidget#websocketSettingsPage QLineEdit,
QWidget#websocketSettingsPage QSpinBox {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    min-height: 24px;
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QWidget#mqttSettingsPage QLineEdit:focus,
QWidget#mqttSettingsPage QSpinBox:focus,
QWidget#mqttSettingsPage QComboBox:focus,
QWidget#websocketSettingsPage QLineEdit:focus,
QWidget#websocketSettingsPage QSpinBox:focus {{
    border-color: {COLOR_PRIMARY};
}}
QWidget#mqttSettingsPage QCheckBox,
QWidget#websocketSettingsPage QCheckBox {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
"""


PRESET_PANEL_STYLE = f"""
QWidget#presetPanel {{
    background-color: {COLOR_SURFACE};
    border-left: 1px solid {COLOR_BORDER};
}}
QWidget#presetPanel QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-family: "{FONT_UI}";
    font-size: 13px;
}}
QLabel#presetTitle {{
    color: {COLOR_TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#presetHint {{
    color: {COLOR_TEXT_MUTED};
    font-size: 12px;
}}
QWidget#presetPanel QPushButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SMALL}px;
    padding: 3px 9px;
    min-height: 24px;
    font-family: "{FONT_UI}";
    font-size: 12px;
}}
QWidget#presetPanel QPushButton:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_PRIMARY_BORDER};
    color: {COLOR_PRIMARY};
}}
QWidget#presetPanel QPushButton#presetRowSend {{
    background-color: {COLOR_PRIMARY};
    border-color: {COLOR_PRIMARY};
    color: #FFFFFF;
    padding: 0;
}}
QWidget#presetPanel QPushButton#presetRowSend:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border-color: {COLOR_PRIMARY_HOVER};
}}
QWidget#presetPanel QCheckBox {{
    color: {COLOR_TEXT_SECONDARY};
    spacing: 5px;
}}
"""
