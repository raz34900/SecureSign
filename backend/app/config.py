from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/securesign.db"
    model_path: str = "models/secure_sign_epoch_50_loss_0.2009_acc_83.48.pth"
    model_version: str = "custom_cnn_v1"
    threshold: float = 0.3999
    pii_enc_key: str = ""      # 32-byte hex; validated at startup, not import time
    pii_index_key: str = ""    # 32-byte hex
    session_ttl_hours: int = 12
    max_upload_mb: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
