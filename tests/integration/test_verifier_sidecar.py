"""Integration test: real Node sidecar (`make verifier-install && make verifier`)
hit over HTTP from Python httpx, with a pre-computed valid EOA signature.

The signature here was generated once via viem against Anvil's test
account #1 (privkey `0x59c6...8690d` → address
`0x70997970C51812dc3A010C7d01b50e0d17dc79C8`). secp256k1 with deterministic
k (RFC 6979) means the signature is deterministic for a given
(privkey, message) pair, so pinning all three is reliable.

If you change the message string, regenerate the signature:

    cd webapp_verifier && node -e '...' (see SIWE-related node smoke)

Skipped if the sidecar isn't reachable on `VERIFIER_URL`.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.integration

VERIFIER_URL = os.environ.get("VERIFIER_URL", "http://127.0.0.1:8090")

# Anvil account #1 — never use on mainnet, this private key is in every
# Hardhat / Foundry repo on GitHub.
TEST_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
TEST_MESSAGE = "tg-token verifier roundtrip test"
TEST_SIGNATURE = (
    "0x0d956cb9ea1cd87eafc167dfc043f9a924c88c2b3ce25fdf2c235d96d3e16e29"
    "7101730ccb969f10379866c09a43acd3e020aca43bc2ef221771f8269bb6212a1b"
)


@pytest.fixture
async def sidecar():
    async with httpx.AsyncClient(timeout=10.0) as c:
        try:
            r = await c.get(f"{VERIFIER_URL}/health")
        except httpx.ConnectError:
            pytest.skip(f"verifier sidecar not reachable at {VERIFIER_URL}")
        if r.status_code != 200:
            pytest.skip(f"verifier sidecar /health returned {r.status_code}")
        yield c


async def test_health(sidecar) -> None:
    r = await sidecar.get(f"{VERIFIER_URL}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


async def test_valid_eoa_signature_accepted(sidecar) -> None:
    r = await sidecar.post(
        f"{VERIFIER_URL}/verify",
        json={
            "message": TEST_MESSAGE,
            "signature": TEST_SIGNATURE,
            "address": TEST_ADDR,
            "chainId": 84532,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["recovered"].lower() == TEST_ADDR.lower()


async def test_tampered_signature_rejected(sidecar) -> None:
    tampered = TEST_SIGNATURE[:-2] + "ff"
    r = await sidecar.post(
        f"{VERIFIER_URL}/verify",
        json={
            "message": TEST_MESSAGE,
            "signature": tampered,
            "address": TEST_ADDR,
            "chainId": 84532,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "bad_signature"


async def test_wrong_address_rejected(sidecar) -> None:
    """Real signature, real message, but the claimed signer is someone else."""
    other = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    r = await sidecar.post(
        f"{VERIFIER_URL}/verify",
        json={
            "message": TEST_MESSAGE,
            "signature": TEST_SIGNATURE,
            "address": other,
            "chainId": 84532,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False


async def test_missing_fields_400(sidecar) -> None:
    r = await sidecar.post(f"{VERIFIER_URL}/verify", json={"message": "x"})
    assert r.status_code == 400


async def test_unsupported_chain_400(sidecar) -> None:
    r = await sidecar.post(
        f"{VERIFIER_URL}/verify",
        json={
            "message": TEST_MESSAGE,
            "signature": TEST_SIGNATURE,
            "address": TEST_ADDR,
            "chainId": 999_999,
        },
    )
    assert r.status_code == 400
