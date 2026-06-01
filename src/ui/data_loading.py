from __future__ import annotations

import os
import src.utils as utils
from pdf2image import convert_from_path
from PIL import Image
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QRunnable, QObject
from PyQt6.QtGui import QPixmap, QImage
import threading
from typing import Type, Callable

from .data_classes import PageKey, UIConstants as UIC
from src.connectors import CaseStore



class Signals(QObject):
    loaded = pyqtSignal(PageKey, QPixmap)



class FileLoader(QRunnable):

    _registry: dict[str, Type[FileLoader]] = {}

    def __init__(self, key: PageKey, case_store: CaseStore, loaded_callback: Callable[[PageKey, QPixmap], None]):
        super().__init__()
        self._key           = key
        self._case_store    = case_store
        self._signals       = Signals()
        self._signals.loaded.connect(loaded_callback)
        self._deprecated    = threading.Event()


    @classmethod
    def register_loader(cls, extension: str):
        """Decorator to register a loader for a file extension (e.g., '.pdf')."""
        def decorator(loader_class: Type['FileLoader']):
            cls._registry[extension.lower()] = loader_class
            return loader_class
        return decorator


    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        return list(cls._registry.keys())


    @classmethod
    def supports_extension(cls, ext: str) -> bool:
        return ext.lower() in cls._registry


    @classmethod
    def create(cls, key: PageKey, case_store: CaseStore, loaded_callback: Callable[[PageKey, QPixmap], None]) -> FileLoader:
        """
        Creates a File Loader dedicated to the file extension of the provided file type within the PageKey.

        Args:
            key:                The PageKey containing all information of the object to load and where to find it
            case_store:         The case store to get local root directories for all cases
            loaded_callback:    A callback function triggered once the file is loaded

        Returns:
            The dedicated FileLoader
        """
        _, ext  = os.path.splitext(key.path)
        ext     = ext.lower()
        if ext not in cls._registry:
            raise ValueError("No loader registered for extension '{}'".format(ext))
        return cls._registry[ext](key, case_store, loaded_callback)


    @pyqtSlot()
    def run(self):
        raise NotImplementedError


    def _load_fallback_pixmap(self) -> QPixmap:
        return utils.load_svg_as_pixmap(UIC.icon_path_missing, UIC.missing_file_icon_size, UIC.missing_file_icon_color)


    def mark_deprecated(self):
        self._deprecated.set()


@FileLoader.register_loader('.pdf')
class PdfLoader(FileLoader):

    @pyqtSlot()
    def run(self):

        if self._deprecated.is_set():
            return

        try:
            case_root   = self._case_store[self._key.case]
            abs_path    = os.path.join(case_root, self._key.path)
            doc         = convert_from_path(abs_path, first_page = self._key.page_number + 1, last_page = self._key.page_number + 1, dpi = self._key.dpi)[0]
            qpiximage   = doc.toqpixmap()
        except:
            qpiximage   = self._load_fallback_pixmap()

        self._signals.loaded.emit(self._key, qpiximage)



@FileLoader.register_loader('.png')
@FileLoader.register_loader('.jpg')
@FileLoader.register_loader('.jpeg')
@FileLoader.register_loader('.bmp')
class ImageLoader(FileLoader):

    @pyqtSlot()
    def run(self):

        if self._deprecated.is_set():
            return

        try:
            case_root   = self._case_store[self._key.case]
            abs_path    = os.path.join(case_root, self._key.path)
            with Image.open(abs_path) as image:
                if image.mode != "RGBA":
                    image = image.convert("RGBA")

                data    = image.tobytes("raw", "RGBA")

            qimg        = QImage(data, image.size[0], image.size[1], QImage.Format.Format_RGBA8888)
            qpiximage   = QPixmap.fromImage(qimg)
        except:
            qpiximage   = self._load_fallback_pixmap()

        self._signals.loaded.emit(self._key, qpiximage)
