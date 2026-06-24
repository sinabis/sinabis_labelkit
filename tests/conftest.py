import pytest

import src.connectors as connectors
from src.config import load_config


# Check which backends to test
_settings           = load_config()
_backends_to_test   = []
if _settings.test_mongodb:
    _backends_to_test.append('mongodb')
if _settings.test_postgres:
    _backends_to_test.append('postgres')


@pytest.fixture(params = _backends_to_test)
def backend_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def store(backend_name: str):
    settings            = load_config()
    settings.backend    = backend_name
    if backend_name == 'mongodb':
        settings.mdb.name = settings.test_db_prefix + settings.mdb.name
        store   = connectors.create_store('mongodb', settings.mdb)
    elif backend_name == 'postgres':
        settings.psql.name = settings.test_db_prefix + settings.psql.name
        store   = connectors.create_store('postgres', settings.psql)
    else:
        raise ValueError("backend must be 'postgres' or 'mongodb'")

    count_before        = store.count()
    if count_before > 0:
        store.delete()
    assert store.count() == 0

    yield store

    try:
        store.delete()
        assert store.count() == 0
    except:
        pass