"""Design tokens, palette and style sheet. Follows the system light/dark setting."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import icons


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    surface: str
    raised: str
    sidebar: str
    border: str
    hover: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    danger: str
    success: str


# Folio is meant to be easy on the eyes: darker text, firmer borders and no pale grey for
# anything that matters (the other apps still use the lighter house palette).
LIGHT = Theme(
    dark=False,
    bg="#f3f4f7", surface="#ffffff", raised="#eceef3", sidebar="#e6e8ee",
    border="#b9bec9", hover="#dfe2ea",
    text="#0e1116", muted="#3f4654", faint="#5d6573",
    accent="#4b4bc8", accent_hover="#3b3bb0", accent_soft="#d9d9f8", on_accent="#ffffff",
    danger="#c4262c", success="#1f7a4d",
)

DARK = Theme(
    dark=True,
    bg="#0e0f11", surface="#17181b", raised="#212328", sidebar="#131416",
    border="#4a4e57", hover="#2c2f35",
    text="#f4f5f7", muted="#c3c8d2", faint="#98a0ad",
    accent="#9a9bff", accent_hover="#b0b1ff", accent_soft="#33356a", on_accent="#0e0f11",
    danger="#ff7b80", success="#4fe39b",
)

# "High contrast" in Settings: black on white / white on black, thick lines.
HIGH_LIGHT = Theme(
    dark=False,
    bg="#ffffff", surface="#ffffff", raised="#f0f0f0", sidebar="#f0f0f0",
    border="#000000", hover="#dcdcdc",
    text="#000000", muted="#1a1a1a", faint="#333333",
    accent="#1f1fa8", accent_hover="#14147a", accent_soft="#cfcff7", on_accent="#ffffff",
    danger="#a30000", success="#005a2b",
)

HIGH_DARK = Theme(
    dark=True,
    bg="#000000", surface="#000000", raised="#1a1a1a", sidebar="#0a0a0a",
    border="#ffffff", hover="#2e2e2e",
    text="#ffffff", muted="#e6e6e6", faint="#cccccc",
    accent="#ffd400", accent_hover="#ffe55c", accent_soft="#3a3300", on_accent="#000000",
    danger="#ff8a8a", success="#6dffb0",
)

RADIUS = 10


MODES = ("system", "light", "dark")


class ThemeManager(QObject):
    """Owns the active theme; follows the system scheme unless the user picked one."""

    changed = Signal(object)  # Theme

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.theme = LIGHT
        mode = QSettings().value("appearance", "system")
        self.mode = mode if mode in MODES else "system"
        self.contrast = str(QSettings().value("high_contrast", "false")).lower() == "true"
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: self.apply())
        self.apply()

    def set_contrast(self, on: bool):
        self.contrast = on
        QSettings().setValue("high_contrast", "true" if on else "false")
        self.apply()

    def set_mode(self, mode: str):
        self.mode = mode
        QSettings().setValue("appearance", mode)
        self.apply()

    def apply(self):
        if self.mode == "system":
            dark = self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = self.mode == "dark"
        self.theme = (HIGH_DARK if dark else HIGH_LIGHT) if self.contrast else (DARK if dark else LIGHT)
        self.app.setPalette(palette(self.theme))
        self.app.setStyleSheet(stylesheet(self.theme))
        self.changed.emit(self.theme)


_manager: ThemeManager | None = None


def install(app: QApplication) -> ThemeManager:
    global _manager
    _manager = ThemeManager(app)
    return _manager


def manager() -> ThemeManager:
    assert _manager is not None, "theme.install() must run before building widgets"
    return _manager


def current() -> Theme:
    return _manager.theme if _manager else LIGHT


def themed(apply) -> None:
    """Call `apply(theme)` now and again whenever the theme changes."""
    apply(current())
    if _manager is not None:
        def safe(theme):
            try:
                apply(theme)
            except RuntimeError:  # the widget was deleted
                pass
        _manager.changed.connect(safe)


def disabled(t: Theme) -> str:
    """Text and icons of things you can't use yet: clearly paler than muted text."""
    return "#8a909c" if t.dark else "#7a808c"


def set_icon(widget, name: str, role: str = "muted", checked_role: str | None = None,
             size: int = 18) -> None:
    """Give a button a line icon that recolours with the theme."""
    def apply(t: Theme):
        widget.setIcon(icons.icon(name, getattr(t, role),
                                  getattr(t, checked_role) if checked_role else None, size,
                                  disabled(t)))
    themed(apply)


def palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: t.bg, QPalette.WindowText: t.text,
        QPalette.Base: t.surface, QPalette.AlternateBase: t.raised,
        QPalette.Text: t.text, QPalette.PlaceholderText: t.faint,
        QPalette.Button: t.raised, QPalette.ButtonText: t.text,
        QPalette.Highlight: t.accent, QPalette.HighlightedText: t.on_accent,
        QPalette.ToolTipBase: t.raised, QPalette.ToolTipText: t.text,
        QPalette.Link: t.accent, QPalette.Mid: t.border, QPalette.Midlight: t.hover,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(t.faint))
    return p


def stylesheet(t: Theme) -> str:
    check = icons.icon_file("check", t.on_accent, 3)
    chevron = icons.icon_file("chevron-down", t.muted)
    chevron_up = icons.icon_file("chevron-up", t.muted)
    r = RADIUS
    return f"""
    * {{ outline: none; }}
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QToolTip {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border};
               border-radius: 6px; padding: 4px 8px; }}

    /* ---- sidebar ---- */
    #sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
    #brand {{ font-size: 15pt; font-weight: 700; color: {t.text}; }}
    #sidebarSection {{ color: {t.faint}; font-size: 10pt; font-weight: 600;
                       letter-spacing: 1px; padding: 0 12px; }}
    QToolButton#nav {{ background: transparent; border: none; border-radius: 8px;
                       padding: 8px 12px; color: {t.muted}; text-align: left;
                       font-weight: 500; }}
    QToolButton#nav:hover {{ background: {t.hover}; color: {t.text}; }}
    QToolButton#nav:disabled {{ color: {disabled(t)}; background: transparent; }}
    QToolButton#nav:checked {{ background: {t.accent_soft}; color: {t.accent};
                               font-weight: 600; }}

    /* ---- page chrome ---- */
    #page {{ background: {t.bg}; }}
    #pageTitle {{ font-size: 19pt; font-weight: 700; color: {t.text}; }}
    #pageSubtitle {{ color: {t.muted}; }}
    #card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r + 4}px; }}
    #cardTitle {{ font-weight: 700; color: {t.text}; font-size: 10.5pt; }}
    #muted {{ color: {t.muted}; }}
    #hint {{ color: {t.faint}; }}
    QLabel#danger {{ color: {t.danger}; }}
    #stat {{ font-size: 22pt; font-weight: 700; color: {t.text}; }}
    #sheetTitle {{ font-size: 16pt; font-weight: 700; color: {t.text}; }}
    QTextBrowser#sheetBody {{ background: {t.raised}; border: none; border-radius: 10px;
        padding: 10px 12px; }}
    QLabel#chip, QLabel#chipDanger {{ background: {t.raised}; color: {t.text};
        border-radius: 10px; padding: 3px 10px; font-size: 10pt; font-weight: 600; }}
    QLabel#chipDanger {{ background: {t.accent_soft}; color: {t.danger}; }}
    QLineEdit#titleEdit {{ font-size: 14pt; font-weight: 600; padding: 8px 10px; }}
    #tileCaption {{ color: {t.muted}; font-size: 10pt; font-weight: 600;
        letter-spacing: 0.5px; }}
    #tileValue {{ font-size: 20pt; font-weight: 700; color: {t.text}; }}
    #segmented {{ background: {t.raised}; border: 1px solid {t.border}; border-radius: 9px; }}
    QPushButton#segment {{ background: transparent; border: none; border-radius: 7px;
        padding: 5px 12px; color: {t.muted}; font-weight: 500; }}
    QPushButton#segment:hover {{ color: {t.text}; }}
    QPushButton#segment:checked {{ background: {t.surface}; color: {t.text};
        font-weight: 600; border: 1px solid {t.border}; }}
    #badge {{ background: {t.accent_soft}; color: {t.accent}; border-radius: 9px;
              padding: 1px 8px; font-weight: 600; font-size: 10pt; }}

    /* ---- buttons ---- */
    QPushButton, QToolButton {{ background: {t.raised}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 8px; padding: 6px 14px; }}
    QPushButton:hover, QToolButton:hover {{ background: {t.hover}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t.faint}; background: transparent; }}
    QPushButton:checked, QToolButton:checked {{ background: {t.accent_soft}; color: {t.accent};
        border-color: {t.accent_soft}; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.on_accent}; border: none;
        font-weight: 600; padding: 7px 16px; }}
    QPushButton#primary:hover {{ background: {t.accent_hover}; }}
    QPushButton#danger {{ color: {t.danger}; }}
    QToolButton#icon, QPushButton#icon {{ background: transparent; border: none;
        border-radius: 8px; padding: 6px; }}
    QToolButton#icon:hover, QPushButton#icon:hover {{ background: {t.hover}; }}
    QToolButton#icon:checked, QPushButton#icon:checked {{ background: {t.accent_soft}; }}
    QToolButton::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#day {{ min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
        padding: 0; border-radius: 13px; border: 1px solid {t.border}; background: {t.surface};
        color: {t.muted}; font-weight: 600; font-size: 10pt; }}
    QToolButton#day:hover {{ border-color: {t.accent}; }}
    QToolButton#day:checked {{ background: {t.accent}; border-color: {t.accent};
        color: {t.on_accent}; }}

    /* ---- the drawing page ---- */
    QToolButton#tool {{ background: transparent; border: none; border-radius: 8px;
        padding: 5px 10px; color: {t.muted}; font-weight: 500; }}
    QToolButton#tool:hover {{ background: {t.hover}; color: {t.text}; }}
    QToolButton#tool:checked {{ background: {t.accent_soft}; color: {t.accent};
        font-weight: 600; }}
    QToolButton#tool[popupMode="1"] {{ padding-right: 22px; }}
    QToolButton#tool::menu-button {{ border: none; width: 18px; }}
    QToolButton#tool::menu-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
    #rule {{ background: {t.border}; }}
    QGraphicsView {{ border: none; border-bottom-left-radius: {r + 4}px;
        border-bottom-right-radius: {r + 4}px; }}
    QPlainTextEdit#code, QTextBrowser#code {{ background: {t.raised}; border: none;
        border-radius: 10px; padding: 10px 12px; }}
    QListWidget#recent::item {{ padding: 9px 10px; }}
    QToolButton#startTile {{ background: {t.raised}; border: 1px solid {t.border};
        border-radius: 12px; padding: 14px; color: {t.text}; font-weight: 600; }}
    QToolButton#startTile:hover {{ border-color: {t.accent}; background: {t.accent_soft}; }}

    QTextBrowser#paper {{ background: #ffffff; color: #16181d; border: none;
        border-radius: 10px; padding: 12px 16px; }}
    QTreeWidget#compact::item {{ padding: 2px 6px; }}
    QTableView::item:selected, QTableWidget::item:selected {{ background: {t.accent_soft};
        color: {t.text}; }}
    QTableView::item:focus {{ border: 2px solid {t.accent}; }}
    QTableView::item {{ padding: 2px 8px; }}
    QTableView {{ background: {t.surface}; alternate-background-color: {t.raised};
        border: 1px solid {t.border}; border-radius: 8px; gridline-color: {t.border};
        color: {t.text}; }}
    QTableCornerButton::section {{ background: {t.raised}; border: none; }}

    /* ---- inputs ---- */
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox {{
        background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 8px; padding: 6px 10px; selection-background-color: {t.accent};
        selection-color: {t.on_accent}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
    QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus {{
        border: 1px solid {t.accent}; }}
    QLineEdit#search {{ background: {t.raised}; border-color: transparent; }}
    QLineEdit#search:focus {{ background: {t.surface}; border-color: {t.accent}; }}
    QPlainTextEdit#bare, QTextBrowser#bare {{ border: none; background: transparent;
        padding: 4px 2px; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({chevron}); width: 14px;
        height: 14px; }}
    QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: none; }}
    QSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 22px;
        border: none; background: transparent; }}
    QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t.hover};
        border-radius: 4px; }}
    QSpinBox::up-arrow {{ image: url({chevron_up}); width: 11px; height: 11px; }}
    QSpinBox::down-arrow {{ image: url({chevron}); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: 8px; padding: 4px; selection-background-color: {t.accent_soft};
        selection-color: {t.text}; }}

    QCheckBox {{ spacing: 8px; color: {t.text}; }}
    QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator {{
        width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid {t.faint};
        background: {t.surface}; }}
    QCheckBox::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {{
        border-color: {t.accent}; }}
    QCheckBox::indicator:checked, QListWidget::indicator:checked,
    QTreeWidget::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
        image: url({check}); }}

    /* ---- lists ---- */
    QListWidget, QTreeWidget, QTableWidget {{ background: transparent; border: none;
        color: {t.text}; }}
    QListWidget::item, QTreeWidget::item {{ padding: 7px 8px; border-radius: 8px;
        margin: 1px 0; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t.hover}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {t.accent_soft};
        color: {t.text}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QHeaderView::section {{ background: {t.raised}; color: {t.text}; border: none;
        border-bottom: 2px solid {t.border}; border-right: 1px solid {t.border};
        padding: 8px 10px; font-weight: 700; font-size: 10.5pt; }}
    QTableWidget {{ gridline-color: {t.border}; }}

    /* ---- scrollbars ---- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {t.border}; border-radius: 3px; min-height: 30px;
        min-width: 30px; }}
    QScrollBar::handle:hover {{ background: {t.faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* ---- menus, splitters ---- */
    QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 6px;
        border-radius: 10px; }}
    QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; color: {t.text}; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}
    QSplitter::handle {{ background: transparent; }}
    QCalendarWidget QWidget {{ alternate-background-color: {t.raised}; }}
    QCalendarWidget QToolButton {{ border: none; background: transparent; }}
    """
