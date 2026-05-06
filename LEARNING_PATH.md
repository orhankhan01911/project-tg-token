# What you actually need to learn to build v2

> You already know Python services, aiogram-style bots, React frontends, systemd, and crypto API plumbing. The marginal new knowledge is **six specific things**, and four of them are library calls — not deep theory.

---

## TL;DR

| You already know | You need to learn | You can skip / let a library handle |
|---|---|---|
| Long-poll bot, send/receive | `chat_join_request` + approve/decline flow (1 hour) | Telegram update parsing internals |
| HTTP services in Python | Mini App with `initData` HMAC verify (half a day) | Bot-side session storage choices — use Redis you already run |
| RPC reads + caching | Alchemy webhook setup + Helius webhook setup (2 hours) | Provider failover algorithms |
| Crypto data plumbing | SIWE / SIWS / ton_proof — what they sign and how to verify (1 day) | secp256k1 / ed25519 internals — use `viem` / `@solana/web3.js` / `@tonconnect/sdk` |
| Postgres + Redis | Idempotent eviction queue pattern (2 hours) | Distributed locking — use Redis `SET NX EX` |
| Vue/React | Telegram WebApp SDK quirks (half a day) | Wallet UX — use the wallet's deeplink/SDK |

**Total focused learning: ~3 days of reading + ~1 week of "hello world" builds.** Not weeks of theory.

---

## The 6 things to actually learn

### 1. Telegram join requests + approve/decline (~1 hour)
**Why it matters**: this is the core architectural shift in v2. Master this and you've already got the spine.

**What to learn**:
- `createChatInviteLink(creates_join_request=true)` — issue a link that creates pending requests
- `chat_join_request` update — the event you receive when someone clicks
- `approveChatJoinRequest(chat_id, user_id)` / `declineChatJoinRequest(chat_id, user_id)`
- `allowed_updates` — you must explicitly subscribe to `chat_join_request`, it's off by default

**Read**: [core.telegram.org/bots/api#approvechatjoinrequest](https://core.telegram.org/bots/api#approvechatjoinrequest) and the surrounding `ChatJoinRequest` section.

**Hello-world**: a bot that auto-approves anyone whose Telegram ID is even, declines if odd. ~50 lines of aiogram. Once this works you understand the whole flow.

---

### 2. Telegram Mini Apps + `initData` HMAC verify (~half a day)
**Why it matters**: replaces the 10-step DM wizard. Once you've done it once, every future bot of yours benefits.

**What to learn**:
- Register a Mini App in BotFather (`/newapp` → URL of your hosted page)
- Open it from the bot via `MenuButtonWebApp` or inline button
- The Mini App receives `Telegram.WebApp.initData` as a string
- Backend verify: `HMAC_SHA256(secret_key=HMAC_SHA256("WebAppData", bot_token), check_string)` where `check_string` is the alphabetically-sorted `key=value\n…` of every initData field except `hash`
- The verified `user.id` is the user's Telegram ID — that's your auth

**Read**: [core.telegram.org/bots/webapps#initializing-mini-apps](https://core.telegram.org/bots/webapps) — specifically the "Validating data received via the Mini App" section.

**Hello-world**: a static HTML page that opens from your bot, shows the user's Telegram name, and POSTs to your backend which verifies the HMAC. Once `verify(initData)` returns the right user ID end-to-end, you've got it.

---

### 3. SIWE (EIP-4361) signature verification (~1 day)
**Why it matters**: replaces self-transfer dust. The single most generally useful crypto thing on this list — every dApp uses it.

**What to learn**:
- The SIWE message format (domain, address, nonce, issued-at, expiration, statement, chain-id)
- Server: issue a nonce, store it bound to a session
- Client: wallet calls `personal_sign` over the formatted message
- Server: parse the signed message, recover the address, check it equals the claimed address, check nonce is unused, check domain + expiry
- **EIP-1271 / 6492** — when the address is a smart contract (Safe, Argent, Coinbase Smart Wallet), `ecrecover` doesn't work; you call `isValidSignature` on the contract instead
- **Library**: `siwe` (npm) does the parse+verify for you. `viem.verifyMessage` handles 1271+6492 transparently in one call.

**Read**: [docs.login.xyz/general-information/siwe-overview/eip-4361](https://docs.login.xyz/) → 30 minute read. Then skim the [`siwe` npm README](https://www.npmjs.com/package/siwe).

**Hello-world**: a one-page web app that connects MetaMask, signs a SIWE message issued by your backend, and your backend prints "verified address 0x…". 80 lines.

**Solana equivalent (SIWS)**: same concept, ed25519 sig instead of secp256k1. Use Phantom's `signIn` method which mirrors SIWE. ~same effort once you've done SIWE once.

---

### 4. TON Connect `ton_proof` (~half a day)
**Why it matters**: the only TON-native auth, and TON Connect is the standard way to talk to wallets inside Mini Apps.

**What to learn**:
- The wallet returns `TonProofItemReplySuccess { timestamp, domain, signature, payload }`
- Backend reassembles the message bytes (specific magic prefix + domain + timestamp + payload), hashes per spec, verifies Ed25519 signature against the wallet pubkey
- `@tonconnect/ui-react` handles the client side — drop into Mini App, opens Tonkeeper / @wallet TON Space inline

**Read**: [docs.ton.org/v3/guidelines/ton-connect/guidelines/verifying-signed-in-users](https://docs.ton.org/v3/guidelines/ton-connect/guidelines/verifying-signed-in-users) — has a working backend verify code sample you can copy.

**Hello-world**: drop `@tonconnect/ui-react` into your Mini App, get a `ton_proof` back, send to backend, verify. The official docs example is ~100 lines total.

---

### 5. Alchemy + Helius webhook integration (~2 hours)
**Why it matters**: the entire "event-driven instead of daily Purge" story rests on this. It's mostly point-and-click setup + a webhook handler endpoint.

**What to learn**:
- **Alchemy Address Activity** — UI + REST API to register a webhook for a list of addresses. Payload structure: `event.activity[]` with `fromAddress`, `toAddress`, `asset`, `value`, `hash`. At-least-once delivery → idempotency key on `(chain, hash, logIndex)`.
- **Helius Enhanced Webhooks** — same idea for Solana, with `transactionTypes` filter (`["TRANSFER"]` is what you want). Use `confirmed` commitment, not `processed`.
- The webhook handler endpoint authenticates via a signing secret in headers — verify it before trusting payload.

**Read**: [alchemy.com/docs/reference/address-activity-webhook](https://www.alchemy.com/docs/reference/address-activity-webhook) and [helius.dev → Enhanced Webhooks](https://www.helius.dev/solana-webhooks-websockets). 30 min each.

**Hello-world**: register a webhook that watches your own wallet on Sepolia, send yourself a tx, see it land in your endpoint. Same on Solana devnet.

---

### 6. Idempotent eviction queue pattern (~2 hours)
**Why it matters**: webhooks are at-least-once, blockchains reorg, Telegram has rate limits. Without idempotency you'll evict + re-admit the same user in a loop.

**What to learn**:
- Idempotency key: `(chain, txhash, logIndex)` — store in Redis with TTL (24h is plenty). On webhook receive, `SET NX` — if it returns 0, you've seen this event, drop it.
- Reorg buffer: don't evict immediately on EVM. Schedule the eviction-decision job at `T + N×block_time` (N=12 for Ethereum mainnet, N=5 for Base/BNB). On Solana use `confirmed` commitment and you can act immediately.
- Confirmation re-read: when a webhook says "user transferred their tokens out", **re-read `balanceOf` before evicting**. Catches wash trades and reverted transfers.
- Telegram rate limits: 30 msg/sec global, honor `retry_after` on 429. A token-bucket queue in front of `kickChatMember` / `declineChatJoinRequest` calls.

**Read**: nothing canonical — this is folklore. The pattern is: receive → idempotency-check → schedule confirmation job → on confirmation, re-read balance → if still failing, queue for eviction → token-bucket pace the eviction.

**Hello-world**: a tiny script that consumes a fake webhook stream with deliberate duplicates, writes idempotency keys to Redis, and proves no duplicate processing.

---

## What you can ignore (use libraries)

- **Cryptographic primitives** — never roll your own ECDSA / Ed25519 verify. `viem`, `siwe`, `@solana/web3.js`, `@tonconnect/sdk` all do it correctly.
- **Wallet UX details** — wallets handle their own deeplinks. You request a signature via standard interface, the wallet handles the user prompt.
- **Telegram update parsing** — `aiogram 3` gives you typed handlers; you don't manually parse JSON updates.
- **Block explorer / chain indexer construction** — you're consuming Alchemy/Helius webhooks, not building one.
- **Reorg-detection algorithms** — providers handle this; you just respect their commitment levels.

---

## A 1-week learning sequence

You learn best by building, so pair each day with the smallest possible "prove it works" build.

| Day | Read | Build |
|-----|------|-------|
| **Mon** | Bot API: ChatJoinRequest section | `chat_join_request` → auto-approve-if-even-id bot |
| **Tue** | core.telegram.org/bots/webapps | Static Mini App that round-trips `initData` HMAC verify |
| **Wed** | docs.login.xyz SIWE overview + `siwe` npm | Sign-in-with-Ethereum end-to-end (MetaMask → Express server) |
| **Thu** | docs.ton.org TON Connect verify | TON Connect ton_proof end-to-end inside Wednesday's Mini App |
| **Fri** | Alchemy + Helius webhook docs | Register webhook on testnet, watch your own wallet, log payloads |
| **Sat** | (consolidate) | Stitch the above into a "demo gate": user signs SIWE in Mini App → bot approves a join request → webhook on outbound transfer kicks them |
| **Sun** | rest, or reorg/idempotency edge cases | Add idempotency + reorg buffer to Saturday's demo |

By Sunday night, you have a working spine. Everything else (multichain support, NFT gates, net-worth gates, Stars subscriptions) is the same patterns repeated, not new knowledge.

---

## Order of attack when you actually start building

Once you've done the learning week above, build in this order so each piece can be tested in isolation before the next is wired in:

1. **Bot worker + DB schema** (Postgres) — boring, but it's the bones. Get `verifications` table and `gates` table right first, schema-additive style so the legacy method stays valid.
2. **Join Request Handler with a stub gate** — gate predicate always returns `true`. Validates the Telegram side end-to-end before you bring in chains.
3. **Auth Verifier (SIWE first)** — replace the stub gate with "user has signed SIWE in last 24h". Validates the auth path end-to-end.
4. **Holdings Aggregator (Alchemy only, EVM only)** — replace with "user holds ≥ N tokens of contract X." Now it's a real token gate. Single chain. No webhooks yet — just on-demand reads.
5. **Mini App settings** — owner-side. Replaces the 10-step wizard. Once this is done, you can hand it to a friend to use.
6. **Webhooks + Re-verify Worker** — drop in. Now it's event-driven.
7. **Solana** + **TON** — repeat Auth Verifier and Holdings Aggregator for the other chains.
8. **Net-Worth Pricer** — add as a new gate type. Multi-source pricing = a separate concern that doesn't affect the spine.
9. **Stars subscriptions** — Telegram-managed paid tier. Trivial once everything else works.

NFTs, ZK proofs, and the public webhook API are all post-v2 — don't let them block shipping.

---

## What you'll find genuinely hard (and how to de-risk)

- **`initData` HMAC** — easy to get the byte-encoding wrong. Use the official Python/Node sample code verbatim, then refactor.
- **EIP-1271 verification** — silently breaks on Coinbase Smart Wallet without EIP-6492. Use `viem` ≥ 2.x which handles 6492 transparently — don't try to write the wrapper yourself.
- **Solana commitment levels** — using `processed` will cause spurious kicks. Use `confirmed` minimum.
- **TON wallet variants** — Tonkeeper, @wallet TON Space, MyTonWallet implement `ton_proof` slightly differently in edge cases. Test against at least Tonkeeper + @wallet before shipping.
- **Reorg evictions** — rare but reputation-damaging. The mitigation (confirmation buffer + balance re-read before evicting) is cheap to implement, do it from day one.

---

## You don't need to be an expert in any of this

You need to be **competent enough to debug** when libraries do something unexpected. Read the spec deeply enough to know what *should* happen, then trust the library, then read the library source only when something goes wrong.

The biggest meta-skill: **never roll your own crypto, never roll your own auth verification, never roll your own reorg detection.** Use the canonical libraries. They've been debugged by 10,000 dApps before you.
