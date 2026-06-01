from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any
from PyQt6.QtCore import QPointF


class RectData(IntEnum):
    DOC_ID      = 0
    CASE        = 1
    PAGE_NUMBER = 2
    PATH        = 3
    DOCTYPES    = 4
    JUNK        = 5


class ArrangementType(Enum):
    PAGE        = 0
    DOCUMENT    = 1
    LABELING    = 2


class LineOperation(Enum):
    INVALID     = 0
    CLUSTER     = 1
    SPLIT       = 2
    MERGE       = 3


@dataclass(frozen = True)
class MagnetLink:
    source_pos:     QPointF
    target_pos:     QPointF


@dataclass(frozen = True)
class ClusterMagnetLink(MagnetLink):
    doc_id:         Any
    page_start:     int
    page_end:       int

    @property
    def operation(self) -> LineOperation:
        return LineOperation.CLUSTER


@dataclass(frozen = True)
class MergeMagnetLink(MagnetLink):
    doc_id_1:       Any
    doc_id_2:       Any

    @property
    def operation(self) -> LineOperation:
        return LineOperation.MERGE


@dataclass(frozen = True)
class SplitMagnetLink(MagnetLink):
    doc_id:         Any
    split_after:    int

    @property
    def operation(self) -> LineOperation:
        return LineOperation.SPLIT



@dataclass(frozen = True)
class CacheKey:
    doc_id:         Any
    page_number:    int


@dataclass(frozen = True)
class PageKey:
    doc_id:         Any
    case:           str
    path:           str
    page_number:    int
    dpi:            int


@dataclass(frozen = True)
class UIConstants:

    # General
    epsilon:                float       = 0.0001

    # UI Updates
    update_frequency_ms:    int         = 5000
    pixmap_check_ms:        int         = 333

    # Junk Documents
    junk_doc_opacity:       float       = 0.3
    junk_strip_color_1:     tuple       = (0, 0, 0, 100)
    junk_strip_color_2:     tuple       = (255, 255, 255, 100)
    junk_strip_size:        float       = 0.1

    # Startup Behavior
    default_arrangement:    ArrangementType = ArrangementType.PAGE
    default_case_filter:    str | None      = None
    default_doctype_filter: str | None      = None
    default_junk_filter:    bool            = False

    # Scene Spacing
    doc_arrangement_gap:    float       = 0.5   # Margin to the right so that pages dont leave the sceen within document arrangement
    page_arrangement_scale: float       = 300
    doc_arrangement_scale:  float       = 300
    lab_arrangement_scale:  float       = 1400
    gap_between_pages:      float       = 0.02
    gap_between_documents:  float       = 0.2
    page_rect_width:        float       = 0.6
    page_rect_height:       float       = 1.0   # 1.0 ~ Screen Height

    # Zooming
    cache_size:             int         = 1000
    min_dpi:                int         = 10
    max_dpi:                int         = 100
    zoom_levels:            int         = 5
    zoom_hide_images:       float       = 100
    zoom_min:               float       = 150
    zoom_max:               float       = 1000

    # Line Drawing
    draw_max_snap_distance: float       = 0.3
    draw_max_zoom:          float       = 125
    line_color_invalid:     tuple       = (0, 0, 0, 100)
    line_color_cluster:     tuple       = (0, 0, 255, 100)
    line_color_merge:       tuple       = (0, 255, 0, 100)
    line_color_split:       tuple       = (255, 0, 0, 100)
    line_color_glow:        tuple       = (255, 255, 255, 100)
    line_inner_width:       float       = 0.05
    line_outer_width:       float       = 0.1
    line_horizontal_offset: float       = 0.07
    magnet_circle_radius:   float       = 0.1
    draw_delay_time:        float       = 0.15

    # Document Selection
    selection_color:        tuple       = (200, 0, 0, 255)
    selection_radius:       float       = 0.015

    # Interaction
    scroll_step:            int         = 100
    zoom_step_factor:       float       = 1.2

    # Status Bar
    action_log_max_lines:   int         = 100
    action_log_height:      int         = 50
    info_log_width:         int         = 500
    info_log_height:        int         = 130
    toolbar_spacing:        int         = 20
    toolbar_item_spacing:   int         = 5
    log_font_size:          int         = 8
    doctype_placeholder_no_doctype:     str     = "Assign"
    doctype_placeholder_no_selection:   str     = "No Selection"

    # Animations
    fade_in_duration:       int         = 200
    fade_out_duration:      int         = 200

    # Icons
    icon_size:              int         = 24
    icon_path_undo:         str         = "assets/arrow-arc-left.svg"
    icon_path_redo:         str         = "assets/arrow-arc-right.svg"
    icon_path_prev:         str         = "assets/arrow-left.svg"
    icon_path_next:         str         = "assets/arrow-right.svg"
    icon_path_trash:        str         = "assets/trash.svg"
    icon_path_missing:      str         = "assets/broken.svg"
    icon_zoom_in:           str         = "assets/magnifying-glass-plus.svg"
    icon_zoom_out:          str         = "assets/magnifying-glass-minus.svg"
    icon_update:            str         = "assets/arrows-clockwise.svg"
    missing_file_icon_size: int         = 300
    missing_file_icon_color: tuple      = (100, 0, 0, 255)