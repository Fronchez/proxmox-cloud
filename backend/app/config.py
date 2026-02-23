from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
    )

    PROXMOX_HOST: str
    PROXMOX_NODE: str
    PROXMOX_TOKEN_ID: str
    PROXMOX_TOKEN_SECRET: str
    DATABASE_URL: str
    SECRET_KEY: str
    TELEGRAM_TOKEN: str
    ADMIN_TELEGRAM_ID: str


settings = Settings()
