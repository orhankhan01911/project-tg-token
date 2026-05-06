# tg-token v2

Telegram-native token-gating bot. v2 of the SaaS pattern that
[`tgtokengates.com`](https://tgtokengates.com) shipped — rebuilt on three
modern primitives that the original predates:

1. **`chat_join_request` + approve/decline** — non-holders never join, no
   ban-after-join hot path.
2. **Event-driven re-verify** — Alchemy + Helius webhooks replace the daily
   Purge cron (~$850/mo → ~$120/mo at the v2 reference workload, eviction
   latency 24h → < 2 min).
3. **Free signature auth** — SIWE / SIWS / TON Connect `ton_proof` replace
   self-transfer dust.

Design docs in this folder, in the order they were written:

- [`RE_ANALYSIS.md`](./RE_ANALYSIS.md) — what the original product is + 12
  gaps + fix matrix.
- [`IMPROVED_ARCHITECTURE.md`](./IMPROVED_ARCHITECTURE.md) — composite v2
  component diagram + cost math.
- [`COST_BREAKDOWN.md`](./COST_BREAKDOWN.md) — infra cost by stage (test
  → soft-launch → 1k chats → 10k+ chats).
- [`LEARNING_PATH.md`](./LEARNING_PATH.md) — the six things to actually learn,
  + a 1-week ramp.
- `~/.claude/plans/lets-start-building-it-temporal-hejlsberg.md` — the
  approved multi-session build plan (10 sessions, S0 → S9).

## Quality + testing bar

Production-quality. Testing is non-negotiable: every feature ships with
unit + integration + smoke tests. See the build plan's "Testing —
NON-NEGOTIABLE" section for the exact contract. The `RUNBOOK.md` records
the smoke procedure for every session — it is the spec a new contributor
re-runs to validate behaviour.

## Stack

- **Bot worker** — Python 3.12 + `aiogram` 3.x, long-poll
- **API + webhooks** — FastAPI + uvicorn (added in S2)
- **Persistence** — MongoDB (Motor async driver), Redis for nonces/cache
- **Frontend** — React + Vite + TypeScript Mini App (added in S2)
- **EIP-1271/6492 verifier** — Node sidecar running viem ≥ 2.x (S2)
- **Process supervision** — systemd user services
- **Package mgrs** — `uv` (Python), `pnpm` (Mini App)

## Quick start

```bash
# 1. install python deps
make install

# 2. start local Mongo + Redis
make infra-up

# 3. fill in .env (BOT_TOKEN at minimum)
cp .env.example .env
$EDITOR .env

# 4. run unit tests
make test

# 5. run the bot in the foreground
make dev
```

To run the integration suite (real Telegram Bot API): set `BOT_TOKEN` in
`.env`, then `make test-integration`.

To enable git pre-push gating once:

```bash
git config core.hooksPath tg-token/.githooks
```

## Layout

```
tg-token/
├── app/                   Python package (bot + future API)
│   ├── __main__.py        aiogram polling entrypoint
│   ├── bot.py             handlers (chat_join_request, /health)
│   ├── settings.py        pydantic-settings
│   ├── logging_conf.py    structlog
│   └── gates.py           gate evaluator (Session 0 stub → real in S1+)
├── tests/
│   ├── unit/              pytest -m unit (mocks ok, fast)
│   └── integration/       pytest -m integration (real Bot API, real RPC)
├── webapp/                React Mini App (S2+)
├── infra/
│   ├── docker-compose.yml local Mongo + Redis
│   └── systemd/           user services (do not enable until S0 smoke green)
├── .githooks/pre-push     ruff + pyright + pytest -m unit; refuses red
├── .github/workflows/     CI mirroring pre-push
├── Makefile
├── pyproject.toml         uv-managed
├── README.md (this file)
└── RUNBOOK.md             session-by-session smoke procedures
```

## Status

- ✅ Session 0 — scaffold + hello-world join-request bot
- ✅ Session 1 — Mongo schema + whitelist-backed gate + decline path
- ✅ Session 2 — SIWE end-to-end (FastAPI + viem sidecar + bot DM + React Mini App). Live: 1.088s verify→approve.
- ⏳ Sessions 3–9 — see the build plan
