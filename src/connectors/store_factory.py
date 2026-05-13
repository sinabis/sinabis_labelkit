from src.config import DatabaseConfig
from .document_store import DocumentStore
from typing import Literal

try:
    from .mongo_store import MongoStore
    print("INFO: Backend 'MongoDB' available")
except:
    pass

try:
    from .postgres_store import PostgresStore
    print("INFO: Backend 'Postgres' available")
except:
    pass


def create_store(
    backend:    Literal["postgres", "mongo"],
    config:     DatabaseConfig
) -> DocumentStore:
    if backend == "postgres":
        return PostgresStore(config)
    elif backend == "mongodb":
        return MongoStore(config)
    else:
        raise ValueError("backend must be 'postgres' or 'mongodb'")