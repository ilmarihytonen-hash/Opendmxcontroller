import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
renderer = QSvgRenderer(str(source))
if not renderer.isValid():
    raise RuntimeError(f"Could not render icon SVG: {source}")
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
renderer.render(painter)
painter.end()
if not image.save(str(destination), "PNG"):
    raise RuntimeError(f"Could not save application icon: {destination}")
