"""SIWE (EIP-4361) message handling.

Two responsibilities:
1. **Issue nonces** — random tokens cached in Redis, scoped to
   `(tg_user_id, chat_id)` with a short TTL. The Mini App requests one
   from `/siwe/nonce`, embeds it in the SIWE message, has the wallet
   sign, and posts back.
2. **Verify a signed SIWE message** — parse the message, sanity-check
   domain / chain-id / nonce / expiry / address, then delegate the
   cryptographic check to the Node sidecar (`viem.verifyMessage`) which
   handles plain EOAs, EIP-1271 contract wallets (Safe / Argent), and
   EIP-6492 counterfactual smart wallets transparently in one call.

Why offload to a Node sidecar instead of doing it in Python: the canonical
implementations of EIP-1271 and EIP-6492 live in `viem`. siwe-py's
`SiweMessage.verify` does *only* EOA recovery; it cannot verify a Safe
signature without us re-implementing 1271/6492 ourselves — exactly the
corner-cut the production-quality bar forbids.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.auth.siwe_parse import SiweParseError, parse_siwe
from app.logging_conf import get_logger
from app.redis_store import consume_nonce
from app.settings import settings

log = get_logger(__name__)

NONCE_SCOPE = "siwe"


def make_nonce() -> str:
    # 16 bytes → 22 base64url chars (no padding) → fits the EIP-4361
    # "alphanumeric, ≥8 chars" requirement comfortably.
    return secrets.token_urlsafe(16)


async def issue_siwe_nonce(redis, *, tg_user_id: int, chat_id: int) -> str:  # type: ignore[no-untyped-def]
    """Mint and store a fresh nonce for the (user, chat) pair.

    Overwrites any existing nonce — re-opening the Mini App invalidates
    any previous in-flight signature attempt.
    """
    nonce = make_nonce()
    await redis.set(
        f"nonce:{NONCE_SCOPE}:{tg_user_id}:{chat_id}",
        nonce,
        ex=settings.siwe_nonce_ttl_seconds,
    )
    return nonce


@dataclass(frozen=True)
class VerifyOk:
    address: str
    chain_id: int
    nonce: str


@dataclass(frozen=True)
class VerifyFail:
    reason: str


VerifyResult = VerifyOk | VerifyFail


def _expected_domain() -> str | None:
    if not settings.webapp_url:
        return None
    # SIWE `domain` is the host (+ optional port), no scheme.
    raw = settings.webapp_url.split("://", 1)[-1]
    return raw.rstrip("/")


async def _call_sidecar(
    *, message: str, signature: str, address: str, http: httpx.AsyncClient
) -> tuple[bool, str | None]:
    payload = {"message": message, "signature": signature, "address": address}
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.3, min=0.3, max=2),
        reraise=True,
    ):
        with attempt:
            resp = await http.post(
                f"{settings.verifier_url.rstrip('/')}/verify",
                json=payload,
                timeout=10.0,
            )
    if resp.status_code != 200:
        return False, f"sidecar_status_{resp.status_code}"
    body: dict[str, Any] = resp.json()
    return bool(body.get("ok")), body.get("error")


async def verify_siwe(
    *,
    redis,  # type: ignore[no-untyped-def]
    http: httpx.AsyncClient,
    message: str,
    signature: str,
    expected_address: str,
    tg_user_id: int,
    chat_id: int,
    expected_chain_id: int | None = None,
) -> VerifyResult:
    """Full SIWE verification pipeline.

    Order matters: cheap checks (parse, domain, expiry, nonce) before the
    expensive sidecar HTTP call, so an attacker can't waste our compute
    by sending malformed messages.
    """
    try:
        msg = parse_siwe(message)
    except SiweParseError as e:
        log.warning("siwe_parse_error", err=str(e))
        return VerifyFail(reason=f"parse_error:{e}")

    expected_domain = _expected_domain()
    if expected_domain and msg.domain.lower() != expected_domain.lower():
        return VerifyFail(reason="domain_mismatch")

    if msg.address.lower() != expected_address.lower():
        return VerifyFail(reason="address_mismatch")

    if expected_chain_id is not None and msg.chain_id != expected_chain_id:
        return VerifyFail(reason="chain_id_mismatch")

    # Expiration check. SIWE messages SHOULD include `expirationTime`;
    # we treat its absence as "valid forever" but cap with the nonce TTL
    # below — a message without expiration but with a fresh nonce is
    # still bounded by the 5-minute nonce window.
    if msg.expiration_time:
        try:
            expiry = datetime.fromisoformat(msg.expiration_time.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
        except ValueError:
            return VerifyFail(reason="bad_expiration_time")
        if datetime.now(tz=UTC) > expiry:
            return VerifyFail(reason="expired")

    # Replay protection: nonce must exist in Redis under our scope, must
    # match the message's nonce, and we consume it on use so it can never
    # be replayed even by us.
    consumed = await consume_nonce(
        redis, NONCE_SCOPE, tg_user_id, chat_id, expected=msg.nonce
    )
    if not consumed:
        return VerifyFail(reason="nonce_invalid_or_consumed")

    ok, sidecar_err = await _call_sidecar(
        message=message, signature=signature, address=expected_address, http=http
    )
    if not ok:
        return VerifyFail(reason=sidecar_err or "sidecar_rejected")

    return VerifyOk(address=expected_address, chain_id=msg.chain_id, nonce=msg.nonce)
