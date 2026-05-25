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

    # --- Chains ---
    # Alchemy is preferred for production (rate limits + reliability). Empty
    # = fall back to the chain's free public RPC. Public RPCs throttle hard;
    # fine for v0 testing on Base Sepolia, paid tier required at scale.
    alchemy_api_key: str = ""
    helius_api_key: str = ""

    # --- Dust verification ---
    # Default chain users verify on. Per-chat config in S3+ overrides this.
    # 84532 = Base Sepolia. 8453 = Base. 1 = Mainnet ETH. 11155111 = Sepolia.
    dust_chain_id: int = 84532

    # Base dust amount in wei. The unique amount = base + suffix where the
    # suffix is hash(tg_user_id, chat_id, server_nonce) % 10^7. So total
    # amount stays under ~0.0000000110 ETH (gas-dominated cost).
    dust_base_wei: int = 10_000_000_000  # 1e10 wei = 0.00000001 ETH

    # Minimum confirmations before approving. 5 is conservative for Base
    # Sepolia; mainnet ETH should be 12+. Per-chain table in evm.py is the
    # authoritative source.
    dust_min_confirmations: int = 5

    # How long a pending dust request lives. 1h covers slow wallets +
    # network congestion + the user putting their phone down.
    dust_request_ttl_seconds: int = 3_600

    # How often the watcher polls each pending request's address.
    dust_poll_interval_seconds: int = 30

    # Re-verification window. Once a user verifies, their binding is fresh
    # for this many seconds; after that, they must re-verify on next join.
    verification_ttl_seconds: int = 86_400

    # --- Purge ---
    # UTC hour (0-23) when the daily purge job fires.
    purge_hour_utc: int = Field(default=0, validation_alias="PURGE_HOUR_UTC")

    # If True, log who would be banned but don't actually call ban_chat_member.
    # Useful for auditing before enabling on a live group.
    purge_dry_run: bool = Field(default=False, validation_alias="PURGE_DRY_RUN")

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
