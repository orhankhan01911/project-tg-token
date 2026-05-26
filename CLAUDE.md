# CLAUDE.md — tg-token project orientation

## What this project is

Telegram-native token-gating SaaS (v2). Bot worker in Python/aiogram 3,
FastAPI for webhooks + Mini App API, MongoDB + Redis, React/Vite Mini App.
Full architecture in `IMPROVED_ARCHITECTURE.md`. Build plan at
`~/.claude/plans/lets-start-building-it-temporal-hejlsberg.md` (S0–S9).

## Infrastructure: self-hosted Hetzner runner (NOT GitHub-hosted)

All CI/CD runs on the user's own Hetzner server via a self-hosted GitHub
Actions runner (`runs-on: [self-hosted, hetzner]`). GitHub-hosted runners
are not used — the free-tier minutes limit was hit. Every workflow in
`.github/workflows/` assumes it is running on that server.

The Hetzner runner user lacks passwordless sudo, so Docker operations and
root-level actions are done via SSH to `root@127.0.0.1` using the
`SSH_PRIVATE_KEY` / `SSH_USER` repository secrets.

## CI/CD notifications → WhatsApp "CI/CD tg token" group

Notifications go to a WhatsApp group named **"CI/CD tg token"** via the
WA sidecar that runs on the Hetzner server at `127.0.0.1:8787`.

The sidecar exposes `POST /send` with `{ to, body }`. The `to` field
accepts a group name (case-insensitive substring match) or a raw WA group
id (`@g.us`). Since the runner IS the Hetzner server, `127.0.0.1:8787`
is always reachable from within a workflow step.

Example notification curl (from a workflow step):
```bash
MSG="🚀 *tg-token* deployed — bot is live"
curl -sf -X POST http://127.0.0.1:8787/send \
  -H "Content-Type: application/json" \
  -d "{\"to\":\"CI/CD tg token\",\"body\":$(echo "$MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" || true
```

**Never use Telegram API calls for CI/CD notifications in this repo.**
The WA sidecar is the single notification channel for this project.

## Workflows

| File | Trigger | What it does |
|---|---|---|
| `deploy-tg-token.yml` | `workflow_dispatch` | Clone/pull repo, build Docker image, start compose, verify bot alive, WA-notify |
| `check-tg-token-logs.yml` | `workflow_dispatch` | Fetch container status + last 80 log lines via root SSH |
| `tg-token-flip-mainnet.yml` | `workflow_dispatch` | Set DUST_CHAIN_ID=8453 in .env.prod and restart bot, WA-notify |

These workflows were previously in `orhankhan01911/project-btcV2` —
they were moved here on 2026-05-26 so that pushes to btcV2 no longer
interfere with tg-token deploys and vice versa.

## Repository secrets required

| Secret | Used by |
|---|---|
| `SSH_PRIVATE_KEY` | All workflows — root SSH to 127.0.0.1 |
| `SSH_USER` | All workflows — typically `root` |
| `TG_TOKEN_BOT_TOKEN` | deploy-tg-token — written to .env.prod |
| `TG_TOKEN_OWNER_ID` | deploy-tg-token — written to .env.prod |
| `TG_TOKEN_ALCHEMY_KEY` | deploy-tg-token — written to .env.prod |
| `TG_TOKEN_HELIUS_KEY` | deploy-tg-token — written to .env.prod |

These secrets must be set in `orhankhan01911/project-tg-token` repo
settings → Secrets and variables → Actions.

## Docker / production stack

Deploy uses `infra/docker-compose.prod.yml`. The bot container is named
`tg-token-bot`. Startup is verified by grepping logs for `bot_starting`.
The deploy workflow clones to `$HOME/tg-token` on the Hetzner server and
runs docker ops as root via SSH.

## Development

```bash
make install      # uv sync
make infra-up     # local Mongo + Redis via docker compose
cp .env.example .env && $EDITOR .env   # set BOT_TOKEN at minimum
make test         # unit suite (no network)
make dev          # aiogram long-poll in foreground
```

## Quality bar

Testing is non-negotiable. Every feature ships with unit + integration +
smoke tests. See `RUNBOOK.md` for the session-by-session smoke procedure.
The `.githooks/pre-push` hook runs ruff + pyright + `pytest -m unit` and
blocks on red.

## What not to do

- Never add Telegram Bot API calls for notifications — WA sidecar only.
- Never add workflows back to the btcV2 repo for this project.
- Never commit `.env.prod` or any file containing bot tokens / API keys.
- Never use GitHub-hosted runners (`runs-on: ubuntu-latest`) — the
  account has no remaining free-tier minutes.
