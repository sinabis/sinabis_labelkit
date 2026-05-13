import src.connectors as connectors
from src.config import load_config

config              = load_config()
backend_configs     = {
    'mongodb':  config.mdb,
    'postgres': config.psql
}

for backend, backend_configs in backend_configs.items():

    print("\nDropping documents from backend '{}' ...".format(backend))
    store   = connectors.create_store(backend, backend_configs)
    result  = store.delete()
    assert store.count() == 0
    print("\u2705 Deleted: '{}' documents!".format(result))