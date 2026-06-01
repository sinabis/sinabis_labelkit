from .custom_items import ContrastLineItem, MultiColorRectItem, StripedColorRectItem, FoldableComboBox
from .data_loading import FileLoader
from .data_classes import ArrangementType, CacheKey, ClusterMagnetLink, LineOperation, MagnetLink, MergeMagnetLink, PageKey, RectData, SplitMagnetLink, UIConstants as UIC
from .dialogs import ActionConflictDialog, CreateCaseDialog, CreateDoctypeDialog, ExportDialog, ImportDialog, MissingFilesDialog, ResolveCasePathDialog
from .page_arrangement import AbstractPageArrangement, DocumentwiseArrangement, LabelingArrangement, PagewiseArrangement
from .. import utils, connectors, caching, actions

from collections import Counter, defaultdict
import datetime as dt
import os

from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDockWidget, QGraphicsEllipseItem, QGraphicsItem, QGraphicsOpacityEffect, QToolButton, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QVBoxLayout, QHBoxLayout, QLabel, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QToolBar, QWidget
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QLineF, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QThreadPool, QTimer
from PyQt6.QtGui import QBrush, QAction, QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QResizeEvent, QWheelEvent


ARRANGEMENT_CLASS_ASSIGNMENTS = {
    ArrangementType.PAGE:       PagewiseArrangement,
    ArrangementType.DOCUMENT:   DocumentwiseArrangement,
    ArrangementType.LABELING:   LabelingArrangement
}



class InitializationException(Exception):
    pass



def _create_page_item(
        document:         dict,
        page_geometry:    QRectF,
        pixmap:           QPixmap,
    ) -> QGraphicsRectItem:
    """
    A method to create a QGraphicsRectItem with a child widget QGraphicsPixmapItem, whoch is assigned a pixmap (can be empty).
    Note that QGraphicsRectItem position is still at the origin and QGraphicsPixmapItem pixmap is still empty.

    Args:
        document:       A dict containing the required data fields
        page_geometry:  A QRectF as default page geometry
        pixmap:         A default pixmap overlayed over the rectangle as child
    """
    colors = [utils.color_from_class(d) for d in (document['doctypes'] if document['doctypes'] else [None])]
    if document['junk']:
        rect    = StripedColorRectItem(page_geometry, colors)
    elif len(colors) > 1:
        rect    = MultiColorRectItem(page_geometry, colors)
    else:
        rect    = QGraphicsRectItem(page_geometry)
        rect.setBrush(QBrush(colors[0]))

    rect.setPen(QPen(Qt.PenStyle.NoPen))

    # Add a QPixmap which is replaced once page is loaded
    pixmap_item = QGraphicsPixmapItem(pixmap, rect)
    pixmap_item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    # Page animations
    opacity_effect = QGraphicsOpacityEffect()
    pixmap_item.setGraphicsEffect(opacity_effect)
    fade_in_anim = QPropertyAnimation(opacity_effect, b"opacity")
    fade_in_anim.setDuration(UIC.fade_in_duration)
    fade_in_anim.setStartValue(0.0)
    fade_in_anim.setEndValue(1.0)
    pixmap_item.fade_in = fade_in_anim

    fade_out_anim = QPropertyAnimation(opacity_effect, b"opacity")
    fade_out_anim.setDuration(UIC.fade_out_duration)
    fade_out_anim.setStartValue(1.0)
    fade_out_anim.setEndValue(0.0)
    pixmap_item.fade_out = fade_out_anim

    rect.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    return rect



class PageCanvas(QGraphicsView):

    # Custom Signals
    store_operation     = pyqtSignal(actions.Action)
    selection_changed   = pyqtSignal(int)
    prev_sel_available  = pyqtSignal(bool)
    next_sel_available  = pyqtSignal(bool)


    def __init__(
            self,
            document_store: connectors.DocumentStore,
            parent:         QWidget | None           = None
        ):
        """
        A widget to hold pages and their pixmap content with different page arrangement options.

        Args:
            document_store: A document store to provide document access
            parent:         The parent QWidget
        """
        super().__init__(parent)

        self._document_store    = document_store

        # General Rendering Settings
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

        # Create Scene
        scene = QGraphicsScene()
        scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(scene)

        # Configure scroll/zoom behavior and user interaction state variables
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.verticalScrollBar().sliderReleased.connect(self._ensure_visible_pages_loaded)
        self.horizontalScrollBar().sliderReleased.connect(self._ensure_visible_pages_loaded)
        self._translation_start     = None

        # Configure line drawing operation variables (only one re-used line instance, a set of magnet target circles)
        self._available_magnets     = []
        self._closest_magnet        = None
        self._magnet_target_items   = set()
        self._line                  = None
        self._draw_mode_delay_timer = QTimer()
        self._draw_mode_delay_timer.setSingleShot(True)

        # Filtering state variables
        self._case_filter           = set([UIC.default_case_filter]) if UIC.default_case_filter else set()
        self._doctype_filter        = set([UIC.default_doctype_filter]) if UIC.default_doctype_filter else set()
        self._junk_filter           = UIC.default_junk_filter

        # Only initialize default (empty) pixmap and rectangle dimensions once and share them
        self._empty_pixmap          = QPixmap()
        self._initial_rect          = QRectF(0, 0, UIC.page_rect_width, UIC.page_rect_height)

        # Handles for fast page-wise scene element access
        self._worker_jobs           = {}
        self._last_update_time      = None
        self._doc_id_to_doc         = {}
        self._doc_id_to_rects       = defaultdict(list)
        self._page_id_to_index      = {}
        self._page_id_to_rect       = {}
        self._page_items            = []
        self._last_pixmap_check     = dt.datetime.now()
        self._pixmap_check_timer    = QTimer()
        self._pixmap_check_timer.setSingleShot(True)
        self._pixmap_check_timer.timeout.connect(self._ensure_visible_pages_loaded)

        # Page content management (pixmaps)
        self._connected_pixmaps     = set()                                 # Currently connected to the UI (not necessarily visible)
        self._loading_pixmaps       = set()                                 # In the loader queue
        self._removed_pixmaps       = set()                                 # Already marked outdated during loading
        self._pixmap_cache          = caching.PriorityCache(UIC.cache_size) # All loaded pages, not necessarily connected to UI
        self._loader_pool           = QThreadPool.globalInstance()

        # Page selection variables
        self._selected_doc_id       = None
        self._selection_pen         = QPen(QColor(*UIC.selection_color), UIC.selection_radius)

        # Prepare scene items and initialize arrangements (filled later)
        self._loaded_arrangements   = {k: v(self) for (k, v) in ARRANGEMENT_CLASS_ASSIGNMENTS.items()}
        self._arrangement_type      = UIC.default_arrangement

        self.update_scene_items()
        self._loaded_arrangements[self._arrangement_type].load_view_state()

        print("INFO: Available Loader Threads:  {}".format(self._loader_pool.maxThreadCount()))
        print("INFO: Pixmap Cache Size:         {}".format(self._pixmap_cache.size))



    # === Properties Methods ===

    @property
    def page_items(self) -> list[QGraphicsRectItem]:
        return self._page_items


    @property
    def case_filter(self) -> set[str] | None:
        return self._case_filter


    @case_filter.setter
    def case_filter(self, case_filter: set[str] | None):
        self._case_filter = case_filter
        self.update_scene_items()


    @property
    def doctype_filter(self) -> set[str | connectors._NO_DOCTYPE] | None:
        return self._doctype_filter


    @doctype_filter.setter
    def doctype_filter(self, doctype_filter: set[str | connectors._NO_DOCTYPE] | None):
        self._doctype_filter = doctype_filter
        self.update_scene_items()

    @property
    def junk_filter(self) -> bool:
        return self._junk_filter


    @junk_filter.setter
    def junk_filter(self, junk_filter: bool):
        self._junk_filter = junk_filter
        self.update_scene_items()


    @property
    def arrangement_type(self) -> ArrangementType:
        return self._arrangement_type


    @arrangement_type.setter
    def arrangement_type(self, arrangement_type: ArrangementType):
        # Attach current view states to the arrangement and load previous state
        self._loaded_arrangements[self._arrangement_type].save_view_state()
        self._arrangement_type  = arrangement_type
        self._loaded_arrangements[arrangement_type].load_view_state()
        self._ensure_visible_pages_loaded()


    @property
    def selection(self) -> dict | None:
        """
        Returns the document which is currently selected.
        """
        if self._selected_doc_id:
            return self._doc_id_to_doc[self._selected_doc_id]
        else:
            return None


    # === Public Methods ===

    def focus_page(self, item: QGraphicsItem):
        """
        Moved the viewport so that a given item is centered.

        Args:
            item: An item within the scene
        """
        self.centerOn(item)
        self._ensure_visible_pages_loaded()


    def toggle_select_document(self, doc_id: int | None = None):
        """
        Selects or deselects a document depending on if it has been selected before.
        If None is passed, the current selection is set to None.
        The selection_changed signal is triggered for all calls, except for consecutive calls with None.

        Args:
            doc_id: The identifier to select or deselect, or None
        """
        if doc_id == self._selected_doc_id == None:
            return

        unselect = self._selected_doc_id == doc_id

        # Deselect previous selection (does not trigger a signal)
        self._reset_selection()

        # Select pages (if a different document was selected than before)
        if doc_id and not unselect:
            self._apply_selection(doc_id)

        self.selection_changed.emit(self._selected_doc_id)
        self.prev_sel_available.emit(self._selected_doc_id is not None and len(self._page_items) and self._page_items[0].data(RectData.DOC_ID) != self._selected_doc_id)
        self.next_sel_available.emit(self._selected_doc_id is not None and len(self._page_items) and self._page_items[-1].data(RectData.DOC_ID) != self._selected_doc_id)


    def select_document(self, doc_id: int | None = None):
        """
        Unselects previous selection and selects a document for upcoming operations.
        If the same document is already selected, it remains selected.
        The selection_changed signal is triggered only when the selection actually changes.

        Args:
            doc_id: The identifier of the document to select or None
        """

        state_changed = (self._selected_doc_id != doc_id)

        # Deselect previous selection (does not trigger a signal)
        self._reset_selection()

        # Select pages
        if doc_id:
            self._apply_selection(doc_id)

        if state_changed:
            self.selection_changed.emit(self._selected_doc_id)
        self.prev_sel_available.emit(self._selected_doc_id is not None and len(self._page_items) and self._page_items[0].data(RectData.DOC_ID) != self._selected_doc_id)
        self.next_sel_available.emit(self._selected_doc_id is not None and len(self._page_items) and self._page_items[-1].data(RectData.DOC_ID) != self._selected_doc_id)


    def select_previous_document(self):
        """
        If there is a document currently selected, find, select and focus the previous document.
        """
        if self._selected_doc_id:
            first_doc_page  = self._doc_id_to_doc[self._selected_doc_id]['pages'][0]
            first_doc_index = self._page_id_to_index[(self._selected_doc_id, first_doc_page)]
            while first_doc_index > 0:
                doc_id      = self._page_items[first_doc_index - 1].data(RectData.DOC_ID)
                if doc_id != self._selected_doc_id:
                    first_page  = self._doc_id_to_doc[doc_id]['pages'][0]
                    first_rect  = self._page_id_to_rect[(doc_id, first_page)]
                    self.focus_page(first_rect)
                    self.select_document(doc_id)
                    break
                first_doc_index -= 1


    def select_next_document(self):
        """
        If there is a document currently selected, find, select and focus the next document.
        """
        if self._selected_doc_id:
            last_doc_page   = self._doc_id_to_doc[self._selected_doc_id]['pages'][-1]
            last_doc_index  = self._page_id_to_index[(self._selected_doc_id, last_doc_page)]
            while last_doc_index + 1 < len(self._page_items):
                doc_id = self._page_items[last_doc_index + 1].data(RectData.DOC_ID)
                if doc_id != self._selected_doc_id:
                    first_page  = self._doc_id_to_doc[doc_id]['pages'][0]
                    first_rect  = self._page_id_to_rect[(doc_id, first_page)]
                    self.focus_page(first_rect)
                    self.select_document(doc_id)
                    break
                last_doc_index += 1


    def update_page_arrangement(self):
        """
        Updates the Page Arrangement, i.e. for zoom changes or window resizing.
        """
        self._loaded_arrangements[self._arrangement_type].apply(self._page_items)
        self.setSceneRect(self.scene().itemsBoundingRect())
        self._ensure_visible_pages_loaded()


    def update_scene_items(self):
        """
        Creates page-wise QRectItems, attaches data and adds them to scene and buffer. Rectangles are buffered, so that only new ones need to be added to the scene.
        """
        # Mark loading pixmaps as depricated; disconnect loaded pixmaps;
        # TODO: optimize
        for key in self._loading_pixmaps:
            self._removed_pixmaps.add(key)
        self._connected_pixmaps.clear()

        # Request updates documents since last change
        new_store_docs          = {x['identifier']: x for x in self._document_store.find(updated_since = self._last_update_time)}
        new_store_doc_ids       = set(new_store_docs.keys())
        self._last_update_time  = dt.datetime.now()

        # Find out which documents to delete / create / update
        current_doc_ids = set(self._document_store.identifiers())
        prev_doc_ids    = set(self._doc_id_to_doc.keys())
        deleted_doc_ids = prev_doc_ids - current_doc_ids
        new_doc_ids     = new_store_doc_ids - prev_doc_ids
        updated_doc_ids = prev_doc_ids.intersection(new_store_doc_ids)

        # Delete old and updated page rects
        scene_items             = set(self.scene().items())
        for doc_id in deleted_doc_ids.union(updated_doc_ids):
            for rect in self._doc_id_to_rects[doc_id]:
                if rect in scene_items:
                    self.scene().removeItem(rect)
            self._doc_id_to_rects[doc_id].clear()
            for page_number in self._doc_id_to_doc[doc_id]['pages']:
                page_id = (doc_id, page_number)
                del self._page_id_to_rect[page_id]

        # Update buffered docs
        for doc_id in new_doc_ids.union(updated_doc_ids):
            self._doc_id_to_doc[doc_id] = new_store_docs[doc_id]
        for doc_id in deleted_doc_ids:
            del self._doc_id_to_doc[doc_id]

        # Create new / (updated) page rects
        for doc_id in new_doc_ids.union(updated_doc_ids):
            doc = self._doc_id_to_doc[doc_id]
            for page_number in doc['pages']:
                page_id = (doc_id, page_number)
                rect    = _create_page_item(doc, self._initial_rect, self._empty_pixmap)
                rect.setData(RectData.DOC_ID, doc_id)
                rect.setData(RectData.CASE, doc['case'])
                rect.setData(RectData.PATH, doc['path'])
                rect.setData(RectData.PAGE_NUMBER, page_number)
                rect.setData(RectData.DOCTYPES, doc['doctypes'])
                rect.setData(RectData.JUNK, doc['junk'])
                self._doc_id_to_rects[doc_id].append(rect)
                self._page_id_to_rect[page_id] = rect

        # TODO: somehow avoid sorting each time
        sorted_docs             = sorted(self._doc_id_to_doc.values(), key = lambda x: (x['case'], x['path'], x['pages']))
        self._page_id_to_index  = {}
        self._page_items        = []

        for doc in sorted_docs:

            # Apply filtering
            rects = self._doc_id_to_rects[doc['identifier']]
            if not self._satisfies_all_filters(doc):
                for rect in rects:
                    if rect in scene_items:
                        self.scene().removeItem(rect)
                continue
            else:
                for rect in rects:
                    if not rect in scene_items:
                        self.scene().addItem(rect)

            for page_number in doc['pages']:
                page_id = (doc['identifier'], page_number)
                self._page_id_to_index[page_id] = len(self._page_items)
                self._page_items.append(self._page_id_to_rect[page_id])

        # Arrange page items
        self.update_page_arrangement()

        # If selected ID still exists and is not filtered -> Highlight, otherwise -> reset selection
        if self._selected_doc_id:
            if self._selected_doc_id in self._doc_id_to_doc and self._satisfies_all_filters(self._doc_id_to_doc[self._selected_doc_id]):
                first_page  = self._doc_id_to_doc[self._selected_doc_id]['pages'][0]
                page_id     = (self._selected_doc_id, first_page)
                self.select_document(self._selected_doc_id)
            else:
                self.select_document(None)


    # === Private Methods ===

    def _reset_selection(self):
        """
        Reset highlighting for currently selected UI items.
        """
        if self._selected_doc_id and self._selected_doc_id in self._doc_id_to_rects:
            for rect in self._doc_id_to_rects[self._selected_doc_id]:
                rect.setPen(QPen(Qt.PenStyle.NoPen))
        self._selected_doc_id = None


    def _apply_selection(self, doc_id: int):
        """
        Highlight UI items depending on the provided document ID.

        Args:
            doc_id: The document identifier to highlight
        """
        if doc_id in self._doc_id_to_rects:
            for rect in self._doc_id_to_rects[doc_id]:
                rect.setPen(self._selection_pen)
        self._selected_doc_id = doc_id


    def _satisfies_all_filters(self, doc: dict) -> bool:
        """
        Returns True if all filter criteria are satisfied, such as case or doctypes.

        Args:
            doc:    The doc dictionary

        Returns:
            A bool indicating if all filters are satisfied
        """
        if self._case_filter and not doc['case'] in self._case_filter:
            return False
        if self._doctype_filter:
            if not doc['doctypes']:
                if not connectors.NO_DOCTYPE in self._doctype_filter:
                    return False
            elif not set(doc['doctypes']).intersection(self._doctype_filter):
                return False
        if self._junk_filter and doc['junk']:
            return False
        return True


    def _on_page_content_loaded(self, page_key: PageKey, pixmap: QPixmap):
        """
        Callback once a pixmap is finished loading. Typically triggered by a loader thread pool.

        Args:
            page_key:   A pageKey identifying the page + zoom level
            pixmap:     A loaded pixmap
        """
        # Already marked outdated -> Discard
        if page_key in self._removed_pixmaps:
            self._loading_pixmaps.discard(page_key)
            self._removed_pixmaps.discard(page_key)
            page_item   = self._page_id_to_rect[(page_key.doc_id, page_key.page_number)]
            pixmap_item = page_item.childItems()[0]
            pixmap_item.setPixmap(self._empty_pixmap)
            return

        # Assign pixmap to page item and play animation (if it was empty before)
        page_item   = self._page_id_to_rect[(page_key.doc_id, page_key.page_number)]
        pixmap_item = page_item.childItems()[0]
        from_empty  = pixmap_item.pixmap().isNull()

        # Scale according to parent and place it in center
        h_scale     = UIC.page_rect_width / pixmap.width()
        v_scale     = UIC.page_rect_height / pixmap.height()
        scale       = min(h_scale, v_scale)
        pixmap_item.setScale(scale)
        if h_scale > v_scale:
            h_offset = (UIC.page_rect_width - scale * pixmap.width()) / 2
            v_offset = 0
        else:
            h_offset = 0
            v_offset = (UIC.page_rect_height - scale * pixmap.height()) / 2
        pixmap_item.setPos(h_offset, v_offset)
        pixmap_item.setPixmap(pixmap)

        # Stylize when junk flag is set
        if page_item.data(RectData.JUNK):
            pixmap_item.graphicsEffect().setOpacity(UIC.junk_doc_opacity)

        # Fade in when newly loaded
        elif from_empty:
            pixmap_item.fade_in.start()

        self._loading_pixmaps.discard(page_key)
        self._connected_pixmaps.add(page_key)
        cache_key = CacheKey(page_key.doc_id, page_key.page_number)
        self._pixmap_cache.add(cache_key, pixmap, page_key.dpi)


    def _ensure_visible_pages_loaded(self):
        """
        Performs a viewport check over all page items. When close enough queues pixmap dataloading jobs to a thread pool.
        Uses caching to buffer pixmaps in different zoom levels. Only one concurrent check is allowed.
        """
        # Avoid rapid checks, i.e. for scrolling, enqueue a final check
        now = dt.datetime.now()
        if (now - self._last_pixmap_check).total_seconds() < UIC.pixmap_check_ms / 1000:
            self._pixmap_check_timer.start(UIC.pixmap_check_ms)
            return

        self._last_pixmap_check = now

        scale = self.transform().m11() # (assumes uniform scaling!)

        # Too far away to show page content -> Remove pixmaps from view (not from cache)
        if scale < UIC.zoom_hide_images:
            for page_key in self._loading_pixmaps:
                self._removed_pixmaps.add(page_key)
            for page_key in self._connected_pixmaps:
                rect = self._page_id_to_rect[(page_key.doc_id, page_key.page_number)]
                for child in rect.childItems():
                    child.fade_out.start()
                    child.fade_out.finished.connect(lambda c = child: c.setPixmap(self._empty_pixmap))
            self._connected_pixmaps.clear()
            return

        # Get required DPI level based on current scene scale
        scale_clip  = max(UIC.zoom_min, min(scale, UIC.zoom_max))
        dpi_scaler  = int((scale_clip - UIC.zoom_min) / ( UIC.zoom_max - UIC.zoom_min) * UIC.zoom_levels) / UIC.zoom_levels
        dpi         = int((dpi_scaler * (UIC.max_dpi - UIC.min_dpi)) + UIC.min_dpi)

        # Intersection check with visible scene rect (in scene coordinates)
        view_rect           = QRect(self.viewport().rect())
        visible_scene_rect  = self.mapToScene(view_rect).boundingRect()
        visible_page_keys   = set()
        for item in self.scene().items(visible_scene_rect):
            if isinstance(item, QGraphicsRectItem):
                key = PageKey(
                    item.data(RectData.DOC_ID),
                    item.data(RectData.CASE),
                    item.data(RectData.PATH),
                    item.data(RectData.PAGE_NUMBER),
                    dpi
                )
                visible_page_keys.add(key)

        # Mark pages as deprecated that are currently waiting to be loaded, but are no longer visible
        for key in self._loading_pixmaps - visible_page_keys:
            self._worker_jobs[key].mark_deprecated()
            self._loading_pixmaps.remove(key)

        # Remove non-visible pixmaps from UI
        for key in self._connected_pixmaps - visible_page_keys:
            self._connected_pixmaps.remove(key)
            page_item   = self._page_id_to_rect[(key.doc_id, key.page_number)]
            pixmap_item = page_item.childItems()[0]
            pixmap_item.setPixmap(self._empty_pixmap)

        # Load visible pages that aren't already loaded / pending / in cache
        load_new = visible_page_keys - self._connected_pixmaps - self._loading_pixmaps
        for key in load_new:
            self._loading_pixmaps.add(key)
            cache_key = CacheKey(key.doc_id, key.page_number)
            if self._pixmap_cache.contains(cache_key, key.dpi):
                cached_pixmap = self._pixmap_cache.get(cache_key, key.dpi)
                self._on_page_content_loaded(key, cached_pixmap)
            else:
                _, ext  = os.path.splitext(key.path)
                if FileLoader.supports_extension(ext):
                    loader = FileLoader.create(key, self._document_store.case_store, self._on_page_content_loaded)
                    self._worker_jobs[key] = loader
                    self._loader_pool.start(loader)
                else:
                    print("WARNING: Encountered unsupported File Type '{}'".format(ext))
                    continue


    # === Native / Overriden Methods ===

    def keyPressEvent(self, event: QKeyEvent):
        key                     = event.key()
        allow_vertical_scroll   = self._loaded_arrangements[self._arrangement_type].allow_vertical_scrolling()
        allow_horizontal_scroll = self._loaded_arrangements[self._arrangement_type].allow_horizontal_scrolling()

        # Scene Navigation (restrict scroll axes based on current view)
        if key == Qt.Key.Key_Left:
            if allow_horizontal_scroll:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - UIC.scroll_step)
        elif key == Qt.Key.Key_Right:
            if allow_horizontal_scroll:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + UIC.scroll_step)
        elif key == Qt.Key.Key_Up:
            if allow_vertical_scroll:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - UIC.scroll_step)
        elif key == Qt.Key.Key_Down:
            if allow_vertical_scroll:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + UIC.scroll_step)
        elif key == Qt.Key.Key_PageUp:
            if allow_vertical_scroll:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - self.height())
        elif key == Qt.Key.Key_PageDown:
            if allow_vertical_scroll:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + self.height())
        else:
            super().keyPressEvent(event)

        self._ensure_visible_pages_loaded()


    def resizeEvent(self, event: QResizeEvent):
        self.update_page_arrangement()
        super().resizeEvent(event)


    def scale(self, factor: float):

        # Anchor point in scene center
        if self._arrangement_type == ArrangementType.LABELING:
            center_screen       = self.viewport().rect().center()
            center_scene_before = self.mapToScene(center_screen)
            super().scale(factor, factor)
            center_scene_after  = self.mapToScene(center_screen)
            delta_scene         = center_scene_after - center_scene_before
            self.translate(delta_scene.x(), delta_scene.y())

        # Anchor point in origin
        else:
            super().scale(factor, factor)

        self.update_page_arrangement()


    def wheelEvent(self, event: QWheelEvent):

        QTimer.singleShot(50, self._ensure_visible_pages_loaded)

        # Wheel + CTRL -> Zoom
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = UIC.zoom_step_factor if event.angleDelta().y() > 0 else 1 / UIC.zoom_step_factor
            self.scale(factor)
            return

        # (Pagewise) Horizontal / Vertical Scrolling
        pagewise    = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        is_hor      = self._loaded_arrangements[self._arrangement_type].allow_horizontal_scrolling()
        is_vert     = self._loaded_arrangements[self._arrangement_type].allow_vertical_scrolling()
        sign        = 1 if event.angleDelta().x() + event.angleDelta().y() > 0 else -1

        if pagewise and is_hor:
            delta   = self.width()
        elif pagewise and is_vert:
            delta   = self.height()
        elif is_hor or is_vert:
            delta   = UIC.scroll_step
        else:
            delta   = 0

        if is_hor:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - sign * delta)
            self._ensure_visible_pages_loaded()
            return
        elif is_vert:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - sign * delta)
            self._ensure_visible_pages_loaded()
            return
        else:
            event.ignore()
            return


    def _construct_magnet_links(self) -> list[MagnetLink]:
        """
        Document operations such as splitting, merging and clustering may be triggered by drawing lines with the mouse, and connecting certain key points.
        If the user presses the mouse within a proximity radius around these so called magnets, the magnet points are stored along with their associated possible target points and actions.
        When releasing the mouse within the proximity radius around one of these target points, the associated operation can then be applied to the documents.
        """
        # Get all pages on screen
        visible_rect    = self.mapToScene(QRect(self.viewport().rect())).boundingRect()
        items           = self.scene().items(visible_rect)
        rect_items      = [item for item in items if isinstance(item, QGraphicsRectItem)]
        if not rect_items:
            return

        # Sort rect_items by global index (magnet link construction relies on consecutive pages)
        rect_items.sort(key = lambda x: self._page_id_to_index[(x.data(RectData.DOC_ID), x.data(RectData.PAGE_NUMBER))])

        # 1) Get all split points (top and bottom of gaps between pages within the same document)
        split_points = []
        for i in range(len(rect_items) - 1):
            doc_id_1    = rect_items[i].data(RectData.DOC_ID)
            doc_id_2    = rect_items[i+1].data(RectData.DOC_ID)
            if doc_id_1 == doc_id_2:
                # Special case: line break in arrangement -> add link to end of line
                if rect_items[i].sceneBoundingRect().topRight().x() >= rect_items[i+1].sceneBoundingRect().topLeft().x():
                    pos_top     = rect_items[i].sceneBoundingRect().topRight()
                    pos_top.setX(pos_top.x() + UIC.gap_between_pages / 2)
                    pos_bottom  = rect_items[i].sceneBoundingRect().bottomRight()
                    pos_bottom.setX(pos_bottom.x() + UIC.gap_between_pages / 2)
                else:
                    pos_top     = (rect_items[i].sceneBoundingRect().topRight() + rect_items[i+1].sceneBoundingRect().topLeft()) / 2
                    pos_bottom  = (rect_items[i].sceneBoundingRect().bottomRight() + rect_items[i+1].sceneBoundingRect().bottomLeft()) / 2
                first_page  = min(rect_items[i].data(RectData.PAGE_NUMBER), rect_items[i+1].data(RectData.PAGE_NUMBER))
                split_points.append(SplitMagnetLink(pos_top, pos_bottom, doc_id_1, first_page))
                split_points.append(SplitMagnetLink(pos_bottom, pos_top, doc_id_1, first_page))

        # 2) Get all merge points (page centers for the first and last pages of a document with the same path and doctypes)
        merge_points = []
        for i in range(len(rect_items) - 1):
            doc_id_1    = rect_items[i].data(RectData.DOC_ID)
            doc_id_2    = rect_items[i+1].data(RectData.DOC_ID)
            doctypes_1  = rect_items[i].data(RectData.DOCTYPES)
            doctypes_2  = rect_items[i+1].data(RectData.DOCTYPES)
            path_1      = rect_items[i].data(RectData.PATH)
            path_2      = rect_items[i+1].data(RectData.PATH)
            is_junk_1   = rect_items[i].data(RectData.JUNK)
            is_junk_2   = rect_items[i+1].data(RectData.JUNK)
            if doc_id_1 != doc_id_2 and path_1 == path_2 and doctypes_1 == doctypes_2 and is_junk_1 == is_junk_2:
                doc1_end    = rect_items[i].sceneBoundingRect().center()
                doc2_start  = rect_items[i+1].sceneBoundingRect().center()
                merge_points.append(MergeMagnetLink(doc1_end, doc2_start, doc_id_1, doc_id_2))
                merge_points.append(MergeMagnetLink(doc2_start, doc1_end, doc_id_1, doc_id_2))

        # 3) Get all cluster points (page centers all pages of documents with more than 1 page)
        cluster_points  = []
        len_per_doc     = Counter(item.data(RectData.DOC_ID) for item in rect_items)
        for i in range(len(rect_items)):
            doc_id_1    = rect_items[i].data(RectData.DOC_ID)
            for j in range(len(rect_items)):
                doc_id_2    = rect_items[j].data(RectData.DOC_ID)
                if doc_id_1 == doc_id_2 and len_per_doc[doc_id_1] > 1:
                    doc1_center = rect_items[i].sceneBoundingRect().center()
                    doc2_center = rect_items[j].sceneBoundingRect().center()
                    page_1      = rect_items[i].data(RectData.PAGE_NUMBER)
                    page_2      = rect_items[j].data(RectData.PAGE_NUMBER)
                    cluster_points.append(ClusterMagnetLink(doc1_center, doc2_center, doc_id_1, page_1, page_2))

        return split_points + merge_points + cluster_points


    def mousePressEvent(self, event: QMouseEvent):

        scene_pos   = self.mapToScene(event.pos())

        # Left Button + CTRL -> Open with extern PDF Viewer
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            items       = self.scene().items(scene_pos)
            rect_items  = [item for item in items if isinstance(item, QGraphicsRectItem)]
            if rect_items:
                rect        = rect_items[0]
                case_root   = self._document_store.case_store[rect.data(RectData.CASE)]
                abs_path    = os.path.join(case_root, rect.data(RectData.PATH))
                if os.path.exists(abs_path):
                    utils.open_file(abs_path, rect.data(RectData.PAGE_NUMBER))

        # Right Button + CTRL -> Focus Page (Opens Labeling View)
        elif event.button() == Qt.MouseButton.RightButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            items       = self.scene().items(scene_pos)
            rects       = [item for item in items if isinstance(item, QGraphicsRectItem)]
            if len(rects):
                if not self._arrangement_type == ArrangementType.LABELING:
                    self.arrangement_type = ArrangementType.LABELING
                self.focus_page(rects[0])

        # Right Button -> Draw Line Start
        elif event.button() == Qt.MouseButton.RightButton:

            # Too far away for drawing
            if self.transform().m11() < UIC.draw_max_zoom:
                return

            # Find magnets within proximity radius
            magnet_points           = self._construct_magnet_links()
            self._available_magnets = []
            for magnet_point in magnet_points:
                if utils.euclidean_distance(scene_pos, magnet_point.source_pos) < UIC.draw_max_snap_distance:
                    self._available_magnets.append(magnet_point)

            if not self._available_magnets:
                return

            self._draw_mode_delay_timer.start(int(1000 * UIC.draw_delay_time))
            self._line = ContrastLineItem(self._available_magnets[0].source_pos, self._available_magnets[0].source_pos, LineOperation.INVALID)
            self.scene().addItem(self._line)

            # Create circles to indicate where the line can be dragged to
            for magnet_point in self._available_magnets:
                top_left    = magnet_point.target_pos - QPointF(UIC.magnet_circle_radius / 2, UIC.magnet_circle_radius / 2)
                circle      = QGraphicsEllipseItem(top_left.x(), top_left.y(), UIC.magnet_circle_radius, UIC.magnet_circle_radius)

                if magnet_point.operation == LineOperation.SPLIT:
                    circle_color = UIC.line_color_split
                elif magnet_point.operation == LineOperation.MERGE:
                    circle_color = UIC.line_color_merge
                elif magnet_point.operation == LineOperation.CLUSTER:
                    circle_color = UIC.line_color_cluster
                else:
                    circle_color = UIC.line_color_invalid
                circle.setBrush(QBrush(QColor(*circle_color)))
                circle.setPen(QPen(Qt.PenStyle.NoPen))
                self._magnet_target_items.add(circle)
                self.scene().addItem(circle)

        # Left Button + Drawing Active -> Abort Drawing Operation
        elif event.button() == Qt.MouseButton.LeftButton and self._available_magnets:
            self._available_magnets = None
            self._closest_magnet    = None
            if self._line and self._line in self.scene().items():
                self.scene().removeItem(self._line)
                self._line = None

        # Left Button -> Select Page
        elif event.button() == Qt.MouseButton.LeftButton:
            items       = self.scene().items(scene_pos)
            rect_items  = [item for item in items if isinstance(item, QGraphicsRectItem)]
            if rect_items:
                self.toggle_select_document(rect_items[0].data(RectData.DOC_ID))

        # Middle Button -> Translation Start
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._translation_start = self.mapToScene(event.pos())

        else:
            super().mousePressEvent(event)


    def mouseReleaseEvent(self, event: QMouseEvent):

        # Right Button -> Draw Line End (Apply operation, remove magnet targets)
        if event.button() == Qt.MouseButton.RightButton:

            for circle in self._magnet_target_items:
                self.scene().removeItem(circle)
            self._magnet_target_items.clear()
            self._available_magnets = []

            if self._line and self._line in self.scene().items():
                self.scene().removeItem(self._line)
                self._line = None

            # Rapid Press and Release -> Don't count
            if self._draw_mode_delay_timer.isActive():
                self._draw_mode_delay_timer.stop()
                self._closest_magnet    = None
                return

            if not self._closest_magnet:
                return

            magnet              = self._closest_magnet
            if magnet.operation == LineOperation.CLUSTER:
                cluster_range   = list(range(min(magnet.page_start, magnet.page_end), max(magnet.page_start, magnet.page_end) + 1))
                action          = actions.ClusterAction(self._document_store, magnet.doc_id, cluster_range)
            elif magnet.operation == LineOperation.MERGE:
                action          = actions.MergeAction(self._document_store, magnet.doc_id_1, magnet.doc_id_2)
            elif magnet.operation == LineOperation.SPLIT:
                action = actions.SplitAction(self._document_store, magnet.doc_id, magnet.split_after)
            else:
                action = None

            if action:
                self.store_operation.emit(action)

            self._closest_magnet    = None

        # Right Button ->
        elif event.button() == Qt.MouseButton.RightButton:
            pass

        # Middle Button -> Translation Stop
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._translation_start = None

        super().mouseReleaseEvent(event)


    def mouseMoveEvent(self, event: QMouseEvent):

        scene_pos   = self.mapToScene(event.pos())

        # Update Drawing
        if self._available_magnets:
            min_dist        = UIC.draw_max_snap_distance
            closest_magnet  = None
            for magnet_point in self._available_magnets:
                distance    = utils.euclidean_distance(scene_pos, magnet_point.target_pos)
                if distance < min_dist:
                    min_dist        = distance
                    closest_magnet  = magnet_point

            # No target magnets close -> invalid operation
            if closest_magnet is None:
                self._line.operation    = LineOperation.INVALID
                self._closest_magnet    = None
                return



            # Add a visual horizontal offset when a single page has been selected for clustering
            if closest_magnet.operation == LineOperation.CLUSTER and utils.euclidean_distance(closest_magnet.source_pos, closest_magnet.target_pos) < UIC.epsilon:
                h_offset    = (1 if closest_magnet.source_pos.x() < closest_magnet.target_pos.x() else -1) * UIC.line_horizontal_offset
            else:
                h_offset    = 0
            offset = QPointF(h_offset, 0)

            self._line.operation    = closest_magnet.operation
            self._line.p1           = closest_magnet.source_pos - offset
            self._line.p2           = closest_magnet.target_pos + offset

            self._closest_magnet    = closest_magnet

        # Update Translation
        elif self._translation_start is not None:

            trans_vec   = scene_pos - self._translation_start

            if not self._loaded_arrangements[self._arrangement_type].allow_vertical_scrolling():
                trans_vec.setY(0)
            elif not self._loaded_arrangements[self._arrangement_type].allow_horizontal_scrolling():
                trans_vec.setX(0)
            self.translate(trans_vec.x(), trans_vec.y())
            self._ensure_visible_pages_loaded()
            return

        return super().mouseMoveEvent(event)



class MainWindow(QMainWindow):

    new_doctype_created = pyqtSignal(str)
    new_case_created    = pyqtSignal(str)
    store_imported      = pyqtSignal(str)
    store_exported      = pyqtSignal(str)


    def __init__(self, store: connectors.DocumentStore, parent: QWidget | None = None):
        """
        A main window to hold the main widget, a status bar and a menu bar.

        Args:
            store:      A document store to provide document access
            parent:     The parent QWidget
        """
        super().__init__(parent)

        self._init_application_settings()

        self._validate_case_paths(store)
        self._validate_file_paths(store)

        self._init_page_canvas(store)

        self._action_queue  = actions.ActionManager()

        self._init_menu_toolbar(store)
        self._init_labeling_toolbar(store)
        self._init_filtering_toolbar(store)
        self._init_action_log_toolbar()

        for toolbar in [self._menu_tool_bar, self._labeling_toolbar, self._filtering_toolbar, self._action_log_toolbar]:
            toolbar.setContentsMargins(0, 0, UIC.toolbar_spacing, 0)
            toolbar.layout().setSpacing(UIC.toolbar_item_spacing)

        self._init_timers()

        central = QWidget()
        central_layout = QVBoxLayout()

        self.addToolBar(self._menu_tool_bar)
        self.addToolBar(self._labeling_toolbar)
        self.addToolBar(self._filtering_toolbar)
        self.addToolBar(self._action_log_toolbar)

        self._init_document_info_dockable()

        central_layout.addWidget(self._canvas)
        central.setLayout(central_layout)
        self.setCentralWidget(central)


    def do(self, action: actions.Action):
        """
        Append an action to the action queue
        """
        try:
            self._action_queue.do(action)
        except (connectors.IdentifierNotFoundException, actions.MergeException):
            ActionConflictDialog().exec()
        self._canvas.update_scene_items()


    def undo(self):
        """
        Undo the last action
        """
        if self._action_queue.undo_chain_length:
            try:
                self._action_queue.undo()
            except (connectors.IdentifierNotFoundException, actions.MergeException):
                ActionConflictDialog().exec()
            self._canvas.update_scene_items()


    def redo(self):
        """
        Redo the last action
        """
        if self._action_queue.redo_chain_length:
            try:
                self._action_queue.redo()
            except (connectors.IdentifierNotFoundException, actions.MergeException):
                ActionConflictDialog().exec()
            self._canvas.update_scene_items()


    def keyPressEvent(self, event: QKeyEvent):

        key = event.key()

        # Unfold Doctype Labeling Box
        if key == Qt.Key.Key_Alt:
            if self._canvas.selection:
                self._labeling_box.showPopup()

        # Toggle Junk Document Filter
        elif key == Qt.Key.Key_J and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._junk_filter_box.setChecked(not self._canvas.junk_filter)

        # Letter -> propagate to labeling
        elif event.text().isalpha():
            if self._canvas.selection:
                self._labeling_box.keyPressEvent(event)

        return super().keyPressEvent(event)


    def _init_application_settings(self):
        """Sets properties of the Application, such as disabling mouse double clicks or the latency between repeating keyboard inputs"""
        QApplication.setDoubleClickInterval(0)
        QApplication.setKeyboardInputInterval(0)


    def _validate_case_paths(self, store: connectors.DocumentStore):
        """
        Checks the existence of case root folders and opens a dialog to resolve missing folders.

        Args:
            store: The document store
        """
        for case in store.missing_case_paths():
            dialog      = ResolveCasePathDialog(store, case)
            ret_code    = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                store.case_store[case] = dialog.path
                continue
            raise InitializationException("Could not resolve path for case '{}'!".format(case))


    def _validate_file_paths(self, store: connectors.DocumentStore):
        """
        Checks the existence of all files mentioned in the document store and opens a dialog listing the missing ones.
        The dialog is informational only.

        Args:
            store: The document store
        """
        for (case, missing_paths) in store.missing_file_paths().items():
            MissingFilesDialog(case, list(sorted(missing_paths))).exec()


    def _init_page_canvas(self, store: connectors.DocumentStore):
        """
        Initializes the page canvas widget containing the graphics scene

        Args:
            store: The document store
        """
        self._canvas = PageCanvas(store)
        self._canvas.store_operation.connect(self.do)


    def _init_menu_toolbar(self, store: connectors.DocumentStore):
        """
        Initializes the menu bar containing all action menus and icons

        Args:
            store: The document store
        """
        menu_tool_bar  = QToolBar(self)
        menu_tool_bar.setIconSize(QSize(UIC.icon_size, UIC.icon_size))
        menu_tool_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        # App -> Close / Import / Export / New Case

        # - Close
        app_menu        = QMenu("App", self)
        close_action    = QAction("Close", self)
        close_action.setShortcut("Esc")
        close_action.triggered.connect(self.close)

        # - Import
        def import_callback():
            doctypes_before = set(store.doctypes())
            cases_before    = set(store.cases())
            self._update_timer.stop()
            dialog          = ImportDialog(store)
            ret_code        = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                self._canvas.update_scene_items()
                self.store_imported.emit(dialog.path)
                for new_doctype in set(store.doctypes()) - doctypes_before:
                    self.new_doctype_created.emit(new_doctype)
                    utils.sorted_insert(self._labeling_box, new_doctype, lambda _x = new_doctype: self._assign_doctype_callback(_x))
                for new_case in set(store.cases()) - cases_before:
                    self.new_case_created.emit(new_case)
            self._update_timer.start()

        import_action   = QAction("Import Document Store", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(import_callback)

        # - Export
        def export_callback():
            dialog      = ExportDialog(store)
            ret_code    = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                self.store_exported.emit(dialog.path)

        export_action   = QAction("Export Document Store", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(export_callback)

        # - New Case
        def new_case_callback():
            dialog      = CreateCaseDialog(store)
            ret_code    = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                store.case_store[dialog.case] = dialog.case_root
                self._canvas.update_scene_items()
                self.new_case_created.emit(dialog.case)

        new_case_action = QAction("New Case", self)
        new_case_action.setShortcut("Ctrl+N")

        new_case_action.triggered.connect(new_case_callback)

        [app_menu.addAction(x) for x in [close_action, import_action, export_action, new_case_action]]

        # View -> Page View / Document View / Labeling View / Information Panel / Minimize / Fullscreen

        # - Views
        view_menu       = QMenu("View", self)
        view_actions    = []
        for i, (name, class_) in enumerate([('Pages', ArrangementType.PAGE), ('Documents', ArrangementType.DOCUMENT), ('Labeling', ArrangementType.LABELING)]):
            view_action = QAction(name, self)
            view_action.setShortcut(str(i + 1))
            view_action.triggered.connect(lambda x, c = class_:  self._canvas.__setattr__('arrangement_type', c))
            view_actions.append(view_action)
        [view_menu.addAction(x) for x in view_actions]
        view_menu.addSeparator()

        # - Information Panel
        def toggle_info_panel(checked: bool):
            if checked:
                self._document_info_dockable.show()
                self._document_info_dockable.raise_()
                self._document_info_dockable.setFloating(False)  # if it got detached and you want to dock it
                self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._document_info_dockable)
            else:
                self.removeDockWidget(self._document_info_dockable)
                self._document_info_dockable.hide()
        toggle_information_panel    = QAction("Information Panel", self)
        toggle_information_panel.setCheckable(True)
        toggle_information_panel.setChecked(False)
        toggle_information_panel.setShortcut("Ctrl+D")
        toggle_information_panel.toggled.connect(toggle_info_panel)

        # - Minimize
        minimize_action     = QAction("Minimize", self)
        minimize_action.setShortcut("Ctrl+F11")
        minimize_action.triggered.connect(self.showMinimized)

        # - Fullscreen
        fullscreen_action   = QAction("Fullscreen", self)
        fullscreen_action.setCheckable(True)
        fullscreen_action.setChecked(True)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.toggled.connect(lambda x: self.showFullScreen() if x else self.showNormal())

        [view_menu.addAction(x) for x in [toggle_information_panel, minimize_action, fullscreen_action]]

        for menu in [app_menu, view_menu]:
            menu_button = QToolButton()
            menu_button.setText(menu.title())
            menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu_button.setMenu(menu)
            menu_tool_bar.addWidget(menu_button)

        # Undo/Redo Buttons
        undo_action     = QAction(self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.setToolTip("Undo last action (Ctrl+Z)")
        undo_action.setIcon(utils.load_icon(UIC.icon_path_undo))
        undo_action.triggered.connect(self.undo)
        undo_action.setDisabled(True)
        self._action_queue.undo_chain_length_changed.connect(lambda x: undo_action.setDisabled(x == 0))
        menu_tool_bar.addAction(undo_action)

        redo_action     = QAction(self)
        redo_action.setShortcut("Ctrl+Shift+Z")
        redo_action.setToolTip("Redo last action (Ctrl+Shift+Z)")
        redo_action.setIcon(utils.load_icon(UIC.icon_path_redo))
        redo_action.triggered.connect(self.redo)
        redo_action.setDisabled(True)
        self._action_queue.redo_chain_length_changed.connect(lambda x: redo_action.setDisabled(x == 0))
        menu_tool_bar.addAction(redo_action)

        # Junk Button
        junk_action     = QAction(self)
        junk_action.setShortcut("Delete")
        junk_action.setToolTip("(De-)Assign as junk (Delete)")
        junk_action.setIcon(utils.load_icon(UIC.icon_path_trash))
        junk_action.triggered.connect(lambda x: self.do(actions.AssignJunkAction(store, self._canvas.selection['identifier'], not self._canvas.selection['junk'])))
        junk_action.setDisabled(True)
        self._canvas.selection_changed.connect(lambda x: junk_action.setDisabled(x is None))
        menu_tool_bar.addAction(junk_action)

        # Select Next/Previous Buttons
        prev_action     = QAction(self)
        prev_action.setShortcut("Ctrl+Left")
        prev_action.setToolTip("Select previous document (Ctrl+Left)")
        prev_action.setIcon(utils.load_icon(UIC.icon_path_prev))
        prev_action.triggered.connect(self._canvas.select_previous_document)
        prev_action.setDisabled(True)
        self._canvas.prev_sel_available.connect(prev_action.setEnabled)
        menu_tool_bar.addAction(prev_action)

        next_action     = QAction(self)
        next_action.setShortcuts(["Ctrl+Right", "Space"])
        next_action.setToolTip("Select next document (Ctrl+Right)")
        next_action.setIcon(utils.load_icon(UIC.icon_path_next))
        next_action.triggered.connect(self._canvas.select_next_document)
        next_action.setDisabled(True)
        self._canvas.next_sel_available.connect(next_action.setEnabled)
        menu_tool_bar.addAction(next_action)

        # Zoom In / Out
        zoom_out_action  = QAction(self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.setToolTip("Zoom out (Ctrl+Minus)")
        zoom_out_action.setIcon(utils.load_icon(UIC.icon_zoom_out))
        zoom_out_action.triggered.connect(lambda x: self._canvas.scale(1 / UIC.zoom_step_factor))
        menu_tool_bar.addAction(zoom_out_action)
        zoom_in_action  = QAction(self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.setToolTip("Zoom in (Ctrl+Plus)")
        zoom_in_action.setIcon(utils.load_icon(UIC.icon_zoom_in))
        zoom_in_action.triggered.connect(lambda x: self._canvas.scale(UIC.zoom_step_factor))
        menu_tool_bar.addAction(zoom_in_action)

        # Update
        update_action   = QAction(self)
        update_action.setShortcut("F5")
        update_action.setToolTip("Update view based on database (F5)")
        update_action.setIcon(utils.load_icon(UIC.icon_update))
        update_action.triggered.connect(self._canvas.update_scene_items)
        menu_tool_bar.addAction(update_action)

        self._menu_tool_bar = menu_tool_bar


    def _init_labeling_toolbar(self, store: connectors.DocumentStore):
        """
        Initializes the labeling toolbar containing the labeling widget

        Args:
            store: The document store
        """
        # Labeling Combobox
        doctype_labeling  = FoldableComboBox()
        doctype_labeling.setDisabled(True)
        doctype_labeling.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        doctype_labeling.setPlaceholderText(UIC.doctype_placeholder_no_selection)

        def assign_doctype_callback(doctype: str | connectors._NO_DOCTYPE):
            if self._canvas.selection:
                action = actions.AssignDoctypeAction(store, self._canvas.selection['identifier'], doctype)
                self.do(action)
                update_labeling_elements_on_selection_change()
        self._assign_doctype_callback = assign_doctype_callback

        for doctype in store.doctypes():
            doctype_labeling.addItem(doctype, lambda _doctype = doctype: assign_doctype_callback(_doctype))
        doctype_labeling.currentIndexChanged.connect(lambda i: doctype_labeling.itemData(i)())
        self._labeling_box = doctype_labeling

        def on_new_doctype():
            dialog      = CreateDoctypeDialog(store)
            ret_code    = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                callback        = lambda _doctype = dialog.doctype: assign_doctype_callback(_doctype)
                insert_index    = utils.sorted_insert(doctype_labeling, dialog.doctype, callback)
                doctype_labeling.setCurrentIndex(insert_index)
                self.new_doctype_created.emit(dialog.doctype)
            dialog.destroy()

        # New Doctype Button
        new_doctype_button      = QPushButton("New")
        new_doctype_button.clicked.connect(on_new_doctype)
        new_doctype_button.setDisabled(True)

        # Reset Doctype Button
        reset_doctype_button    = QPushButton("Reset")
        reset_doctype_button.clicked.connect(lambda: assign_doctype_callback(connectors.NO_DOCTYPE))
        reset_doctype_button.setDisabled(True)

        # Callback to update Labeling based on Selection
        def update_labeling_elements_on_selection_change():
                doctype_labeling.blockSignals(True)

                # 1) No Selection
                if not self._canvas.selection:
                    doctype_labeling.setPlaceholderText(UIC.doctype_placeholder_no_selection)
                    doctype_labeling.setCurrentIndex(-1)
                    doctype_labeling.setDisabled(True)
                    reset_doctype_button.setDisabled(True)
                    new_doctype_button.setDisabled(True)

                # 2) Selection without assigned Doctype
                elif not (doctypes := self._canvas.selection['doctypes']):
                    doctype_labeling.setPlaceholderText(UIC.doctype_placeholder_no_doctype)
                    doctype_labeling.setCurrentIndex(-1)
                    doctype_labeling.setDisabled(False)
                    reset_doctype_button.setDisabled(True)
                    new_doctype_button.setEnabled(True)

                # 3) Document with at least one Doctype
                else:
                    doctype_labeling.setCurrentText(doctypes[0])
                    doctype_labeling.setDisabled(False)
                    reset_doctype_button.setEnabled(True)
                    new_doctype_button.setEnabled(True)

                doctype_labeling.blockSignals(False)

        self._canvas.selection_changed.connect(update_labeling_elements_on_selection_change)

        h_wrapper_layout = QHBoxLayout()
        h_wrapper_layout.setSpacing(UIC.toolbar_item_spacing)
        h_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        h_wrapper_layout.addWidget(doctype_labeling)
        h_wrapper_layout.addWidget(new_doctype_button)
        h_wrapper_layout.addWidget(reset_doctype_button)
        h_wrapper_container = QWidget()
        h_wrapper_container.setLayout(h_wrapper_layout)

        v_wrapper_layout = QVBoxLayout()
        v_wrapper_layout.setSpacing(0)
        v_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        v_wrapper_layout.addWidget(QLabel("Document Type Labeling"))
        v_wrapper_layout.addWidget(h_wrapper_container)
        v_wrapper_container = QWidget()
        v_wrapper_container.setLayout(v_wrapper_layout)

        labeling_toolbar = QToolBar(self)
        labeling_toolbar.addWidget(v_wrapper_container)

        self._labeling_toolbar = labeling_toolbar


    def _init_filtering_toolbar(self, store: connectors.DocumentStore):
        """
        Initializes the filtering toolbar containing the case, doctype and junk filters.

        Args:
            store: The document store
        """
        # Case Filter
        case_filter_box     = FoldableComboBox()
        case_filter_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        case_filter_box.addItem("<All>", None)
        for case in store.cases():
            case_filter_box.addItem(case, case)

        def case_filter_update(index: int):
            case = case_filter_box.itemData(index)
            self._canvas.case_filter = set([case]) if isinstance(case, str) else set()

        case_filter_box.activated.connect(case_filter_update)
        self.new_case_created.connect(lambda x: utils.sorted_insert(case_filter_box, x, x))

        # Doctype Filter
        doctype_filter_box      = FoldableComboBox()
        doctype_filter_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        doctype_filter_box.addItem("<All>", None)
        doctype_filter_box.addItem("<Not Assigned>", connectors.NO_DOCTYPE)
        for doctype in store.doctypes():
            doctype_filter_box.addItem(doctype, doctype)

        def doctype_filter_update(index: int):
            doctype = doctype_filter_box.itemData(index)
            self._canvas.doctype_filter = set([doctype]) if isinstance(doctype, str) or doctype == connectors.NO_DOCTYPE else set()

        doctype_filter_box.activated.connect(doctype_filter_update)
        self.new_doctype_created.connect(lambda x: utils.sorted_insert(doctype_filter_box, x, x))

        # Junk Filter
        def junk_filter_update(junk: bool):
            self._canvas.junk_filter = junk

        junk_filter_box         = QCheckBox()
        junk_filter_box.checkStateChanged.connect(lambda x: junk_filter_update(junk_filter_box.isChecked()))
        self._junk_filter_box       = junk_filter_box

        vbox_1 = QVBoxLayout()
        vbox_1.addWidget(QLabel("Case Filter"))
        vbox_1.addWidget(case_filter_box)

        vbox_2 = QVBoxLayout()
        vbox_2.addWidget(QLabel("Doctype Filter"))
        vbox_2.addWidget(doctype_filter_box)

        vbox_3 = QVBoxLayout()
        vbox_3.addWidget(QLabel("Junk Filter"))
        vbox_3.addWidget(junk_filter_box, alignment = Qt.AlignmentFlag.AlignCenter)

        filtering_toolbar = QToolBar(self)
        for vbox in [vbox_1, vbox_2, vbox_3]:
            vbox_widget = QWidget(self)
            vbox_widget.setLayout(vbox)
            vbox.setSpacing(0)
            vbox.setContentsMargins(0, 0, 0, 0)
            filtering_toolbar.addWidget(vbox_widget)

        self._filtering_toolbar = filtering_toolbar


    def _init_action_log_toolbar(self):
        """Initializes the action log toolbar"""
        message_bar = QPlainTextEdit()
        message_bar.appendHtml("<pre>Action Log</pre>")
        font = QFont()
        font.setPointSize(UIC.log_font_size)
        message_bar.setFont(font)
        message_bar.setReadOnly(True)
        message_bar.setMaximumBlockCount(UIC.action_log_max_lines)
        self.new_doctype_created.connect(lambda doctype: message_bar.appendHtml("<pre>Created:\tNew Doctype '{}'</pre>".format(doctype)))
        self.new_case_created.connect(lambda case: message_bar.appendHtml("<pre>Created:\tNew Case '{}'</pre>".format(case)))
        self.store_imported.connect(lambda path: message_bar.appendHtml("<pre>Imported:\t'{}'</pre>".format(path)))
        self.store_exported.connect(lambda path: message_bar.appendHtml("<pre>Exported:\t'{}'</pre>".format(path)))
        self._action_queue.do_triggered.connect(lambda action: message_bar.appendHtml("<pre>Do:\t{}</pre>".format(action)))
        self._action_queue.undo_triggered.connect(lambda action: message_bar.appendHtml("<pre>Undo:\t{}</pre>".format(action)))
        self._action_queue.redo_triggered.connect(lambda action: message_bar.appendHtml("<pre>Redo:\t{}</pre>".format(action)))
        message_bar.setFixedHeight(UIC.action_log_height)
        action_log_toolbar          = QToolBar()
        action_log_toolbar.addWidget(message_bar)
        self._action_log_toolbar    = action_log_toolbar


    def _init_document_info_dockable(self):
        """Initializes document information dockable widget"""
        information_bar = QPlainTextEdit()
        font = QFont()
        font.setPointSize(UIC.log_font_size)
        information_bar.setFont(font)
        information_bar.setReadOnly(True)

        def show_document_information():
            document = self._canvas.selection
            information_bar.clear()
            if document is not None:
                information_bar.appendHtml("<pre>{}{}</pre>".format('identifier:'.ljust(12), document['identifier']))
                for k in sorted(set(document.keys()) - set(['identifier'])):
                    if isinstance(document[k], list) and len(document[k]) > 6:
                        value = "[{}, {}, {}, ..., {}, {}, {}]".format(*document[k][:3], *document[k][-3:])
                    else:
                        value = document[k]
                    information_bar.appendHtml("<pre>{}{}</pre>".format((k + ':').ljust(12), value))

        self._canvas.selection_changed.connect(show_document_information)

        information_bar.setFixedHeight(UIC.info_log_height)
        information_bar.setFixedWidth(UIC.info_log_width)
        document_info_dockable          = QDockWidget()
        document_info_dockable.setWidget(information_bar)
        self._document_info_dockable    = document_info_dockable


    def _init_timers(self):
        """Initializes a UI update timer to periodically update scene items according to the latest document store changes."""
        timer               = QTimer(self)
        timer.timeout.connect(self._canvas.update_scene_items)
        timer.start(UIC.update_frequency_ms)
        self._update_timer  = timer