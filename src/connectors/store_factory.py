from typing import Literal

from .document_store import DocumentStore
from src.config import DatabaseConfig

try:
    from .mongo_store import MongoStore
    print("INFO: Backend 'MongoDB' available")
except ImportError:
    pass

try:
    from .postgres_store import PostgresStore
    print("INFO: Backend 'Postgres' available")
except ImportError:
    pass


def create_store(
    backend:    Literal["postgres", "mongodb"],
    config:     DatabaseConfig
) -> DocumentStore:
    if backend == "postgres":
        return PostgresStore(config)
    elif backend == "mongodb":
        return MongoStore(config)
    else:
        raise ValueError("backend must be 'postgres' or 'mongodb'")