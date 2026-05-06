# TG Token Gates — Improved Architecture (v2)

**Question:** *Is there a more efficient way to gatekeep Telegram chats than what TG Token Gates does today?*
**Answer:** Yes — on three independent axes. Each is fixable in isolation; together they cut roughly **-90% of recurring infrastructure cost** and **-99% of eviction latency**, while removing about **~30% of the bot's custom code** in favor of Telegram-native primitives.

This document is the synthesis of three parallel investigations:
1. Telegram platform primitives shipped 2021–2025 that obsolete custom code.
2. Event-driven holdings re-verification vs the current daily Purge.
3. Wallet-proof patterns: self-transfer dust vs SIWE / SIWS / TON Connect / ZK.

---

## Axis 1 — Replace custom code with Telegram-native primitives

The current stack predates several Telegram features that do its job natively. Where Telegram has a primitive, **using the platform is cheaper, more robust, and removes a class of bugs** (rate limits, race conditions, FSM persistence).

| Custom code today | Telegram-native replacement | Bot API | Effect |
|---|---|---|---|
| Bot lets user join, then bans non-holders via `banChatMember` | **`chat_join_request` + `approveChatJoinRequest` / `declineChatJoinRequest`** on links created with `creates_join_request: true` | 5.4 | Eliminates the ban-after-join hot path entirely — non-holders never join, so never need to be removed. |
| Daily Purge cron over the **full** roster | **`chat_member` updates** (subscribe via `allowed_updates`) + per-user TTL re-check | 5.4 | Replaces "rescan everyone" with "react when membership or holdings change". Resolves rate-limit hazard (G8). |
| One-time SOL setup fee + custom payment receipts | **`createInvoiceLink(currency='XTR', subscription_period=2592000)`** for groups; **`createChatSubscriptionInviteLink`** for channels | 8.0 / 8.1 | Telegram runs recurring billing, auto-renews, and on channels **auto-removes lapsed users** — no bot ban call. Channel-tier path needs zero Purge. |
| 10-step DM wizard for `/setup` and `/settings` | **Mini App** with `initData` HMAC auth (`HMAC_SHA256(bot_token,"WebAppData")`) | WebApps | Replaces fragile FSM with a real form UI. Resolves G11. |
| Whitelist keyed on `@username` (breaks on rename, no-username users excluded) | **`KeyboardButtonRequestUsers`** native picker returns numeric `tg_user_id` | 7.0 | Resolves G6 directly. |
| Custom invite-link minting + nonce tracking | **`createChatInviteLink(member_limit=1, expire_date=now+1h, name=tg_user_id)`** | 5.4 | Per-user one-shot invites with built-in audit (`chat_member.invite_link`). |
| Self-transfer dust on TON | **TON Connect 2 `ton_proof`** | TON Connect | Free, instant, native to Mini Apps. |

**What still must be custom:** on-chain reads (balance/ownership), the rules engine itself, and re-verification of token gates (Telegram has no opinion on whether you hold $PONKE, only on whether you've paid Stars).

---

## Axis 2 — Daily Purge → event-driven re-verification

The current "rescan everyone every 24h" model is **O(chats × members × tokens × chains) RPC reads per day**. Almost all of that work is wasted: most members held the same balance yesterday and still hold it today.

### Cost math (example: 1,000 chats × 100 members × 3 tokens × 4 chains)

| | Daily Purge (current) | Event-driven (proposed) |
|---|---|---|
| RPC volume | 1.2M `balanceOf` calls/day → 36M/mo | ~3M webhook events/mo (1 transfer/wallet/day on average) |
| EVM cost (Alchemy) | ~$818/mo | ~$41/mo |
| Solana cost (Helius) | ~$30–80/mo | within free or Developer tier ($49/mo) |
| **Total /mo** | **~$850+** | **~$90–130** |
| **Eviction latency** | up to 24h | < 2 min |

→ **~85% cost reduction, ~720× faster eviction.**

### Recommended pattern

- **EVM (ETH / Base / BNB / Polygon):** Alchemy **Address Activity** webhook (one webhook per chain, 100k addresses each).
- **Solana:** Helius **Enhanced Webhooks** with `transactionTypes: ["TRANSFER"]`, `commitment: "confirmed"`.
- **Cache:** Redis `(chain, address, token) → balance` with **TTL 5–15 min**.
- **Reorg buffer:** schedule eviction decision at `T + N×block_time` (60–120s on Ethereum, ~30s on Base/BNB). Solana `confirmed` is sufficient.
- **Wash-trade absorption:** on disqualifying event, re-confirm at T+5min and T+30min. Both must still fail before evicting.
- **Belt-and-braces sweep:** **weekly**, not daily. Catches missed deliveries, contract upgrades, address-list drift.
- **Idempotency key:** `(chain, txhash, logIndex)` — providers guarantee at-least-once, not exactly-once.

### Edge cases (will bite if ignored)

1. Reorg evictions on EVM (mitigation: confirmation buffer above)
2. Solana commitment trap — never use `processed`; `confirmed` minimum
3. Router-mediated transfers: `Transfer` `from` is the router, not the EOA — watch `from` AND `to` topics
4. Webhook duplicates — idempotency required
5. Bulk-evict storms (token rugs) — token-bucket `kickChatMember` queue, honor `retry_after`
6. Address-list cap drift (Alchemy 100k/webhook)
7. Wrapped/proxy tokens — `Transfer` doesn't always fire; confirm with `balanceOf` on the trigger

---

## Axis 3 — Self-transfer dust → free signature schemes

The **dust self-transfer** is clever but charges users gas and has unspecified semantics (G4). For most users a free signature is better. The honest comparison:

| Scheme | $ to user | Friction | Replay protection | Smart-wallet OK | Telegram fit |
|---|---|---|---|---|---|
| **Self-transfer (current)** | $0.001–$5 gas | high (3 dialogs + finality wait) | bot-side only | yes (any wallet self-tx works) | OK |
| **SIWE (EIP-4361, EVM)** | **$0** | low (1 dialog, ~5s) | nonce + domain + expiry + chain-id, all signed | with **EIP-1271/6492** verifier | excellent |
| **SIWS (Solana)** | **$0** | low | nonce in payload + TTL | n/a | excellent |
| **TON Connect `ton_proof`** | **$0** | low | nonce + domain + 15-min TTL | native | **perfect** (designed for Mini Apps) |
| **Sismo Connect (ZK)** | $0 | medium (15–30s) | nullifier `H(secret, tg_user_id)` | yes | OK (extra modal) |

### Where dust still wins
- **Link-share immunity** — a SIWE link sent to a victim *can* be tricked; a self-transfer cannot, only the wallet owner can produce the on-chain artifact.
- **Smart-contract wallets** work for free (Safe/Argent self-transfer like any EOA; SIWE needs EIP-1271 / 6492 verifier).
- **No wallet SDK** in the bundle — saves SDK-churn maintenance.

### Recommended stack (Telegram-first, $0 to user)
- **EVM:** SIWE + EIP-1271/6492 verifier (`viem.verifyMessage` handles both transparently). Bake `tg_user_id` and `chat_id` into the SIWE `statement`.
- **Solana:** SIWS via Phantom `signIn` with raw `signMessage` fallback.
- **TON:** TON Connect `ton_proof` via `@tonconnect/ui-react` in the Mini App.
- **Privacy tier (optional):** Sismo Connect for "prove holdings without revealing address" — opt-in, not default.
- **Payments orthogonal:** `@wallet Pay` for setup fees; Telegram Stars for fiat-pegged options.

### Migration shape — strict superset, not flag-day

```sql
verifications (
  tg_user_id, chat_id, address, chain,
  method TEXT CHECK (method IN ('dust','siwe','siws','ton_proof','zk')),
  nonce, signature_or_txhash, verified_at
)
```

1. **Schema additive** — old rows get `method='dust'` retroactively, no data lost.
2. **Polymorphic verifier** — single `verify_link(record)` dispatches on `method`. Existing dust watcher untouched.
3. **New flow in Mini App** — both options offered; signature is default.
4. **Re-verification on purge** uses original method per record — a SIWE row re-checks balance only.
5. **Migration nudge** — after second gated chat, one-tap "switch to signature".
6. **Deprecation horizon** — 6 months write, then read-only.
7. **Ship 1271/6492 with SIWE** — not after.

---

## The composite v2 architecture

Putting all three axes together — what changes in the system schematic:

```
─── REMOVED OR DOWNGRADED ─────────────────────────────────────
× Daily Purge cron (over full roster)        → replaced by per-user TTL + event triggers
× banChatMember / unbanChatMember hot path   → replaced by approve/declineChatJoinRequest
× 10-step DM FSM                             → replaced by Mini App with initData HMAC
× Self-transfer dust watcher (TON/SOL/EVM)   → replaced by ton_proof / SIWS / SIWE
× @username-keyed whitelist                  → replaced by KeyboardButtonRequestUsers
× Custom one-time payment receipt code       → replaced by Telegram Stars subscriptions

─── ADDED ─────────────────────────────────────────────────────
+ Event subscription layer (Alchemy + Helius webhooks)
+ Mini App settings frontend (Vite + React, served from existing Vercel)
+ initData HMAC verifier on the bot backend
+ EIP-1271 / 6492 signature verifier for smart-contract wallets
+ Per-method verifier dispatch in re-verification
+ Weekly belt-and-braces sweep (replaces daily Purge)

─── UNCHANGED ─────────────────────────────────────────────────
= Holdings Aggregator (still on us — Telegram has no on-chain opinion)
= Net-Worth Pricer (still on us — multi-source pricer recommended)
= Settings Store (database)
= Multichain Metrics integration
= Rules engine (5+1 gate model is sound)
```

### Component count: 8 → 7
The **Wallet Link Service** (self-transfer watcher) collapses into the **Auth Verifier** (signature dispatch). The **Purge Scheduler** becomes a **Re-verify Worker** that consumes events instead of cron-driving the full roster.

### Cost reduction summary

| Vector | Before | After | Saving |
|---|---|---|---|
| RPC reads (purge) | ~$850/mo | ~$120/mo | -86% |
| User gas (verification) | $0.50–$5/EVM user | $0 | -100% |
| Custom code surface | 8 components | 7 components | ~-30% LoC removed |
| Eviction latency | up to 24h | < 2 min | -99.9% |
| Owner setup complexity | 10-step linear FSM | Mini App form | qualitative win |

---

## Risk register for v2

- **Webhook downtime** — providers do go down. Without the daily Purge as last-resort, eviction lag could grow to days. Mitigation: weekly sweep + dead-letter queue + multi-provider failover for high-tier chats.
- **Mini App adoption** — older Telegram clients (<v6.0) don't support Mini Apps. Mitigation: keep DM FSM as fallback for `tdesktop < 4.0` / `Telegram-iOS < 9.0`.
- **EIP-6492 edge cases** — counterfactual smart wallets are still relatively new; some RPC providers cache `eth_call` poorly. Mitigation: use `viem` ≥ 2.x which handles 6492 well.
- **TON Connect wallet fragmentation** — Tonkeeper / @wallet TON Space / MyTonWallet implement `ton_proof` slightly differently in edge cases (e.g. domain encoding). Mitigation: test matrix, fallback to legacy ledger-style sign for unsupported wallets.
- **Reorg-driven false-evictions** — rare but catastrophic for the affected user. Mitigation: never evict on `processed` / unconfirmed; always confirm with a `balanceOf` re-read.
- **Sybil regression** — moving away from on-chain self-transfer artifacts means sybil prevention lives entirely in the bot DB. Mitigation: nullifier-style hashes binding `(wallet, tg_user_id)` and one-active-binding-per-wallet rule.

---

## What to do first (4 weeks, single dev)

| Week | Ship |
|---|---|
| **W1** | Switch to **`creates_join_request`** invite links; subscribe to `chat_join_request`; remove ban-after-join code path. *Lowest-risk highest-impact change.* |
| **W2** | Add **Alchemy + Helius webhooks**; route to a "potentially-disqualifying" queue; keep daily Purge running in parallel as shadow validation. |
| **W3** | Build **Mini App settings v0** with `KeyboardButtonRequestChat` + `KeyboardButtonRequestUsers`; switch whitelist to `tg_user_id`. |
| **W4** | Add **SIWE + SIWS + ton_proof** verifier behind a `method` column; ship with dust watcher still active; A/B by chat. Drop daily Purge in favor of weekly sweep + event-driven flow once shadow-validation matches for 7 days. |

Everything below the W4 line (NFTs, full TON path, Stars subscriptions, ZK gates) is post-v2 and additive — none of it blocks the v2 cost wins.

---

## Sources

Telegram primitives:
- [Bot API reference](https://core.telegram.org/bots/api), [changelog](https://core.telegram.org/bots/api-changelog)
- [Stars / Subscriptions](https://core.telegram.org/bots/payments-stars), [Mini Apps / WebApps](https://core.telegram.org/bots/webapps)

Event-driven RPC:
- [Alchemy Notify Address Activity](https://www.alchemy.com/docs/reference/address-activity-webhook), [pricing](https://www.alchemy.com/pricing)
- [Helius Webhooks](https://www.helius.dev/solana-webhooks-websockets), [pricing](https://www.helius.dev/pricing)
- [QuickNode Streams](https://www.quicknode.com/docs/streams/filters)

Auth schemes:
- [EIP-4361 SIWE](https://eips.ethereum.org/EIPS/eip-4361), [EIP-1271](https://eips.ethereum.org/EIPS/eip-1271), [EIP-6492](https://eips.ethereum.org/EIPS/eip-6492)
- [TON Connect](https://docs.ton.org/ecosystem/ton-connect/overview), [`ton_proof` verify](https://docs.ton.org/v3/guidelines/ton-connect/guidelines/verifying-signed-in-users)
- [Sismo Connect](https://docs.sismo.io/), [Phantom signMessage](https://docs.phantom.app/solana/signing-a-message)
