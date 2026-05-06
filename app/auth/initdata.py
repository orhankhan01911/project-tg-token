"""Telegram Mini App `initData` HMAC verification.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

The Mini App receives `Telegram.WebApp.initData` as a urlencoded string,
posts it to our backend, and we authenticate the user by:

1. Parse the urlencoded pairs.
2. Pop `hash` (the value Telegram signed). All other fields go into the
   data-check string.
3. Build `data_check_string = "\\n".join(f"{k}={v}" for k,v in sorted(pairs))`.
4. Derive `secret_key = HMAC_SHA256(key="WebAppData", data=bot_token)`.
5. Compute `expected = HMAC_SHA256(key=secret_key, data=data_check_string)`
   in hex.
6. Compare with `hmac.compare_digest`.
7. Reject if `auth_date` is older than the configured tolerance.

Edge cases this module handles:
- Missing `hash` field → invalid (not "missing", same outcome).
- Unsorted pairs → we sort, never trust client order.
- `auth_date` not an int → invalid.
- Stale auth_date → invalid (closes a replay window).
- The `user` field is JSON in initData; we expose the parsed dict via
  `verified.user`, since callers always need the tg_user_id.

We never raise on ill-formed input — we return an `Invalid` result. The
caller (FastAPI route) maps it to HTTP 401.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class Verified:
    fields: dict[str, str]
    user: dict[str, Any] = field(default_factory=dict)
    auth_date: int = 0


@dataclass(frozen=True)
class Invalid:
    reason: str


VerifyResult = Verified | Invalid


def verify_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: float | None = None,
) -> VerifyResult:
    if not init_data:
        return Invalid("empty_init_data")
    if not bot_token:
        return Invalid("missing_bot_token")

    # Telegram urlencodes everything; keep_blank_values=True so we don't
    # silently drop a key whose value is empty (would otherwise change the
    # data-check string and look like tampering).
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    fields_map: dict[str, str] = dict(pairs)

    received_hash = fields_map.pop("hash", None)
    if not received_hash:
        return Invalid("missing_hash")

    # `signature` (added in Bot API 8.0) participates in the same scheme
    # as `hash` for third-party Mini App auth — for our own bot's auth we
    # compute the data-check string from everything else, including any
    # `signature` field if present. The Telegram docs explicitly include
    # all non-hash fields. So no extra exclusion here.

    data_check_string = "\n".join(f"{k}={fields_map[k]}" for k in sorted(fields_map))

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return Invalid("bad_hash")

    auth_date_raw = fields_map.get("auth_date", "")
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return Invalid("bad_auth_date")

    current = now if now is not None else time.time()
    if current - auth_date > max_age_seconds:
        return Invalid("stale_auth_date")
    if auth_date - current > 60:
        # auth_date in the future is a clock-skew or tampering signal;
        # tolerate up to 1 minute of clock drift between Telegram and us.
        return Invalid("future_auth_date")

    user_raw = fields_map.get("user", "")
    user_obj: dict[str, Any] = {}
    if user_raw:
        try:
            user_obj = json.loads(user_raw)
        except json.JSONDecodeError:
            return Invalid("bad_user_json")

    return Verified(fields=fields_map, user=user_obj, auth_date=auth_date)
