from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8100
    grpc_port: int = 50051
    env: str = "development"

    # Redis
    redis_url: str = "redis://localhost:6379/0"


    # LLM
    litellm_proxy_url: str = "http://localhost:4000"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Whisper
    whisper_model: str = "base"
    whisper_mode: str = "local"  

    # Tools
    google_places_api_key: str = ""

    # Session
    session_ttl_seconds: int = 1800

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()