from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", validation_alias="BOT_TOKEN")
    owner_tg_ids: str = Field(default="", validation_alias="OWNER_TG_IDS")

    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "tg_token"

    redis_url: str = "redis://127.0.0.1:6379/0"

    sentry_dsn: str = ""
    log_level: str = "INFO"

    alchemy_api_key: str = ""
    alchemy_webhook_signing_key: str = ""
    helius_api_key: str = ""
    helius_webhook_signing_key: str = ""
    ton_api_key: str = ""

    webapp_url: str = ""
    verifier_url: str = "http://127.0.0.1:8090"

    @property
    def owner_ids(self) -> set[int]:
        out: set[int] = set()
        for piece in self.owner_tg_ids.replace(",", " ").split():
            try:
                out.add(int(piece))
            except ValueError:
                continue
        return out


settings = Settings()
