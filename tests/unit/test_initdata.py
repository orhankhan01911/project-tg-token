"""Unit tests for `app.auth.initdata.verify_init_data`.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.auth.initdata import Invalid, Verified, verify_init_data

pytestmark = pytest.mark.unit

BOT_TOKEN = "1234567890:ABCDEF_test_token_DO_NOT_USE_real"


def _make_init_data(
    *,
    bot_token: str = BOT_TOKEN,
    user: dict | None = None,
    auth_date: int | None = None,
    extra: dict | None = None,
    bad_hash: bool = False,
) -> str:
    """Build a valid init_data string for tests, with optional tampering."""
    user = user or {"id": 1598057702, "first_name": "Test"}
    if auth_date is None:
        auth_date = int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps(user, separators=(",", ":")),
        "query_id": "AAH123",
    }
    if extra:
        fields.update(extra)
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if bad_hash:
        h = "0" * 64
    fields["hash"] = h
    return urlencode(fields)


def test_valid_init_data_round_trip() -> None:
    s = _make_init_data()
    result = verify_init_data(s, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Verified)
    assert result.user["id"] == 1598057702
    assert result.user["first_name"] == "Test"


def test_tampered_hash_rejected() -> None:
    s = _make_init_data(bad_hash=True)
    result = verify_init_data(s, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "bad_hash"


def test_wrong_bot_token_rejected() -> None:
    s = _make_init_data()
    other = verify_init_data(s, bot_token="some:other-token", max_age_seconds=3600)
    assert isinstance(other, Invalid)
    assert other.reason == "bad_hash"


def test_tampered_user_field_rejected() -> None:
    """If a client tries to swap the user field after signing, the hash
    no longer matches."""
    s = _make_init_data()
    # Replace the user field with a different one. The hash stays the same
    # so it'll mismatch.
    parts = dict(p.split("=", 1) for p in s.split("&"))
    parts["user"] = json.dumps({"id": 999999, "first_name": "Imposter"})
    tampered = urlencode(parts)
    result = verify_init_data(tampered, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "bad_hash"


def test_stale_auth_date_rejected() -> None:
    s = _make_init_data(auth_date=int(time.time()) - 7200)  # 2h old
    result = verify_init_data(s, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "stale_auth_date"


def test_future_auth_date_rejected() -> None:
    s = _make_init_data(auth_date=int(time.time()) + 600)  # 10 min future
    result = verify_init_data(s, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "future_auth_date"


def test_clock_skew_within_60s_accepted() -> None:
    s = _make_init_data(auth_date=int(time.time()) + 30)
    result = verify_init_data(s, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Verified)


def test_missing_hash_rejected() -> None:
    s = _make_init_data()
    parts = dict(p.split("=", 1) for p in s.split("&"))
    parts.pop("hash")
    result = verify_init_data(urlencode(parts), bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "missing_hash"


def test_bad_user_json_rejected() -> None:
    """A signed init_data with a syntactically broken `user` field should
    be flagged distinctly from a hash mismatch — it indicates a bug in
    the client serializer, not an attack."""
    fields = {
        "auth_date": str(int(time.time())),
        "user": "{not json}",
        "query_id": "AAH123",
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = h
    result = verify_init_data(urlencode(fields), bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Invalid)
    assert result.reason == "bad_user_json"


def test_empty_inputs_rejected() -> None:
    r1 = verify_init_data("", bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(r1, Invalid) and r1.reason == "empty_init_data"

    r2 = verify_init_data("auth_date=1&hash=x", bot_token="", max_age_seconds=3600)
    assert isinstance(r2, Invalid) and r2.reason == "missing_bot_token"


def test_field_order_does_not_matter() -> None:
    """Telegram doesn't promise a stable order; we sort before HMAC."""
    s = _make_init_data()
    parts = list(p.split("=", 1) for p in s.split("&"))
    parts.reverse()
    reordered = "&".join("=".join(p) for p in parts)
    result = verify_init_data(reordered, bot_token=BOT_TOKEN, max_age_seconds=3600)
    assert isinstance(result, Verified)
