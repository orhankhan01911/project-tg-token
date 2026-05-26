import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default unit-test env. Integration tests can override per-test."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("MONGO_DB", "tg_token_test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")

    # Force unit tests to use public RPCs (no Alchemy key) so respx mocks
    # targeting the public RPC URL match. Settings is a module-level singleton
    # loaded at import time, so we patch the instance attribute directly.
    import app.settings as _settings_mod

    monkeypatch.setattr(_settings_mod.settings, "alchemy_api_key", "")


@pytest.fixture(autouse=True)
def _clear_verify_cooldown() -> None:
    """Reset the in-process /verify rate-limit store between tests.

    The store is a module-level dict in app.bot. Without clearing it, a test
    that calls on_verify with a valid address would set a 5-min cooldown for
    that user_id, breaking subsequent tests that use the same user_id.
    """
    import app.bot as _bot_mod

    _bot_mod._verify_cooldown_store.clear()
    yield  # type: ignore[misc]
    _bot_mod._verify_cooldown_store.clear()
