import abc
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTransform
from PyQt6.QtWidgets import QGraphicsView, QGraphicsRectItem

from .data_classes import RectData, UIConstants as UIC



class AbstractPageArrangement(abc.ABC):

    def __init__(self, view: QGraphicsView, transform: QTransform | None = None):
        """
        Abstract base class for page arrangements that holds a view and associated transformation attributes in order to keep states when switching between arrangements

        Args:
            view:       The view to manage
            transform:  A default scene transformation, i.e. to provide a default zoom level
        """
        if not transform:
            transform = QTransform()

        self._view      = view
        self._transform = transform
        self._h_scroll  = 0
        self._v_scroll  = 0


    @abc.abstractmethod
    def apply(self, pages: list[QGraphicsRectItem]):
        """
        Sets the positions of the QGraphicsRectItem according to an arrangement schema.

        Args:
            pages: A list of rectangles to arrange
        """
        raise NotImplementedError


    @abc.abstractmethod
    def allow_horizontal_scrolling(self) -> bool:
        """
        Indicates if the arrangement allows horizontal zooming

        Returns:
            A bool
        """
        raise NotImplementedError


    @abc.abstractmethod
    def allow_vertical_scrolling(self) -> bool:
        """
        Indicates if the arrangement allows vertical zooming

        Returns:
            A bool
        """
        raise NotImplementedError


    def load_view_state(self):
        """
        Restores a scene's transformation as well as scrolling positions
        """
        self._view.setTransform(self._transform)
        self._view.horizontalScrollBar().setValue(self._h_scroll)
        self._view.verticalScrollBar().setValue(self._v_scroll)

        h_scoll_policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if self.allow_horizontal_scrolling() else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self._view.setHorizontalScrollBarPolicy(h_scoll_policy)
        v_scoll_policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if self.allow_vertical_scrolling() else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self._view.setVerticalScrollBarPolicy(v_scoll_policy)

        self.apply(self._view.page_items)
        self._view.setSceneRect(self._view.scene().itemsBoundingRect())


    def save_view_state(self):
        """
        Stores a scene's transformation as well as current scrolling positions
        """
        self._transform = self._view.transform()
        self._h_scroll  = self._view.horizontalScrollBar().value()
        self._v_scroll  = self._view.verticalScrollBar().value()



class PagewiseArrangement(AbstractPageArrangement):

    def __init__(self, view: QGraphicsView):
        """
        Creates a grid to display all pages aligned to columns and rows.

        Args:
            view: The QGraphicsView holding the items
        """
        default_transform   = QTransform().scale(UIC.page_arrangement_scale, UIC.page_arrangement_scale)
        super().__init__(view, default_transform)


    def apply(self, pages: list[QGraphicsRectItem]):
        bounding_rect   = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
        no_columns      = max(1, bounding_rect.width() // (UIC.page_rect_width + UIC.gap_between_pages))
        no_rows         = int(np.ceil(len(pages) / no_columns))
        x_pos           = np.arange(no_columns) * (UIC.page_rect_width + UIC.gap_between_pages)
        y_pos           = np.arange(no_rows) * (UIC.page_rect_height + UIC.gap_between_pages)
        X_pos, Y_pos    = np.meshgrid(x_pos, y_pos)
        X_pos           = X_pos.flatten()
        Y_pos           = Y_pos.flatten()

        for (x, y, page) in zip(X_pos, Y_pos, pages):
            page.setPos(x, y)


    def allow_horizontal_scrolling(self) -> bool:
        return False


    def allow_vertical_scrolling(self) -> bool:
        return True



class DocumentwiseArrangement(AbstractPageArrangement):

    def __init__(self, view: QGraphicsView):
        """
        Arranges the pages on the canvas so that pagges assigned to the same document are clustered spatially.

        Args:
            view: The QGraphicsView holding the items
        """
        default_transform   = QTransform().scale(UIC.doc_arrangement_scale, UIC.doc_arrangement_scale)
        super().__init__(view, default_transform)


    def apply(self, pages: list[QGraphicsRectItem]):
        max_x       = int(self._view.mapToScene(self._view.viewport().rect()).boundingRect().width()) - UIC.doc_arrangement_gap
        max_x       = max(UIC.page_rect_width, max_x)

        x_offset    = 0
        y_offset    = 0
        prev_doc_id = None
        for rect in pages:
            doc_id  = rect.data(RectData.DOC_ID)

            # Case 1: First Document
            if prev_doc_id is None:
                rect.setPos(x_offset, y_offset)

            # Case 2: Same Document
            elif prev_doc_id == doc_id:
                if (x_offset := x_offset + UIC.gap_between_pages + UIC.page_rect_width) > max_x:
                    x_offset = 0
                    y_offset += UIC.page_rect_height + UIC.gap_between_documents
                rect.setPos(x_offset, y_offset)

            # Case 3: New Document
            else:
                if (x_offset := x_offset + UIC.gap_between_documents + UIC.page_rect_width) > max_x:
                    x_offset = UIC.gap_between_documents
                    y_offset += UIC.page_rect_height + UIC.gap_between_documents
                rect.setPos(x_offset, y_offset)

            prev_doc_id = doc_id


    def allow_horizontal_scrolling(self) -> bool:
        return False


    def allow_vertical_scrolling(self) -> bool:
        return True



class LabelingArrangement(AbstractPageArrangement):

    def __init__(self, view: QGraphicsView):
        """
        Used to arrange pages within a single row, so that pages cover a large portion of the screen.
        Pages assigned to the same document are clustered spatially.

        Args:
            view: The QGraphicsView holding the items
        """
        default_transform   = QTransform().scale(UIC.lab_arrangement_scale, UIC.lab_arrangement_scale)
        super().__init__(view, default_transform)


    def apply(self, pages: list[QGraphicsRectItem]):
        x_offset    = 0
        prev_doc_id = None
        for rect in pages:
            doc_id  = rect.data(RectData.DOC_ID)
            if doc_id != prev_doc_id:
                prev_doc_id = doc_id
                x_offset += UIC.gap_between_documents
            rect.setPos(x_offset, 0)
            x_offset += UIC.page_rect_width + UIC.gap_between_pages


    def allow_horizontal_scrolling(self) -> bool:
        return True


    def allow_vertical_scrolling(self) -> bool:
        return False