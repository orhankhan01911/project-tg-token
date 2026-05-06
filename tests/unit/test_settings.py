import pytest

from app.settings import Settings

pytestmark = pytest.mark.unit


def test_owner_ids_parses_comma_and_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_TG_IDS", "111, 222 333")
    s = Settings()
    assert s.owner_ids == {111, 222, 333}


def test_owner_ids_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_TG_IDS", "")
    s = Settings()
    assert s.owner_ids == set()


def test_owner_ids_skips_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_TG_IDS", "111, foo, 222")
    s = Settings()
    assert s.owner_ids == {111, 222}


def test_defaults_are_localhost() -> None:
    s = Settings()
    assert s.mongo_uri.startswith("mongodb://127.0.0.1")
    assert s.redis_url.startswith("redis://127.0.0.1")
    assert s.log_level == "WARNING"  # set by conftest autouse fixture
