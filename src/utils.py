import hashlib
import math
import os
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QApplication, QComboBox
from PyQt6.QtSvg import QSvgRenderer
import subprocess
import sys
import shutil
from typing import Any
from src.ui.data_classes import UIConstants as UIC



def color_from_class(text: str, saturation: int = 200, light: int = 60, alpha: int = 200) -> QColor:
    """
    Genereates a deterministic hue for give string. While the saturation and light factors for a HSL color remain fixed, the hue is generated.
    This could be useful for visually distint prediction labels in a UI. Returns grey if the text is None

    Args:
        text:       A string
        saturation: A fixed stauration in 0-255
        light:      A fixed light value in 0-255
        alpha:      A fixed alpha to support transparence in 0-255

    Returns:
        The QColor
    """

    if text is None:
        return QColor(100, 100, 100, alpha)

    # 1. Create a hash of the class name
    h = int(hashlib.sha256(text.encode()).hexdigest(), 16)

    # 2. Map hash to hue (0–359)
    hue = h % 360

    # 3. Use fixed saturation and lightness for consistency
    return QColor.fromHsl(hue, saturation, light, alpha)



def ls_rec(root_dir: str, filter: str | None = None) -> list[str]:
    """
    Recursively lists all files within a given directory, optionally filtered by extension type.

    Args:
        root_dir:   the directory to filter
        filter:     only return files with this extension (optional)

    Returns:
        a (filtered) list of files found
    """
    paths = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filter is not None and not filename.endswith(filter):
                continue
            paths.append(os.path.join(dirpath, filename))
    return list(sorted(paths))



def open_file(path: str, page: int | None = None):
    """
    A method to open a file with the default viewer that should work across multiple operating systems.
    As a special case, evince and okular are used for Linux based systems to open PDF files at a specific page index.

    Args:
        path:   The path of the file to open
        page:   The page to load from the file, only applicable to PDF files
    """

    if page is None:
        page = 0

    path = os.path.abspath(path)

    if not os.path.exists(path):
        raise FileNotFoundError("File not found: {}".format(path))

    try:
        # Windows
        if sys.platform.startswith('win'):
            os.startfile(path)  # available since Python 3.2

        # MacOS
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])

        # Linux
        elif sys.platform.startswith('linux') or sys.platform.startswith('freebsd'):
            if path.endswith('.pdf'):
                pdf_viewers = [viewer for viewer in ['okular', 'evince'] if shutil.which(viewer)]
                if pdf_viewers:
                    subprocess.Popen([pdf_viewers[0], path, '-p', str(page + 1)])
                else:
                    subprocess.Popen(['xdg-open', path])
            else:
                subprocess.Popen(['xdg-open', path])

        else:
            raise OSError("Unsupported platform: {}".format(sys.platform))

    except subprocess.CalledProcessError as e:
        raise RuntimeError("Failed to open file: {}".format(e))



def euclidean_distance(p1: QPointF, p2: QPointF) -> float:
    """
    Calculate the euclidean distance between two given points.

    Args:
        p1: The first point
        p2: The second point

    Returns:
        The euclidean distance
    """
    dx = p1.x() - p2.x()
    dy = p1.y() - p2.y()
    return math.sqrt(dx * dx + dy * dy)



def load_svg_as_pixmap(path: str, size: int, color: tuple) -> QPixmap:
    """
    Loads a vector graphic and renders them with a given color and size

    Args:
        path:   The path to the vector graphic
        size:   The width and height of the rendered pixmap
        color:  A RGBA tuple for the new primary color

    Returns:
        The rendered QPixmap
    """
    renderer = QSvgRenderer(path)

    # Rasterize SVG to an alpha-masked pixmap
    alpha_mask = QPixmap(size, size)
    alpha_mask.fill(Qt.GlobalColor.transparent)
    renderer.render(QPainter(alpha_mask))

    # Apply color tint while preserving alpha
    result = QPixmap(size, size)
    result.fill(QColor(*color))
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, alpha_mask)
    painter.end()
    return result



def load_icon(path: str) -> QIcon:
    """
    Loads an SVG icon, applies rescaling and re-coloring for active and disabled states according to a theme-specific color.

    Args:
        path: The path to a vector graphic file (svg)

    Returns:
        The loaded QIcon
    """
    size        = UIC.icon_size
    palette     = QApplication.palette()
    renderer    = QSvgRenderer(path)
    temp_pixmap = QPixmap(size, size)
    temp_pixmap.fill(Qt.GlobalColor.transparent)
    renderer.render(QPainter(temp_pixmap))

    icon        = QIcon()

    def _render_pixmap(color):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.fill(color)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, temp_pixmap)
        painter.end()
        return pixmap

    active_pixmap   = _render_pixmap(palette.color(QPalette.ColorRole.WindowText))
    icon.addPixmap(active_pixmap)

    disabled_pixmap = _render_pixmap(palette.color(QPalette.ColorRole.PlaceholderText))
    icon.addPixmap(disabled_pixmap, QIcon.Mode.Disabled)

    return icon



def sorted_insert(box: QComboBox, text: str, data: Any) -> int:
    """
    Inserts a new item into a QComboBox so that the order remains alphabetically.

    Args:
        box:    The QComboBox to insert into
        text:   The text of the item
        data:   The data of the item

    Returns:
        The index of the inserted item
    """
    # Insert alphabetically
    insert_index = box.count()
    for i in range(insert_index):
        if text.lower() < box.itemText(i).lower():
            insert_index = i
            break
    box.insertItem(insert_index, text, data)
    return insert_index