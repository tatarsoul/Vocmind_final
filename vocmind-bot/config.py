from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )

    bot_token: str
    backend_base_url: str = "http://localhost:8000"
    bot_internal_key: str = "vm_9x2k_a81q_secret_backend_bot_2026"
    mini_app_url: str = "https://porchless-volcanically-isreal.ngrok-free.dev/lk"


settings = Settings()