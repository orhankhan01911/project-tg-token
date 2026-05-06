# TG Token Gates — Reverse-Engineering Analysis

**Subject:** [tgtokengates.com](https://tgtokengates.com) + [tg-token-gates.gitbook.io/docs](https://tg-token-gates.gitbook.io/docs)
**Bot:** `@tg_token_gates_bot` · **Demo group:** `t.me/tgtokengatestest`
**Drafted:** 2026-05-05 · multi-agent recon

---

## 1. Product summary

A **non-custodial Telegram-native token-gating SaaS**. Owner pays a one-time SOL fee, configures up to **5 token gates + 1 net-worth gate** per chat across **Solana / Ethereum / Base / BNB**, and a daily **Purge** job removes anyone who no longer satisfies the gates. Wallet ownership is proven by **self-transfer of a small native amount to a bot-derived address** — there is no WalletConnect / SIWE flow.

Differentiator vs. Collab.Land / Guild.xyz: net-worth-aggregation gating across multiple chains via a third-party data layer (`multichainmetrics.com`), and the "Purge" UX as a first-class feature (with custom GIFs).

---

## 2. Inferred system architecture

### 2.1 Components

| # | Component | Responsibility | Inferred stack |
|---|-----------|----------------|----------------|
| 1 | **Telegram bot worker** | Bot API webhook/long-poll; FSM for `/setup`, `/settings`, `/supplycontrol`, `/networth`; button callbacks | Python aiogram or Node telegraf — language unknown; long-poll is most likely (no public webhook hostname) |
| 2 | **Admin manager** | Issues invites, calls `banChatMember`/`unbanChatMember`; tracks bot-admin status per chat | Same worker |
| 3 | **Wallet-link service** | Generates per-user "verification amount" (a tiny dust value), watches chain for the self-transfer, marks wallet linked | Per-chain tx watchers (ETH/Base/BNB log scan, Solana getSignaturesForAddress) |
| 4 | **Holdings aggregator** | Per (wallet, chain) reads native + ERC-20/SPL/BEP-20 balances; resolves "the same token across chains" via Multichain Metrics | Multi-RPC façade; provider unspecified |
| 5 | **Net-worth pricer** | Sums USD across all linked wallets; needed for `/networth` and net-worth gates | Multichain Metrics + likely CoinGecko fallback |
| 6 | **Purge scheduler** | Daily cron; per-chat opt-in; sends summary; manual-purge with 24h cooldown; renders 3 GIFs (Purged / Diamond Hands / Supply Control) | Cron + worker queue |
| 7 | **Payment processor** | Receives one-time SOL setup fee; future "Payment gates" route funds **directly to owner-supplied payout wallets** (one SOL + one shared EVM) | On-chain receive only — no Stripe / Coinbase Commerce / Stars in the bundle |
| 8 | **Settings store** | Per-chat: gates list, whitelist, entry message, command toggles, purge prefs, GIF refs, payout wallets, owner TG ID | Postgres or Mongo (not exposed) |

### 2.2 Public surface (verified from docs)

**Slash commands**
- `/setup` (DM, owner-only) — gate-creation wizard (10 steps)
- `/settings` (DM, owner-only) — manage gates / whitelist / purge / commands / payout wallets
- `/supplycontrol` (in-group, togglable) — % of token supply held by group members
- `/networth` (in-group, togglable) — aggregate USD across linked wallets

**Gate inputs**
- Type: `Token Gate` | `Net Worth Gate` | `Payment Gate` (beta)
- Chain: `Solana | Ethereum | Base | BNB`
- Token: `Native` | `Custom contract` | `Multichain (via multichainmetrics.com)`
- Threshold: token amount or USD value
- Cap: 5 token gates + 1 net-worth gate per chat; user passes any one

**Settings menu** — Manage Gates · Manage Purge (notifications + GIFs + manual run) · Manage Commands · Payment Info (coming soon: SOL + shared EVM payout addresses)

**Tech-stack signals from marketing site**
- Vite/React SPA on Vercel; GA4 (`G-VCN8LL87GD`); reCAPTCHA Enterprise; Formspree (`xrbqwnkd`) for contact
- **No** wallet SDKs in the bundle (no wagmi/RainbowKit/`@solana/web3`/`@tonconnect`) — confirms self-transfer model
- **No** payment SDKs — confirms direct-to-wallet payouts
- **No** dashboard — admin UI is entirely inside Telegram

### 2.3 Reference architecture comparison

| Pattern | Industry standard (Collab.Land / Guild.xyz) | TG Token Gates |
|---------|---------------------------------------------|----------------|
| Wallet proof | EIP-4361 SIWE / EIP-191 / TON Connect — sign nonce | **Self-transfer of dust** to bot-derived address |
| Re-verify cadence | Continuous on event | **Daily batch** ("the Purge") |
| Auth web | Separate HTTPS origin + WalletConnect | **None** — flow is entirely in Telegram DM + chain watching |
| Admin UI | Web dashboard | In-bot menu only |
| Multi-wallet | Standard | Implied (per chain), behavior undocumented |
| NFT support | Standard (Collab.Land/Guild) | **Not supported** |
| TON / Stars | Optional add-on | **Not supported** |

The self-transfer auth model is unusual but elegant: it sidesteps WalletConnect UX friction entirely, but at the cost of (a) a small UX tax (user pays gas), (b) tx-finality timing complexity, (c) inability to verify smart-contract-wallet holders without an EOA equivalent, (d) no hardware-wallet WalletConnect path.

---

## 3. Gaps — where the product is thin

### 3.1 Architectural / correctness gaps

| ID | Gap | Severity | Source |
|----|-----|---------:|--------|
| G1 | **Pre-existing members are invisible** to the bot — purge only sees members who joined after admin grant. Docs admit this; no remediation shipped. | High | docs/the-purge |
| G2 | **No NFT support** (ERC-721/1155). Largest single missed market in token gating. | High | absent from docs |
| G3 | **No TON / Stars** support. Telegram-native chain — adjacent and obvious. | Medium | bundle has no TON Connect strings |
| G4 | **Self-transfer scheme details unspecified**: amount precision, expiry, replay protection, dust-collision when two users get the same nonce-amount, mempool vs finality, dropped-tx retries. | High | docs silent |
| G5 | **Net-worth pricing oracle unspecified.** Single-vendor risk via Multichain Metrics; no documented fallback. | High | docs silent |
| G6 | **Telegram username churn** — whitelist is `@username`-keyed; users without a public username can't be whitelisted; behavior on rename undocumented. Should be `tg_user_id`-keyed. | Medium | docs/manage-gates |
| G7 | **Bot-loses-admin race** on supergroup conversion. Re-add is manual; no detect-and-prompt loop documented. | Medium | docs/setup-bot-permissions |
| G8 | **Telegram Bot API rate limits** during purge of large rooms (30 msg/sec global, 20/min per chat). No documented throttle. | Medium | implementation hazard |
| G9 | **Sybil / wallet-sharing**. A whale can satisfy net-worth gates across many chats; two users can share one wallet. No nonce-bound identity proof. | Medium | architectural |
| G10 | **Setup-fee SOL recipient + amount + refund policy** — completely undocumented (where does the money go?). | Low | trust gap |
| G11 | **No dashboard / web UI** — every admin action is inside a 10-step Telegram FSM. Brittle UX for non-trivial config changes. | Medium | site has no app shell |
| G12 | **No public API / webhooks** for community owners (no programmatic ban events, no audit log export). | Low | nothing in bundle |

### 3.2 Product / GTM gaps

- **Pricing is unpublished** anywhere — friction for prospects.
- **Beta-gated Payment Gate** has no application path or self-serve unlock.
- **"Custom gates" (staked-token / etc.)** is a contact-form-only product — no docs.
- **No POAP / on-chain-activity / NFT-trait** gates — Guild.xyz's bread and butter.
- **No discoverable changelog / blog** — product velocity is opaque.

---

## 4. Can we fix them? — fix matrix

Answer: **all of them**, with varying effort. Group them by where the lift goes:

### 4.1 Cheap wins (days-of-effort)

| Gap | Fix |
|-----|-----|
| G6 | Switch whitelist to `tg_user_id`. Migrate by doing one `@username → id` resolution per existing entry. |
| G7 | On `chat_member` event with `status: kicked|left` for the bot itself, DM the chat owner with re-add instructions; poll `getChatMember(bot)` after first config save. |
| G8 | Token-bucket pacer in the purge worker; honor `retry_after` on 429; concurrency cap per chat. Standard hardening. |
| G10 | Publish a fee/recipient page; add an on-chain receipt link in the bot reply. |

### 4.2 Medium lifts (weeks-of-effort)

| Gap | Fix |
|-----|-----|
| G1 | Two-pronged: (a) on bot-admin-grant, send a self-introduction message in-chat with verify CTA; (b) a "soft-purge" mode that DMs each existing member instead of banning, until they verify. Existing members can also be flushed via a `forwarded_from` audit using channel-message scrape, but the cleanest path is the soft-purge model. |
| G4 | Specify the scheme: `amount_wei = base_dust + (hash(tg_user_id, chat_id, nonce) mod 10^9)`; 30-min TTL; require ≥1 finality on EVM, ≥1 confirmed slot on Solana; persistent mempool watcher with idempotency on `(chain, tx_hash)`; replay-window per `(chain, address)`. Document publicly. |
| G5 | Multi-source pricer: CoinGecko (primary) → on-chain TWAP (fallback) → Multichain Metrics (cross-chain unification only, not pricing); refuse to evaluate net-worth gates if all sources stale > N min; report stale-mode in `/networth`. |
| G9 | Nonce-bind the verification message to `tg_user_id` and reject if the linked wallet is already linked to a different `tg_user_id` (one-active-binding-per-wallet within a chat). |
| G11 | Telegram WebApp ([Mini App](https://core.telegram.org/bots/webapps)) for `/settings` — gives a real form UI inside Telegram without leaving the chat; auth via `initData` HMAC. ~2 weeks for a usable v1. |

### 4.3 Big bets (months-of-effort, but real moat)

| Gap | Fix |
|-----|-----|
| G2 | NFT gating: ERC-721 ownership, ERC-1155 balance ≥ N, **trait gates** (Guild.xyz parity). Requires metadata cache + refresh-on-event. Solana (Metaplex) via Helius DAS API. |
| G3 | TON Connect path: jetton + NFT gating, parallel verify channel. Single biggest TAM unlock — TON has the largest Telegram-native userbase. |
| G12 | Owner-facing API: signed webhooks on member-add / purge events, audit log export, programmatic gate CRUD. Enables third-party integrations and command-bar tools. |
| GTM | Publish pricing; document Payment Gate self-serve path; ship a status page + changelog. |

---

## 5. If we were to reimplement

### 5.1 Stack proposal

- **Bot worker:** Python + `aiogram 3.x` (or Node + `grammY`). Long-poll for v1, webhook for prod.
- **Web verify (only if we move off self-transfer for some flows):** Next.js + `wagmi`/`@solana/wallet-adapter`/`@tonconnect/ui`. Hosted on Vercel.
- **Chain readers:** Alchemy (EVM multi-chain) + Helius (Solana) + TonAPI (TON). All wrapped behind a `ChainReader` interface with cache (Redis 60s TTL on `(chain,address,contract)`).
- **DB:** Postgres for canonical state; Redis for nonces, rate limits, chain-read cache.
- **Scheduler:** APScheduler / BullMQ; one job per chat; idempotent.
- **Admin UI:** Telegram WebApp (Mini App) for in-Telegram dashboard. Optional out-of-band web for power users.
- **Pricing:** CoinGecko Pro key + on-chain TWAP fallback + Multichain Metrics (or replace with our own normalized-token table).

### 5.2 Borrow / fork candidates

- `nessshon/token-access-control-bot` — TON-native, MIT, closest end-to-end shape, good per-participant invite-token model.
- `jill6666/nft-validation-tg-bot` — TS + TON Connect + Vercel KV, MIT; minimal/readable verify flow blueprint.
- `guildxyz/guild-sdk` — best "requirement-type" abstraction in the space; our rules engine should mirror it.
- `ton-connect/demo-telegram-bot` — canonical TON Connect verify snippet.

### 5.3 v0 scope (4 weeks, single dev)

1. Core bot: `/setup` → token-gate-only (ERC-20 + SPL) → daily purge.
2. Wallet link via SIWE + Solana sign-message (skip self-transfer for v0; less complexity).
3. Postgres + Redis + Alchemy + Helius.
4. WebApp settings panel.
5. No NFT, no TON, no net-worth gate, no payment gate. Ship the spine first.

---

## 6. One-page summary

- **What it is:** non-custodial Telegram token-gating SaaS, EVM + Solana, daily-purge enforcement model, novel self-transfer wallet auth.
- **What it is missing:** NFTs · TON · multi-source pricing · existing-member ingestion · Mini App admin UI · public API · pricing transparency.
- **What's defensible if they fix the gaps:** the daily-purge UX with per-chat GIFs is a small but real brand asset; the net-worth-gate primitive is rarer than token-balance gates; the Solana-payment setup-fee model is friendly to crypto-native operators.
- **What we could build instead (or to compete):** same spine + NFT gates + TON gates + Mini App settings + public API. v0 in ~4 weeks.

---

## 7. Open follow-ups (worth a second pass)

- Decompile / inspect the bot's actual responses by joining the demo chat (`t.me/tgtokengatestest`) and tracing observable behavior — confirms RPC providers, finality requirements, exact self-transfer scheme.
- Probe `multichainmetrics.com` API surface — it's a single-vendor dependency.
- Watch the bot's payout addresses on-chain to gauge product traction (volume of setup fees over time).
- Search Telegram for groups that mention `@tg_token_gates_bot` to count active deployments.
