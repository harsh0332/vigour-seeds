from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Meta WhatsApp configuration
    META_VERIFY_TOKEN: str
    META_WHATSAPP_TOKEN: str
    META_PHONE_NUMBER_ID: str
    META_APP_SECRET: str

    # Supabase configuration
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str

    # AI configuration
    AI_PROVIDER: str = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # Application configuration
    APP_ENV: str = "production"
    LOG_LEVEL: str = "INFO"

    # Load from environment variables
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
