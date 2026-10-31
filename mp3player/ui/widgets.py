"""自作ウィジェット(省略表示ラベル / シークバー / 音量行 / レベルメーター / アイコン)。"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFontMetrics, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QSlider, QStyle, QWidget,
)

from . import theme


def set_state(widget: QWidget, state: str) -> None:
    """QSSの [state="..."] を切り替えて再描画する。"""
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """幅に収まらない文字を「…」で省略して表示するラベル。"""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt流儀)
        self._full = text
        self.setToolTip(text)
        self._apply()

    def text(self) -> str:  # noqa: D401
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideRight,
                               max(self.width(), 10))
        )


class SeekSlider(QSlider):
    """クリックした位置へジャンプできるシークバー。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 0)
        self.setEnabled(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), max(1, self.width()),
            )
            self.setValue(value)
            self.sliderMoved.emit(value)
        super().mousePressEvent(event)


class VolumeRow(QWidget):
    """「ラベル + スライダー + %表示」の1行。値は0〜150(%)。"""

    changed = Signal(float)

    def __init__(self, label: str, value: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._name = QLabel(label)
        self._name.setFixedWidth(84)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 150)
        self.slider.setValue(int(round(value)))
        self._value = QLabel()
        self._value.setObjectName("muted")
        self._value.setFixedWidth(44)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._name)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self._value)
        self.slider.valueChanged.connect(self._on_changed)
        self._on_changed(self.slider.value())

    def _on_changed(self, value: int) -> None:
        self._value.setText(f"{value}%")
        self.changed.emit(float(value))


class LevelMeter(QWidget):
    """音量メーター(-60dB〜0dB)。ピークの位置に細い目印が残り、ゆっくり下がる。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._level = 0.0
        self._hold = 0.0

    @staticmethod
    def _to_unit(peak: float) -> float:
        if peak <= 1e-4:
            return 0.0
        db = 20.0 * math.log10(peak)
        return min(1.0, max(0.0, (db + 60.0) / 60.0))

    def set_peak(self, peak: float) -> None:
        value = self._to_unit(peak)
        self._level = max(value, self._level - 0.05)
        self._hold = max(value, self._hold - 0.012)
        self.update()

    def reset(self) -> None:
        self._level = 0.0
        self._hold = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        track = QPainterPath()
        track.addRoundedRect(rect, 3, 3)
        painter.fillPath(track, QColor(theme.RAISED))

        if self._level > 0.0:
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
            gradient.setColorAt(0.0, QColor(theme.OK))
            gradient.setColorAt(0.70, QColor(theme.OK))   # -18dB
            gradient.setColorAt(0.88, QColor(theme.WARN)) # -7dB
            gradient.setColorAt(1.0, QColor(theme.BAD))
            painter.save()
            painter.setClipPath(track)
            painter.fillRect(
                QRectF(rect.left(), rect.top(), rect.width() * self._level, rect.height()),
                QBrush(gradient),
            )
            painter.restore()
        if self._hold > 0.02:
            x = rect.left() + rect.width() * self._hold
            painter.setPen(QPen(QColor(theme.TEXT), 2))
            painter.drawLine(QPointF(x, rect.top() + 1), QPointF(x, rect.bottom() - 1))


# ---- アイコン(コードで描くので画像ファイルは不要) ----------------------
def make_icon(kind: str, color: str = theme.TEXT, size: int = 96) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    s = float(size)

    def poly(points: list[tuple[float, float]]) -> None:
        path = QPainterPath()
        path.moveTo(points[0][0] * s, points[0][1] * s)
        for x, y in points[1:]:
            path.lineTo(x * s, y * s)
        path.closeSubpath()
        painter.drawPath(path)

    def rect(x: float, y: float, w: float, h: float) -> None:
        painter.drawRoundedRect(QRectF(x * s, y * s, w * s, h * s), s * 0.04, s * 0.04)

    if kind == "play":
        poly([(0.32, 0.20), (0.32, 0.80), (0.82, 0.50)])
    elif kind == "pause":
        rect(0.26, 0.20, 0.17, 0.60)
        rect(0.57, 0.20, 0.17, 0.60)
    elif kind == "stop":
        rect(0.24, 0.24, 0.52, 0.52)
    elif kind == "prev":
        rect(0.20, 0.22, 0.10, 0.56)
        poly([(0.82, 0.22), (0.82, 0.78), (0.36, 0.50)])
    elif kind == "next":
        rect(0.70, 0.22, 0.10, 0.56)
        poly([(0.18, 0.22), (0.18, 0.78), (0.64, 0.50)])
    painter.end()
    return QIcon(pixmap)


def make_app_icon() -> QIcon:
    """アプリのアイコン(波形バー)。"""
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    background = QPainterPath()
    background.addRoundedRect(QRectF(8, 8, size - 16, size - 16), 52, 52)
    painter.fillPath(background, QColor(theme.PANEL))
    painter.setPen(QPen(QColor(theme.LINE), 4))
    painter.drawPath(background)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.ACCENT))
    heights = (0.30, 0.52, 0.72, 0.46, 0.60, 0.34)
    bar, gap = 20.0, 12.0
    total = len(heights) * bar + (len(heights) - 1) * gap
    x = (size - total) / 2
    for h in heights:
        height = size * h
        painter.drawRoundedRect(QRectF(x, (size - height) / 2, bar, height), 10, 10)
        x += bar + gap
    painter.end()
    return QIcon(pixmap)
