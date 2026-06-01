import math
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QPen, QPolygonF, QColor, QMouseEvent, QPainter
from PyQt6.QtWidgets import QComboBox, QGraphicsItemGroup, QGraphicsLineItem, QGraphicsRectItem, QStyleOptionGraphicsItem, QWidget, QGraphicsItem

from .data_classes import LineOperation, UIConstants as UIC




class MultiColorRectItem(QGraphicsRectItem):

    def __init__(self, rect: QRectF, colors: list[QColor], parent: QGraphicsItem | None = None):
        """
        A regular QGraphicsRectItem with the additional feature that it can have several background colors which are horizontally aligned with equal spacing.

        Args:
            rect:   The geometry of the item
            colors: A list of QColors
            parent: an optional parent item
        """
        super().__init__(rect, parent)
        self._colors = colors
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))


    def paint(self, painter: QPainter, options: QStyleOptionGraphicsItem, widget: QWidget | None = None):

        # Get base rect
        rect    = self.rect()
        w, h    = rect.width(), rect.height()
        seg_w   = w / len(self._colors)
        for i, color in enumerate(self._colors):
            x   = rect.left() + i * seg_w
            painter.fillRect(QRectF(x, rect.top(), seg_w, h), color)

        # Draw border
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(rect)



class StripedColorRectItem(QGraphicsRectItem):

    def __init__(self, rect: QRectF, colors: list[QColor], parent: QGraphicsItem | None = None):
        """
        A Rectangle that behaves like a MultiColorRectItem, with an additional diagonal stripe pattern overlayed.

        Args:
            rect:   The geometry of the item
            colors: A list of QColors
            parent: an optional parent Widget
        """
        super().__init__(rect, parent)
        self._colors        = colors
        self._brush_1       = QBrush(QColor(*UIC.junk_strip_color_1))
        self._brush_2       = QBrush(QColor(*UIC.junk_strip_color_2))
        self._diag_len      = math.sqrt(2 * UIC.junk_strip_size * UIC.junk_strip_size)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))


    def paint(self, painter: QPainter, options: QStyleOptionGraphicsItem, widget: QWidget | None = None):

        # Get base rect
        rect    = self.rect()
        w, h    = rect.width(), rect.height()
        painter.setClipRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw Document Type colors
        seg_w   = w / len(self._colors)
        for i, color in enumerate(self._colors):
            x   = rect.left() + i * seg_w
            painter.fillRect(QRectF(x, rect.top(), seg_w, h), color)

        # Draw Stripes
        no_strips = int(math.ceil((w + h) / self._diag_len))
        for i in range(no_strips):
            p1 = rect.topLeft() + QPointF(0, i * self._diag_len)
            p2 = rect.topLeft() + QPointF(i * self._diag_len, 0)
            p3 = rect.topLeft() + QPointF((i + 1) * self._diag_len, 0)
            p4 = rect.topLeft() + QPointF(0, (i + 1) * self._diag_len)
            polygon = QPolygonF([p1, p2, p3, p4])
            if i % 2:
                painter.setBrush(self._brush_1)
            else:
                painter.setBrush(self._brush_2)
            painter.drawPolygon(polygon)

        # Draw border
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(rect)



class ContrastLineItem(QGraphicsItemGroup):

    def __init__(self, p1: QPointF, p2: QPointF, operation: LineOperation = LineOperation.INVALID, parent: QGraphicsItem | None = None):
        """
        A class to provide a line with a larger one behind it with a constrastive background color. Inteded to distinguish the line better over varying background items.

        Args:
            p1:         Coordinates of the point point
            p2:         Coordinates of the second point
            operation:  The type of operation that the line triggers once dropped.
        """
        super().__init__(parent)

        self._operation = operation

        self._p1        = p1
        self._p2        = p2

        self._outer     = QGraphicsLineItem()
        self._inner     = QGraphicsLineItem()

        self._outer_pen = QPen(QColor(*UIC.line_color_glow), UIC.line_outer_width)
        self._outer.setPen(self._outer_pen)
        self.addToGroup(self._outer)


        self._inner_pen = QPen(QColor(*UIC.line_color_invalid), UIC.line_inner_width)
        self._inner.setPen(self._inner_pen)
        self.addToGroup(self._inner)

        self._update_line()


    @property
    def operation(self) -> LineOperation:
        return self._operation


    @operation.setter
    def operation(self, operation: LineOperation):
        self._operation = operation
        self._update_line_colors()


    @property
    def p1(self) -> QPointF:
        return self._p1


    @p1.setter
    def p1(self, p1: QPointF):
        self._p1 = p1
        self._update_line()


    @property
    def p2(self) -> QPointF:
        return self._p2


    @p2.setter
    def p2(self, p2: QPointF):
        self._p2 = p2
        self._update_line()


    def _update_line(self):
        self._line      = QLineF(self._p1, self._p2)

        # Rendering for lines with a length of zero is undefined; Set a minimal length resulting in a square
        if self._line.length() < UIC.epsilon:
            self._line = QLineF(self._p1, self._p2 + QPointF(UIC.epsilon, 0))

        self._outer.setLine(self._line)
        self._inner.setLine(self._line)


    def _update_line_colors(self):
        if self._operation      == LineOperation.INVALID:
            color = UIC.line_color_invalid
        elif self._operation    == LineOperation.CLUSTER:
            color = UIC.line_color_cluster
        elif self._operation    == LineOperation.SPLIT:
            color = UIC.line_color_split
        elif self._operation    == LineOperation.MERGE:
            color = UIC.line_color_merge

        self._inner_pen.setColor(QColor(*color))
        self._inner.setPen(self._inner_pen)



class FoldableComboBox(QComboBox):

    def __init__(self):
        """
        For some reason the popup behavior of regular combo boxes only allows item selection while the mouse button is pressed, and cloeses the popup once the button is released.
        This class changes this behavior and opens the popup once a mouse button was released.
        """
        super().__init__()


    def mousePressEvent(self, e: QMouseEvent):
        e.accept()


    def mouseReleaseEvent(self, e: QMouseEvent):
        super().mousePressEvent(e)
        super().mouseReleaseEvent(e)