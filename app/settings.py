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

    # --- Mini App + verifier (Session 2+) ---
    # The public URL where the Vite/React Mini App is served. Used both as
    # the WebAppInfo URL the bot sends, and as the SIWE `domain` (per
    # EIP-4361 the domain in the message MUST match the origin the user
    # sees, otherwise the signature can be replayed across sites).
    webapp_url: str = ""
    verifier_url: str = "http://127.0.0.1:8090"

    # Where the FastAPI server listens. Bot worker is a separate process.
    # Port 8001 is taken by project-hypeV2 LLM service on this host.
    api_host: str = "127.0.0.1"
    api_port: int = 8002

    # CORS origins for the Mini App. Comma-separated in env.
    cors_origins: str = ""

    # SIWE nonce TTL in Redis. 5 min is the value most reference SIWE
    # implementations ship with; long enough for a wallet round-trip,
    # short enough that a leaked nonce isn't useful.
    siwe_nonce_ttl_seconds: int = 300

    # Re-verification window. Once a user signs SIWE successfully, the
    # verification row is "fresh" for this many seconds; after that the
    # gate evaluator falls back to declining + re-prompting verification.
    # 24h is the IMPROVED_ARCHITECTURE.md default.
    verification_ttl_seconds: int = 86_400

    # Tolerance for `auth_date` in initData. Telegram's docs say accept
    # initData up to "a few hours" old; we go strict at 1h to limit replay.
    initdata_max_age_seconds: int = 3_600

    @property
    def owner_ids(self) -> set[int]:
        out: set[int] = set()
        for piece in self.owner_tg_ids.replace(",", " ").split():
            try:
                out.add(int(piece))
            except ValueError:
                continue
        return out

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_origins:
            # Default to the webapp URL itself (and localhost dev origins).
            base: list[str] = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
            if self.webapp_url:
                base.append(self.webapp_url)
            return base
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
