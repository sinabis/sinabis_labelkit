import os
import pdf2image
import re
from pdf2image.exceptions import PDFPageCountError
from PyQt6.QtCore import pyqtSlot, pyqtSignal, QObject, QRunnable, QThreadPool, QTimer
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget
from typing import Callable

from .. import utils
from ..connectors import DocumentStore, ImportException
from .data_loading import FileLoader

VALID_DB_STRING_REGEX   = r"^[a-z0-9_ßöüä-]+$"
ERROR_STYLE             = "color: red;"
MIN_WINDOW_WIDTH        = 700
SUCCESS_MESSAGE_MSECS   = 800



class ActionConflictDialog(QDialog):

    def __init__(self, parent: QWidget | None = None):
        """
        A Dialog to indicate that a document store action could not be performed.

        Args:
            parent: The parent QWidget
        """
        super().__init__(parent)

        self.setWindowTitle("⚠️ Action not possible")

        QBtn = QDialogButtonBox.StandardButton.Ok

        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)

        layout = QVBoxLayout()
        message = QPlainTextEdit("Not able to apply action.\nThis is likely caused by concurrent document store operations.\nUI is updated.")
        message.setReadOnly(True)
        layout.addWidget(message)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)



class MissingFilesDialog(QDialog):

    def __init__(self, case: str, missing_files: list[str], parent: QWidget | None = None):
        """
        A Dialog to indicate that files referenced in the document store are missing on the device.

        Args:
            parent: The parent QWidget
        """
        super().__init__(parent)

        self.setWindowTitle("⚠️ Missing Files")

        QBtn = QDialogButtonBox.StandardButton.Ok

        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)

        layout = QVBoxLayout()
        message = QPlainTextEdit("Case {} is missing files:\n".format(case))
        for file in missing_files:
            message.appendPlainText("\t{}".format(file))
        message.setReadOnly(True)
        layout.addWidget(message)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)



class ResolveCasePathDialog(QDialog):

    def __init__(self, store: DocumentStore, case: str, parent: QWidget | None = None):
        """
        A dialog to select a new case path.

        Args:
            store:  The document store
            case:   The case name
            parent: The parent QWidget
        """
        super().__init__(parent)

        self._store         = store
        self._case          = case
        self._path          = ""

        self.setWindowTitle("Resolve invalid Case Root")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        # = File path =
        self._path_edit     = QLineEdit()
        self._path_edit.setDisabled(True)
        self._browse_button = QPushButton("Browse")
        self._browse_button.clicked.connect(self._choose_file_path)
        self._dir_errors    = QLabel()
        self._dir_errors.setStyleSheet(ERROR_STYLE)

        # = Progress Bar =
        self._progress_bar  = QProgressBar()
        self._progress_msg  = QPlainTextEdit("")
        self._progress_msg.setReadOnly(True)

        # = Buttons =
        buttons         = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box      = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)

        # = Layout =
        grid_layout     = QGridLayout()
        grid_layout.addWidget(QLabel("Select Root Directory for Case '{}'".format(case)), 0, 0, 1, 2)
        grid_layout.addWidget(self._path_edit, 1, 0)
        grid_layout.addWidget(self._browse_button, 1, 1)
        grid_layout.addWidget(self._dir_errors, 2, 0, 1, 2)
        grid_layout.addWidget(self._progress_bar, 3, 0, 1, 2)
        grid_layout.addWidget(self._progress_msg, 4, 0, 1, 2)
        grid_container  = QWidget()
        grid_container.setLayout(grid_layout)

        # = Main Layout =
        layout          = QVBoxLayout()
        layout.addWidget(grid_container)
        layout.addWidget(button_box)
        self.setLayout(layout)


    @property
    def path(self) -> str:
        return self._path


    def _choose_file_path(self):
        self._path = QFileDialog.getExistingDirectory(parent = self)
        self._path_edit.setText(self._path)
        self._validate_fields()


    def _validate_fields(self):
        if not len(self._path):
            self._dir_errors.setText("Path cannot be empty")
        elif not os.path.exists(self._path):
            self._dir_errors.setText("Path does not exist")
        elif not self._perform_file_check():
            self._dir_errors.setText("Path is missing files")
        else:
            self._dir_errors.clear()
            self._ok_button.setEnabled(True)
            QTimer.singleShot(SUCCESS_MESSAGE_MSECS, self.accept)


    def _perform_file_check(self) -> bool:
        self._progress_msg.setPlainText("Checking Files ...")
        docs = self._store.find(cases = [self._case])
        self._progress_bar.setMaximum(len(docs))
        valid = True
        for i, doc in enumerate(docs):
            abs_path = os.path.join(self._path, doc['path'])
            if not os.path.exists(abs_path):
                valid = False
                self._progress_msg.appendPlainText("File '{}' does not exist!".format(abs_path))
            self._progress_bar.setValue(i)

        if valid:
            self._progress_msg.appendPlainText("All Files found")

        return valid



class WorkerThread(QRunnable):

    def __init__(self, job_callback: Callable[[], None], on_exception: Callable[[Exception], None], on_success: Callable[[], None]):
        """
        A runnable class to execute a job callback, which might last a long time, in a thread, so that the UI never freezes.
        Once done it triggers either a callback for successfull execution or a callback for exceptions.
        This class is implemented in a way so that exception and success callbacks are executed in the main thread, so that UI calls are possible.

        Args:
            job_callback:   The function to execute, which might take a while
            on_exception:   A function executed when exceptions occur during job execution
            on_success:     A function executed once the job callback finishes successfully
        """
        super().__init__()

        class InternSignals(QObject):
            finished    = pyqtSignal()
            error       = pyqtSignal(Exception)

        self._callback      = job_callback
        self._on_exception  = on_exception
        self._on_success    = on_success

        self._signals       = InternSignals()
        self._signals.finished.connect(self._on_success)
        self._signals.error.connect(self._on_exception)


    @pyqtSlot()
    def run(self):
        try:
            self._callback()
            self._signals.finished.emit()
        except Exception as e:
            self._signals.error.emit(e)



class ImportDialog(QDialog):

    def __init__(self, store: DocumentStore, parent: QWidget | None = None):
        """
        A dialog to import the entire document store from a serializable JSON file.

        Args:
            parent: The parent QWidget
        """
        super().__init__(parent)

        self._store     = store
        self._file_path = ""

        self.setWindowTitle("Import Document Store")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        # = File path =
        self._path_edit     = QLineEdit()
        self._path_edit.setDisabled(True)
        self._browse_button = QPushButton("Browse")
        self._browse_button.clicked.connect(self._choose_file_path)
        self._dir_errors    = QLabel()
        self._dir_errors.setStyleSheet(ERROR_STYLE)
        self._progress_msg  = QLabel()

        # = Buttons =
        buttons         = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box      = QDialogButtonBox(buttons)
        button_box.accepted.connect(self._import)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)

        # = Layout =
        grid_layout     = QGridLayout()
        grid_layout.addWidget(QLabel("File Path:"), 0, 0)
        grid_layout.addWidget(self._path_edit, 0, 1)
        grid_layout.addWidget(self._browse_button, 0, 2)
        grid_layout.addWidget(self._dir_errors, 1, 0, 1, 3)
        grid_layout.addWidget(self._progress_msg, 2, 0, 1, 3)
        grid_container  = QWidget()
        grid_container.setLayout(grid_layout)

        # = Main Layout =
        layout          = QVBoxLayout()
        layout.addWidget(grid_container)
        layout.addWidget(button_box)
        self.setLayout(layout)


    @property
    def path(self) -> str:
        return self._file_path


    def _choose_file_path(self):
        self._file_path, _ = QFileDialog.getOpenFileName(parent = self, filter = "JSON (*.json)")
        self._path_edit.setText(self._file_path)
        self._validate_fields()


    def _validate_fields(self):
        valid = False
        if not len(self._file_path):
            self._dir_errors.setText("Path cannot be empty")
        elif not self._file_path.endswith('.json'):
            self._dir_errors.setText("Path must be a .json file")
        else:
            self._dir_errors.clear()
            valid = True
        self._ok_button.setEnabled(valid)


    def _import_job(self):

        self._store.import_documents(self._file_path)

        def resolve_invalid_case_root(case) -> bool:
            dialog      = ResolveCasePathDialog(self._store, case)
            ret_code    = dialog.exec()
            if ret_code == QDialog.DialogCode.Accepted:
                self._store.case_store[case] = dialog.path
                return True
            return False

        # Resolve case roots from the document store which are missing
        for case in self._store.missing_case_paths():
            if not resolve_invalid_case_root(case):
                raise ImportException("Could not resolve path for case '{}'!".format(case))

        # Warning for missing file paths
        for (case, missing_paths) in self._store.missing_file_paths().items():
            MissingFilesDialog(case, list(sorted(missing_paths))).exec()


    def _import(self):
        self._progress_msg.setText("Importing...")
        self._ok_button.setEnabled(False)
        self._browse_button.setEnabled(False)

        # Run import in background thread so that UI does not freeze
        job_callback = lambda: self._import_job()
        self._future = WorkerThread(job_callback, self._on_exception, self._on_success)
        QThreadPool.globalInstance().start(self._future)


    def _on_success(self):
        self._progress_msg.setText("Done!")
        QTimer.singleShot(SUCCESS_MESSAGE_MSECS, self.accept)


    def _on_exception(self, exception: Exception):
        self._progress_msg.setText(str(exception))
        self._ok_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._future = None



class ExportDialog(QDialog):

    def __init__(self, store: DocumentStore, parent: QWidget | None = None):
        """
        A dialog to export the entire document store to a serializable JSON file.

        Args:
            parent: The parent QWidget
        """
        super().__init__(parent)

        self._store     = store
        self._file_path = ""

        self.setWindowTitle("Export Document Store")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        # = File path =
        self._path_edit     = QLineEdit()
        self._path_edit.setDisabled(True)
        self._browse_button = QPushButton("Browse")
        self._browse_button.clicked.connect(self._choose_file_path)
        self._dir_errors    = QLabel()
        self._dir_errors.setStyleSheet(ERROR_STYLE)
        self._progress_msg  = QLabel()

        # = Buttons =
        buttons         = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box      = QDialogButtonBox(buttons)
        button_box.accepted.connect(self._export)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)

        # = Layout =
        grid_layout     = QGridLayout()
        grid_layout.addWidget(QLabel("File Path:"), 0, 0)
        grid_layout.addWidget(self._path_edit, 0, 1)
        grid_layout.addWidget(self._browse_button, 0, 2)
        grid_layout.addWidget(self._dir_errors, 1, 0, 1, 3)
        grid_layout.addWidget(self._progress_msg, 2, 0, 1, 3)
        grid_container  = QWidget()
        grid_container.setLayout(grid_layout)

        # = Main Layout =
        layout          = QVBoxLayout()
        layout.addWidget(grid_container)
        layout.addWidget(button_box)
        self.setLayout(layout)


    @property
    def path(self) -> str:
        return self._file_path


    def _choose_file_path(self):
        self._file_path, _ = QFileDialog.getSaveFileName(parent = self, filter = "JSON (*.json)")
        self._path_edit.setText(self._file_path)
        self._validate_fields()


    def _validate_fields(self):
        valid = False
        if not len(self._file_path):
            self._dir_errors.setText("Path cannot be empty")
        elif not self._file_path.endswith('.json'):
            self._dir_errors.setText("Path must be a .json file")
        else:
            self._dir_errors.clear()
            valid = True
        self._ok_button.setEnabled(valid)


    def _export(self):
        self._progress_msg.setText("Exporting...")
        self._ok_button.setEnabled(False)
        self._browse_button.setEnabled(False)

        # Run import in background thread so that UI does not freeze
        job_callback = lambda: self._store.export_documents(self._file_path)
        self._future = WorkerThread(job_callback, self._on_exception, self._on_success)
        QThreadPool.globalInstance().start(self._future)


    def _on_success(self):
        self._progress_msg.setText("Done!")
        QTimer.singleShot(SUCCESS_MESSAGE_MSECS, self.accept)


    def _on_exception(self, exception: Exception):
        self._progress_msg.setText(str(exception))
        self._ok_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._future = None



class CreateDoctypeDialog(QDialog):

    def __init__(self, store: DocumentStore, parent: QWidget | None = None):
        """
        A dialog to create a new doctype with a text box being the only input field.

        Args:
            parent: The parent QWidget
        """
        super().__init__(parent)

        self._store = store

        self.setWindowTitle("Create new Doctype")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        self._doctype_edit      = QLineEdit()
        self._doctype_edit.textChanged.connect(self._validate_doctype)
        self._doctype_errors    = QLabel()
        self._doctype_errors.setStyleSheet(ERROR_STYLE)

        buttons                 = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box              = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self._ok_button         = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)

        # = Layout =
        grid_layout     = QGridLayout()
        grid_layout.addWidget(QLabel("Doctype Name:"), 0, 0)
        grid_layout.addWidget(self._doctype_edit, 0, 1, 1, 2)
        grid_layout.addWidget(self._doctype_errors, 1, 0, 1, 3)
        grid_container  = QWidget()
        grid_container.setLayout(grid_layout)

        # = Main Layout =
        layout          = QVBoxLayout()
        layout.addWidget(grid_container)
        layout.addWidget(button_box)
        self.setLayout(layout)


    @property
    def doctype(self) -> str:
        return self._doctype


    def _validate_doctype(self, doctype: str):

        doctype_lower = doctype.lower()

        if not len(doctype_lower):
            self._doctype_errors.setText("Doctype cannot be empty")
            valid = False
        elif not re.match(VALID_DB_STRING_REGEX, doctype_lower):
            self._doctype_errors.setText("Doctype contains invalid symbols")
            valid = False
        elif doctype_lower in self._store.doctypes():
            self._doctype_errors.setText("Doctype already exists in database")
            valid = False
        else:
            self._doctype_errors.clear()
            valid = True

        self._ok_button.setEnabled(valid)
        self._doctype = doctype_lower



class CreateCaseDialog(QDialog):

    progress_total      = pyqtSignal(int)
    progress_advanced   = pyqtSignal(int, str)


    def __init__(self, store: DocumentStore, parent: QWidget | None = None):
        """
        A dialog to create a new case. The user chooses a valid name, which is not yet in the document store, and selects a root directory where all files are are recursively assigned to the case.
        When 'ok' is clicked, the document store is filled.

        Args:
            store: The document store
            parent: The parent QWidget
        """
        super().__init__(parent)

        self._store         = store
        self._case_root     = None
        self._valid_path    = False
        self._case_name     = None
        self._valid_name    = False

        self.setWindowTitle("Create new Case")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        # = UI Setup =
        # 1) Case Name Selection
        self._name_edit     = QLineEdit()
        self._name_edit.textChanged.connect(self._validate_name)
        self._name_errors   = QLabel()
        self._name_errors.setStyleSheet(ERROR_STYLE)

        # 2) Root Directory
        self._dir_edit      = QLineEdit()
        self._dir_edit.setDisabled(True)
        self._browse_button = QPushButton("Browse")
        self._browse_button.clicked.connect(self._choose_file_path)
        self._dir_errors    = QLabel()
        self._dir_errors.setStyleSheet(ERROR_STYLE)

        # 3) Progress Bar
        self._progress_bar  = QProgressBar()
        self._progress_msg  = QLabel()

        # = Layout =
        grid_layout     = QGridLayout()
        grid_layout.addWidget(QLabel("Case Name:"), 0, 0)
        grid_layout.addWidget(self._name_edit, 0, 1, 1, 2)
        grid_layout.addWidget(self._name_errors, 1, 0, 1, 3)
        grid_layout.addWidget(QLabel("Root Directory:"), 2, 0)
        grid_layout.addWidget(self._dir_edit, 2, 1)
        grid_layout.addWidget(self._browse_button, 2, 2)
        grid_layout.addWidget(self._dir_errors, 3, 0, 1, 3)
        grid_layout.addWidget(self._progress_bar, 4, 0, 1, 3)
        grid_layout.addWidget(self._progress_msg, 5, 0, 1, 3)
        grid_container  = QWidget()
        grid_container.setLayout(grid_layout)

        # = Buttons =
        buttons         = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box      = QDialogButtonBox(buttons)
        button_box.accepted.connect(self._store_files)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)

        # = Main Layout =
        layout          = QVBoxLayout()
        layout.addWidget(grid_container)
        layout.addWidget(button_box)
        self.setLayout(layout)

        # Marshal progress updates from the worker thread back to the GUI thread
        self.progress_total.connect(self._on_progress_total)
        self.progress_advanced.connect(self._on_progress_advanced)


    @property
    def case(self) -> str | None:
        return self._case_name


    @property
    def case_root(self) -> str | None:
        return self._case_root


    def _store_files(self):
        """
        Starts a background worker that traverses all files recursively and stores them in the document store.
        """
        if self._case_root is None or self._case_name is None:
            return

        # Register the case root BEFORE inserting docs so loaders can resolve file paths
        self._store.case_store[self._case_name] = self._case_root

        self._progress_msg.setText("Scanning files ...")
        self._ok_button.setEnabled(False)
        self._browse_button.setEnabled(False)

        # Run in background thread so that the UI does not freeze
        job_callback    = lambda: self._store_files_job()
        self._future    = WorkerThread(job_callback, self._on_exception, self._on_success)
        QThreadPool.globalInstance().start(self._future)


    def _store_files_job(self):
        """
        Traverses all files recursively and stores them in the document store. Runs in a worker thread;
        progress is reported to the GUI thread via signals.
        """
        files               = utils.ls_rec(self._case_root)
        self.progress_total.emit(len(files))
        unknown_extensions  = set()
        for i, file in enumerate(files):

            _, ext = os.path.splitext(file)
            if not FileLoader.supports_extension(ext):
                if not ext in unknown_extensions:
                    unknown_extensions.add(ext)
                    print("WARNING: Skipped unsupported File Type '{}'".format(ext))
                self.progress_advanced.emit(i + 1, "Skipped {}".format(file))
                continue
            elif ext == '.pdf':
                try:
                    no_pages    = pdf2image.pdfinfo_from_path(file)['Pages']
                except PDFPageCountError:
                    print("WARNING: Skipped PDF with unsupported page range: '{}'".format(file))
                    self.progress_advanced.emit(i + 1, "Skipped {}".format(file))
                    continue
                pages       = list(range(no_pages))
            else:
                pages       = [0]

            local_path  = os.path.relpath(file, self._case_root)
            self.progress_advanced.emit(i + 1, "Inserting {}".format(local_path))
            self._store.insert(case = self._case_name, path = local_path, pages = pages)


    def _on_progress_total(self, total: int):
        self._progress_bar.setMaximum(total)


    def _on_progress_advanced(self, value: int, message: str):
        self._progress_bar.setValue(value)
        self._progress_msg.setText(message)


    def _on_success(self):
        self._progress_msg.setText("Done")
        QTimer.singleShot(SUCCESS_MESSAGE_MSECS, self.accept)


    def _on_exception(self, exception: Exception):
        self._progress_msg.setText(str(exception))
        self._ok_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._future = None


    def _check_button_states(self):
        """
        Checks if all inputs are valid and enables the 'ok' button if so.
        """
        self._ok_button.setEnabled(self._valid_name and self._valid_path)


    def _validate_name(self, case: str):
        """
        Checks if a string is a valid case name.

        Args:
            case:   The text to validate
        """

        case_lower = case.lower()

        if not len(case_lower):
            self._name_errors.setText("Name cannot be empty")
            self._valid_name = False
        elif not re.match(VALID_DB_STRING_REGEX, case_lower):
            self._name_errors.setText("Name contains invalid characters")
            self._valid_name = False
        elif case_lower in self._store.cases():
            self._name_errors.setText("Case already exists in Document Store")
            self._valid_name = False
        else:
            self._name_errors.clear()
            self._valid_name = True

        self._check_button_states()
        self._case_name = case_lower


    def _choose_file_path(self):
        """
        Opens a file dialog to choose a folder and validates the returned path.
        """
        case_root = QFileDialog.getExistingDirectory(parent = self)

        if not len(case_root):
            self._dir_errors.setText("Path cannot be empty")
            self._valid_path    = False
        else:
            self._dir_errors.clear()
            self._dir_edit.setText(case_root)
            self._valid_path    = True

        self._check_button_states()
        self._case_root = case_root
