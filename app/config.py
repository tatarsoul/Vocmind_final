from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VocMind Pro"

    telegram_bot_token: str = Field(
        "",
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "telegram_bot_token", "bot_token"),
    )
    auth_secret: str = Field(
        "ilovevocmind",
        validation_alias=AliasChoices("AUTH_SECRET", "auth_secret"),
    )
    auth_token_ttl_hours: int = 24 * 30
    telegram_auth_max_age_seconds: int = 3600 * 24
    extension_link_code_ttl_minutes: int = 10
    bot_internal_key: str = Field(
        "vm_9x2k_a81q_secret_backend_bot_2026",
        validation_alias=AliasChoices("BOT_INTERNAL_KEY", "bot_internal_key"),
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "vocmind"

    @property
    def postgres_admin_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/postgres"
        )

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_timeout_seconds: float = 20.0

    ffmpeg_path: str | None = None

    asr_model: str = "E:/models/whisper-small"
    asr_language: str = "ru"
    asr_device: str = "auto"
    asr_compute_type: str = "auto"

    asr_window_seconds: float = 14.0
    asr_live_step_seconds: float = 1.0
    asr_commit_stability_seconds: float = 1.1
    asr_min_audio_seconds: float = 0.9
    asr_prompt_tail_chars: int = 320
    asr_preview_tail_chars: int = 1000

    audio_sample_rate: int = 16000
    audio_channels: int = 1
    buffer_max_seconds: int = 120
    vad_aggressiveness: int = 3
    vad_frame_ms: int = 30
    vad_min_speech_ms: int = 180
    vad_min_silence_ms: int = 550

    trigger_window_seconds: int = 90
    trigger_cooldown_seconds: int = 25

    triggers_update_every_chunks: int = 10
    protocol_update_every_chunks: int = 15
    protocol_update_every_seconds: int = 30

    # ============================================================
    # Производительность pipeline
    # ============================================================
    # Live-протокол: если True — пересобирает протокол КАЖДЫЕ 30 сек / 15 чанков
    # во время записи. Это даёт пользователю «живые» обновления, но
    # увеличивает нагрузку на Groq (быстрее упираемся в rate limit) и тормозит
    # запись. По умолчанию ВЫКЛ — протокол строится один раз в /stream/finish.
    enable_live_protocol: bool = Field(
        False,
        validation_alias=AliasChoices("ENABLE_LIVE_PROTOCOL", "enable_live_protocol"),
    )

    # LLM-полировка транскрипта: причёсывает грамматику и пунктуацию через
    # Groq на финише. Качество транскрипта заметно лучше, но добавляет
    # 10-20 секунд к финализации и расходует Groq-квоту. Если упираешься в
    # rate limit — выключи (ENABLE_TRANSCRIPT_POLISH=false в .env).
    enable_transcript_polish: bool = Field(
        True,
        validation_alias=AliasChoices("ENABLE_TRANSCRIPT_POLISH", "enable_transcript_polish"),
    )

    # Повторная пере-транскрипция всех PCM-буферов на финише. Раньше делалась
    # всегда, давала +5-10% качества, но добавляла 30-90 секунд на длинных
    # встречах. Теперь на длинных встречах (≥2000 символов транскрипта) и
    # так автоматически пропускается, а здесь общий выключатель.
    enable_final_retranscribe: bool = Field(
        False,
        validation_alias=AliasChoices("ENABLE_FINAL_RETRANSCRIBE", "enable_final_retranscribe"),
    )


settings = Settings()
