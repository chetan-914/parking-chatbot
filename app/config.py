import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(
        default="gpt-6-luna",
        alias="OPENAI_MODEL",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="EMBEDDING_MODEL",
    )

    # PostgreSQL
    postgres_admin_dsn: SecretStr = Field(alias="POSTGRES_ADMIN_DSN")
    postgres_agent_dsn: SecretStr = Field(alias="POSTGRES_AGENT_DSN")

    # Weaviate
    weaviate_host: str = Field(
        default="localhost",
        alias="WEAVIATE_HOST",
    )
    weaviate_http_port: int = Field(
        default=8080,
        alias="WEAVIATE_HTTP_PORT",
    )
    weaviate_grpc_port: int = Field(
        default=50051,
        alias="WEAVIATE_GRPC_PORT",
    )
    weaviate_collection: str = Field(
        default="ParkingKnowledge",
        alias="WEAVIATE_COLLECTION",
    )

    # Retrieval
    retrieval_top_k: int = Field(
        default=5,
        alias="RETRIEVAL_TOP_K",
    )

    # Chunking
    chunk_size: int = Field(
        default=1000,
        alias="CHUNK_SIZE",
        gt=0,
    )
    chunk_overlap: int = Field(
        default=150,
        alias="CHUNK_OVERLAP",
        ge=0,
    )

    # Application
    timezone: str = Field(
        default="Asia/Kolkata",
        alias="TZ",
    )
    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    @property
    def openai_key(self) -> str:
        return self.openai_api_key.get_secret_value()

    @property
    def admin_dsn(self) -> str:
        return self.postgres_admin_dsn.get_secret_value()

    @property
    def agent_dsn(self) -> str:
        return self.postgres_agent_dsn.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Return a cached application settings instance."""
    settings = Settings()

    if settings.chunk_overlap >= settings.chunk_size:
        raise ValueError(
            "CHUNK_OVERLAP must be smaller than CHUNK_SIZE."
        )

    return settings


settings = get_settings()