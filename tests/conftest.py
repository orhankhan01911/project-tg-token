import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default unit-test env. Integration tests can override per-test."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("MONGO_DB", "tg_token_test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
