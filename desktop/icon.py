"""程序化生成应用 logo，避免外部图片文件依赖。"""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtGui import QIcon


def make_app_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    margin = size * 0.08
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#3b82f6"))
    grad.setColorAt(1.0, QColor("#1e3a8a"))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(rect, size * 0.18, size * 0.18)

    cx, cy = rect.center().x(), rect.center().y()
    r = rect.width() * 0.28
    tri = QPainterPath()
    tri.moveTo(QPoint(int(cx - r * 0.7), int(cy - r)))
    tri.lineTo(QPoint(int(cx - r * 0.7), int(cy + r)))
    tri.lineTo(QPoint(int(cx + r), int(cy)))
    tri.closeSubpath()
    p.fillPath(tri, QColor("#ffffff"))

    p.end()
    return pm


def make_app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 32, 64, 128, 256):
        icon.addPixmap(make_app_pixmap(s))
    return icon
