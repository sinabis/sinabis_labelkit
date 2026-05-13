from src.config import load_config
from src.connectors import create_store
from src.ui import MainWindow, InitializationException
from PyQt6.QtWidgets import QApplication
import sys

# Load Document Store
config = load_config()
if config.backend == 'postgres':
    store   = create_store('postgres', config.psql)
elif config.backend == 'mongodb':
    store   = create_store('mongodb', config.mdb)
else:
    raise ValueError("backend must be 'postgres' or 'mongodb'")

# Start Application
try:
    app     = QApplication(sys.argv)
    widget  = MainWindow(store)
    widget.setWindowTitle("Document Labeling Tool")
    widget.showFullScreen()
except InitializationException:
    raise
app.exec()