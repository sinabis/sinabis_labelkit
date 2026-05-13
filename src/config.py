from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, BaseModel
from typing import Literal



class DatabaseConfig(BaseModel):
    host:       str
    port:       int
    name:       str
    user:       str
    password:   str



class AppSettings(BaseSettings):
    backend:        Literal["postgres", "mongodb"]
    psql:           DatabaseConfig
    mdb:            DatabaseConfig
    case_root_file: str
    test_postgres:  bool
    test_mongodb:   bool
    test_db_prefix: str

    model_config = SettingsConfigDict(
        env_file            = ".env",
        env_file_encoding   = "utf-8",
        case_sensitive      = False,
        extra               = "ignore",
    )
    

    @model_validator(mode = "before")
    @classmethod
    def load_nested_configs(cls, data: dict) -> dict:
        
        prefix_to_backend = {'psql': 'db_psql_', 'mdb': 'db_mdb_'}
        for backend, prefix in prefix_to_backend.items():
            data[backend] = DatabaseConfig(
                host        = data.get(prefix + 'host'),
                port        = data.get(prefix + 'port'),
                name        = data.get(prefix + 'name'),
                user        = data.get(prefix + 'user', ''),
                password    = data.get(prefix + 'password', '')
            )

        # Top-level fields
        data["backend"]         = data.get("db_backend")
        data["case_root_file"]  = data.get("case_root_file")
        data["test_postgres"]   = bool(data.get("test_postgres"))
        data["test_mongodb"]    = bool(data.get("test_mongodb"))
        data["test_db_prefix"]  = data.get("test_db_prefix")

        return data



def load_config():
    return AppSettings()