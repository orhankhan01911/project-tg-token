# TG Token Gates v2 — Cost Breakdown

Numbers are USD/month, conservative (round up where ambiguous), and assume you self-host where it's cheap. All providers verified against current public pricing as of 2026-05.

---

## TL;DR

| Stage | Users / chats | Monthly cost |
|---|---|---|
| **Test phase** (dev + staging on testnets) | you + a few testers | **~$5–7/month** |
| **Soft-launch** | <100 chats, <10k users | **~$15–35/month** |
| **Medium production** (the example workload) | 1,000 chats, 100k users | **~$170–300/month** |
| **Large production** | 10,000 chats, 1M+ users | **~$1,200–2,700/month** |

Telegram Bot API is free. Telegram Stars subscriptions are *revenue*, not cost.

---

## Stage 1 — Test phase (dev/staging on testnets)

You can build the entire spine without paying anyone except a VPS host. Everything below is on free tiers.

| Line item | Provider | Tier | Cost |
|---|---|---|---|
| Bot worker host | Hetzner CX11 / DigitalOcean / Oracle Free | smallest | $0–$5 |
| Postgres + Redis (self-hosted on same VPS) | Docker Compose | — | $0 |
| EVM RPC + webhooks | Alchemy | Free (30M CU/mo, 5 webhooks) | $0 |
| Solana RPC + webhooks | Helius | Free (1M credits/mo, 1 webhook) | $0 |
| Mini App hosting | Vercel | Hobby | $0 |
| Domain | Cloudflare Registrar (`.com`) | — | ~$1 (amortized $12/yr) |
| TLS | Let's Encrypt or Cloudflare | — | $0 |
| Error tracking | Sentry | Free (5k events/mo) | $0 |
| Uptime monitoring | BetterStack / UptimeRobot | Free | $0 |
| Test ETH / Base / BNB / SOL | Public faucets | — | $0 |
| Telegram Bot API | Telegram | — | $0 |

**Total: ~$5–7/month** (realistically $1 if you use Oracle Free).

You can run the entire learning-week plan on this. No reason to spend more until real users show up.

---

## Stage 2 — Soft-launch (≤100 chats, ≤10k members)

You're on mainnet, real users, but small. Almost everything still fits in free tiers.

| Line item | Provider | Tier | Cost |
|---|---|---|---|
| Bot worker host | Hetzner CX22 (4GB) | — | $5 |
| Postgres (managed) | Supabase or Neon | Free | $0 |
| Redis | Upstash | Free (500k commands/mo) | $0 |
| EVM webhooks | Alchemy | Free → first paid tier | $0–$15 |
| Solana webhooks | Helius | Free → Developer if exceeded | $0–$49 |
| Mini App hosting | Vercel | Hobby | $0 |
| Domain | Cloudflare | — | $1 |
| Sentry + uptime | Free tiers | — | $0 |
| Pricing source (`/networth` only) | CoinGecko | Free / Demo (10–30 calls/min) | $0 |

**Total: ~$15–35/month**

The variable here is whether Helius free tier carries you. 1M credits = roughly 1M webhook events. If your watched-wallet set is small and dormant, free tier is fine. If active, Developer tier ($49/mo) covers you.

---

## Stage 3 — Medium production (1,000 chats × 100 members × 3 tokens × 4 chains)

This is the workload from the v2 cost analysis. Everything you'd need is genuinely paid here.

| Line item | Provider | Plan | Cost |
|---|---|---|---|
| Bot worker host | Hetzner CX32 (8GB) or DO Premium Droplet | — | $20 |
| Postgres managed | Supabase Pro | 8 GB | $25 |
| Redis managed | Upstash Pay-as-you-go | ~10M commands/mo | $10 |
| EVM webhooks (Alchemy) | Address Activity, ~2.25M events/mo | PAYG | ~$41 |
| Solana webhooks (Helius) | Enhanced Webhooks, ~750k events/mo | Developer | $49 |
| Mini App hosting + serverless | Vercel Pro | — | $20 |
| Pricing source | CoinGecko Pro (or free if low call rate) | Analyst | $0–$129 |
| Domain + DNS | Cloudflare | — | $1 |
| Error tracking | Sentry Team | 50k events/mo | $26 |
| Uptime monitoring | BetterStack | Team | $0–$24 |

**Total without CoinGecko Pro: ~$170–215/month**
**Total with CoinGecko Pro: ~$295–325/month**

For comparison: v1's daily Purge alone would cost ~$850/mo just on RPC reads at this scale. **v2 is roughly 1/4 to 1/5 the v1 cost.**

---

## Stage 4 — Large production (10,000 chats, 1M+ members)

At this scale you're scaling individual line items, not adding new ones. Numbers become approximate.

| Line item | Cost band |
|---|---|
| Bot worker host (cluster: 2-3 instances behind a queue) | $80–$150 |
| Postgres managed (Supabase Team / Neon Scale) | $100–$200 |
| Redis (Upstash Pro / Redis Cloud) | $50–$100 |
| Alchemy webhooks (sharded across multiple webhooks, address-cap creep) | $400–$800 |
| Helius webhooks (Business tier) | $200–$500 |
| Vercel Pro / Enterprise | $200–$500 |
| CoinGecko Pro / Enterprise | $129–$499 |
| Sentry Business + monitoring | $80–$150 |

**Total: ~$1,240–$2,900/month**

At this scale it's worth re-evaluating: self-host an Alchemy alternative (Erigon node + Eigenphi-style indexer), use Quicknode Streams for some chains, or sign Alchemy Enterprise pricing. But that's a decision for when you're actually there.

---

## What's *not* in these numbers

- **Telegram Bot API** — free at every scale
- **Telegram Stars** — Telegram takes a cut on payouts, but Stars are *revenue* to you, not a cost
- **TON RPC** — free public endpoints (toncenter, tonapi free tier) are fine for small/medium scale; pay only at large scale
- **Wallet SDKs** — `viem`, `siwe`, `@solana/web3.js`, `@tonconnect/sdk` are all free open-source
- **Salaries** — assumes you're the dev. If hiring, that dwarfs everything above.
- **Marketing / legal** — out of scope for infra costs

---

## Hidden gotchas that bend cost curves

1. **Alchemy CU pricing is per byte of payload.** A webhook delivering a long log payload costs more than a short one. Estimate conservatively (~40 CU/event).
2. **Helius credit cost spikes on webhook *edits*.** Each `editWebhook` call burns 100 credits regardless of address-list change size. Batch your address updates — don't call edit per user.
3. **Postgres connections** — Supabase Pro is 60 connections; if you have multiple bot workers each opening 20 idle connections, you'll hit the cap. Use PgBouncer or `asyncpg` pool sizing.
4. **Redis bandwidth on Upstash** — pay-as-you-go bills per request. A chatty cache layer (uncached `getChatMember` polling) can run up the bill faster than the data warrants. Set TTLs aggressively.
5. **CoinGecko free tier rate-limits** at 10–30 req/min. Net-worth gates fired on every join can blow this within an hour. Either cache prices for 5 min or buy Pro.
6. **Sentry "events" counts include performance traces.** Easy to overshoot 50k/mo without realizing. Disable performance tracing on the bot worker; keep it on the Mini App only.

---

## Cost-control levers if it gets expensive

- **Increase webhook coalescing window** (5 min → 15 min before re-evaluating) — reduces Alchemy/Helius event count
- **Lengthen Redis cache TTL** on `(chain, address, token)` to 30 min — most balances don't change that fast
- **Skip net-worth re-eval below threshold** — if user is well above the gate threshold, don't re-price every event
- **Move pricing to on-chain TWAP** for the most-watched tokens — eliminates CoinGecko dependency entirely
- **Use Supabase Free + self-host Redis** at small/medium scale — saves $35/mo with negligible reliability cost
- **Quicknode Streams instead of Alchemy** at very large scale — Streams charges per-block-processed (cheap if you have many active addresses, expensive if sparse)

---

## Bottom line

| If you are… | Pay roughly |
|---|---|
| Building / testing | **$5–7/mo** |
| First 100 customers | **$15–35/mo** |
| Real product (1k chats) | **$200–300/mo** |
| Scaled (10k+ chats) | **$1.2–2.7k/mo** |

**Test cheap → ship → only scale costs after revenue is real.** Most of this stack has free tiers good enough to validate the idea before you spend a cent.
