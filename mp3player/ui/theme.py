"""見た目(ダークテーマ)の定義。

配色は「ミキサー卓」をイメージ: 青みのある黒を土台に、再生・操作の要所だけ
琥珀色(アンバー)を使う。メーターの緑→琥珀→赤は意味のある色なので固定。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#13161c"
PANEL = "#1b2029"
RAISED = "#252c38"
HOVER = "#2e3646"
LINE = "#2e3645"
TEXT = "#e8ecf3"
MUTED = "#8b95a7"
ACCENT = "#f0b441"
ACCENT_HOVER = "#f6c561"
ON_ACCENT = "#1a1406"
OK = "#5fd38d"
WARN = "#f0b441"
BAD = "#ef6b6b"

FONT_FAMILY = '"Yu Gothic UI", "Segoe UI", "Meiryo UI", sans-serif'

_QSS = """
* { font-family: @FONT@; font-size: 13px; }
QMainWindow, QDialog, QWidget#root { background: @BG@; }
QWidget { color: @TEXT@; }
QLabel { background: transparent; }
QToolTip { background: @RAISED@; color: @TEXT@; border: 1px solid @LINE@; padding: 4px 6px; }

QFrame#panel { background: @PANEL@; border: 1px solid @LINE@; border-radius: 10px; }
QLabel#appTitle { font-size: 17px; font-weight: 700; }
QLabel#heading { font-size: 14px; font-weight: 700; }
QLabel#muted { color: @MUTED@; }
QLabel#trackTitle { font-size: 18px; font-weight: 700; }
QLabel#time { font-family: Consolas, "Cascadia Mono", monospace; color: @MUTED@; }

QLabel#chip { padding: 3px 10px; border-radius: 11px; background: @RAISED@; color: @MUTED@; }
QLabel#chip[state="ok"] { color: @OK@; }
QLabel#chip[state="warn"] { color: @WARN@; }
QLabel#chip[state="bad"] { color: @BAD@; }
QLabel#note { color: @MUTED@; }
QLabel#note[state="warn"] { color: @WARN@; }
QLabel#note[state="bad"] { color: @BAD@; }

QPushButton, QToolButton {
    background: @RAISED@; border: 1px solid @LINE@; border-radius: 7px; padding: 6px 12px;
}
QPushButton:hover, QToolButton:hover { background: @HOVER@; }
QPushButton:pressed, QToolButton:pressed { background: @LINE@; }
QPushButton:disabled { color: @MUTED@; }
QPushButton:checked { background: @ACCENT@; color: @ON_ACCENT@; border-color: @ACCENT@; }
QPushButton#transport { padding: 8px; border-radius: 8px; min-width: 22px; }
QPushButton#play { background: @ACCENT@; border-color: @ACCENT@; border-radius: 24px; padding: 0px; }
QPushButton#play:hover { background: @ACCENT_HOVER@; }
QPushButton#accent { background: @ACCENT@; color: @ON_ACCENT@; border-color: @ACCENT@; font-weight: 700; }
QPushButton#accent:hover { background: @ACCENT_HOVER@; }

QLineEdit, QSpinBox, QComboBox {
    background: @BG@; border: 1px solid @LINE@; border-radius: 7px; padding: 6px 8px;
    selection-background-color: @ACCENT@; selection-color: @ON_ACCENT@;
}
QLineEdit:focus, QComboBox:focus { border-color: @ACCENT@; }
QComboBox QAbstractItemView { background: @PANEL@; border: 1px solid @LINE@; selection-background-color: @HOVER@; selection-color: @TEXT@; outline: 0; }

QListWidget { background: @BG@; border: 1px solid @LINE@; border-radius: 8px; padding: 4px; outline: 0; }
QListWidget::item { padding: 7px 8px; border-radius: 6px; }
QListWidget::item:hover { background: @RAISED@; }
QListWidget::item:selected { background: @HOVER@; color: @TEXT@; }

QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid @MUTED@; background: @BG@; }
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; @CHECK_IMAGE@ }

QSlider::groove:horizontal { height: 4px; background: @RAISED@; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @ACCENT@; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: @TEXT@; }
QSlider::handle:horizontal:hover { background: @ACCENT_HOVER@; }
QSlider::add-page:horizontal { background: @RAISED@; border-radius: 2px; }
QSlider::sub-page:horizontal:disabled { background: @LINE@; }
QSlider::handle:horizontal:disabled { background: @MUTED@; }

QTabWidget::pane { border: 1px solid @LINE@; border-radius: 8px; top: -1px; background: @PANEL@; }
QTabBar::tab { background: transparent; color: @MUTED@; padding: 8px 14px; border: none; margin-right: 2px; }
QTabBar::tab:selected { color: @TEXT@; border-bottom: 2px solid @ACCENT@; }
QTabBar::tab:hover { color: @TEXT@; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @LINE@; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: @MUTED@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QStatusBar { background: @BG@; color: @MUTED@; }
QStatusBar::item { border: none; }
QMenu { background: @PANEL@; border: 1px solid @LINE@; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: @HOVER@; }
QMessageBox { background: @PANEL@; }
"""


def _make_check_image() -> str:
    """チェックマークのPNGを作り、QSSの image: url(...) 用の記述を返す。失敗時は空。"""
    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QPainter, QPen, QPixmap

        from ..config import APPDATA_DIR

        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(ON_ACCENT), 3.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(24, 10)])
        painter.end()
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        path = APPDATA_DIR / "check.png"
        if not pixmap.save(str(path), "PNG"):
            return ""
        return f'image: url("{path.as_posix()}");'
    except Exception:  # noqa: BLE001
        return ""


def build_stylesheet() -> str:
    tokens = {
        "CHECK_IMAGE": _make_check_image(),
        "FONT": FONT_FAMILY, "BG": BG, "PANEL": PANEL, "RAISED": RAISED,
        "HOVER": HOVER, "LINE": LINE, "TEXT": TEXT, "MUTED": MUTED,
        "ACCENT": ACCENT, "ACCENT_HOVER": ACCENT_HOVER, "ON_ACCENT": ON_ACCENT,
        "OK": OK, "WARN": WARN, "BAD": BAD,
    }
    qss = _QSS
    for key, value in tokens.items():
        qss = qss.replace(f"@{key}@", value)
    return qss


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG,
        QPalette.ColorRole.AlternateBase: PANEL,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: RAISED,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.ToolTipBase: RAISED,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: ON_ACCENT,
        QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(MUTED))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet())
