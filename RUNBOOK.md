# tg-token RUNBOOK

End-to-end smoke procedures, session by session. Every session appends its
"Done when" walk-through here. A new contributor must be able to re-run any
session's smoke from this file with no other context.

This file is the **smoke spec**. It is part of the testing contract — alongside
unit tests (`pytest -m unit`) and integration tests (`pytest -m integration`).

---

## Session 0 — Scaffold + auto-approve join-request bot

**Goal:** prove the spine works. Bot reacts to a real `chat_join_request`,
approves the user, and the user lands inside the test group.

### Prereqs (one-time)

1. Two real Telegram accounts: your main + a burner (sign up via web/another
   device). Both will be needed for every session's smoke.
2. A throwaway test supergroup that *you* own. Telegram requires
   join-by-request links to come from supergroups (not basic groups).
3. Docker + docker compose installed and the daemon running.
4. Python 3.12 available on `$PATH` (`python3.12 --version`).
5. `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

### Step 1 — Register the dev bot

1. Open Telegram on your main account, DM `@BotFather`.
2. `/newbot` → name `tg-token v2 dev`, username `<something>_dev_bot` (must
   end in `_bot`).
3. Copy the token.
4. `/setjoingroups` → enable for your bot.
5. `/setprivacy` → **Disable** (otherwise the bot only sees commands, not
   group events).

### Step 2 — Add the bot to the test group as admin

1. Open the test group on your main account.
2. Add `@<your_bot_username>` as a member.
3. Promote it to admin with at least: *Invite users via link* and *Restrict
   members*. (We need both to issue `creates_join_request` invite links and
   to decline/kick later.)

### Step 3 — Configure + start the bot

```bash
cd ~/Desktop/claude_folder/claude/tg-token
cp .env.example .env
# Edit .env:
#   BOT_TOKEN=<token from BotFather>
#   OWNER_TG_IDS=<your main account user id, from @userinfobot>

make install
make infra-up      # Mongo + Redis (Mongo is unused in S0 but health-checked)
make test          # unit suite must be green
make dev           # foreground; logs to stdout
```

You should see structured log lines including `bot_starting allowed_updates=[...]`.

### Step 4 — Real Bot API integration test

In a second terminal:

```bash
cd ~/Desktop/claude_folder/claude/tg-token
.venv/bin/pytest -q -m integration
```

Should pass with `getMe()` round-trip.

### Step 5 — Live smoke: join-request flow

1. From your **main** account (the bot's admin), in the test group: tap
   group title → *Invite Links* → *Create New Link* → enable **Request
   admin approval** → save.
2. Copy the link.
3. Switch to the **burner** account and open the link. The burner sees
   *Request to join* — tap it.
4. Watch the bot's stdout. You should see:
   - `join_request_received chat_id=… tg_user_id=…`
   - `approved reason='stub: always-approve'`
5. The burner account is now inside the group.

### Done criteria

- ✅ unit suite green (`make test`)
- ✅ integration suite green when `BOT_TOKEN` is set
- ✅ real burner account joins via auto-approve in under ~5s
- ✅ structured logs show approve path

If any step fails, fix root cause — no skipping. Update this RUNBOOK if a
real-world step needed wording you didn't have.

### Recovery: a join request landed but approve/decline failed

Telegram's edge will occasionally reset connections (`Connection reset by peer`,
`ClientConnectorError`). The handler retries up to 5× with exponential backoff
(0.5s → 8s) — covered by `tests/unit/test_bot_handler.py` — but if all 5
attempts fail, the request stays in *Pending* state. Manual recovery:

```bash
set -a; source .env; set +a
.venv/bin/python <<'PY'
import asyncio, os
from aiogram import Bot
async def go():
    b = Bot(token=os.environ['BOT_TOKEN'])
    try:
        # Substitute the real chat_id + user_id from the bot log line:
        #   join_request_received chat_id=… tg_user_id=…
        await b.approve_chat_join_request(chat_id=-5202535300, user_id=1250618494)
        # or: await b.decline_chat_join_request(chat_id=…, user_id=…)
    finally:
        await b.session.close()
asyncio.run(go())
PY
```

If the recovery script also fails, it's a Telegram-side outage or a network
problem on your host — check the api.telegram.org status and your DNS/IPv6
config before changing code.

---

## Session 1 — Mongo schema + whitelist gate + decline path

**Goal:** the gate evaluator now reads from Mongo. Auto-approve still
works for the chat owner and explicit whitelist entries; everyone else
gets *declined* with reason `not_whitelisted`. Joining an unregistered
chat is declined with `chat_not_registered`.

### Prereqs

- Session 0 done (bot can approve in the test group).
- Mongo + Redis running via `make infra-up`.
- The bot worker restarted on the Session-1 build (`make dev`). Look for
  a startup line `indexes_ensured db=tg_token` — that proves
  `ensure_indexes()` ran and the bot is reading from the live db.

### Step 1 — Register a chat (one-shot)

The bot ignores chats Mongo doesn't know about. Seed the test group:

```bash
set -a; source .env; set +a
.venv/bin/python <<'PY'
import asyncio
from app.db import make_client, get_db, ensure_indexes
from app.models import Chat

async def go():
    client = make_client()
    db = get_db(client)
    await ensure_indexes(db)
    chat = Chat(_id=-5202535300, owner_tg_id=1598057702)  # ← edit me
    await db.chats.update_one(
        {"_id": chat.chat_id},
        {"$set": chat.model_dump(by_alias=True, exclude={"chat_id"}) | {"_id": chat.chat_id}},
        upsert=True,
    )
    client.close()

asyncio.run(go())
PY
```

Substitute the real chat_id (negative integer; check with `getChat` from
the bot logs) and `owner_tg_id` (your main TG id from `@userinfobot`).

### Step 2 — Decline path (live)

1. Have the burner account leave the test group.
2. Send burner the invite link from S0.
3. Burner taps *Request to join*.
4. Bot logs:
   - `join_request_received chat_id=… tg_user_id=…`
   - `declined reason='not_whitelisted'`
5. The burner's join request should disappear without the bot adding them.

### Step 3 — Whitelist + approve path (live)

Add the burner to the whitelist:

```bash
set -a; source .env; set +a
.venv/bin/python <<'PY'
import asyncio
from app.db import make_client, get_db
from app.models import WhitelistEntry

BURNER_TG_ID = 8626694223  # ← edit me

async def go():
    client = make_client()
    db = get_db(client)
    entry = WhitelistEntry(chat_id=-5202535300, tg_user_id=BURNER_TG_ID)
    await db.whitelist.update_one(
        {"chat_id": entry.chat_id, "tg_user_id": entry.tg_user_id},
        {"$set": entry.model_dump()},
        upsert=True,
    )
    print("ok")
    client.close()

asyncio.run(go())
PY
```

Then have the burner tap the invite link again. Bot logs:
- `join_request_received …`
- `approved reason='whitelist'`

### Done criteria

- ✅ unit suite green (`make test` — 21 passed at S1)
- ✅ integration suite green (`pytest -m integration` — 6 passed at S1)
- ✅ live: registered chat + non-whitelisted user → declined
- ✅ live: registered chat + whitelisted user → approved
- ✅ live: unregistered chat → declined (try a totally separate test group)

### Mongo inspection cheat sheet

```bash
docker exec -it tg-token-mongo mongosh tg_token --quiet
# Inside mongosh:
db.chats.find().pretty()
db.whitelist.find({chat_id: -5202535300})
db.getCollectionInfos()  # confirms indexes were created
db.whitelist.getIndexes()
```

---

## Session 2 — SIWE end-to-end (auth spine)

**Goal:** a stranger to a registered chat is no longer auto-declined.
The bot DMs them a Mini App "Verify your wallet" button. The Mini App
issues a SIWE message, the user signs it with their wallet, the backend
verifies the signature via the Node sidecar (handles EOA + EIP-1271 +
EIP-6492 transparently), persists a `verifications` row, and approves
the still-pending join request.

### Architecture additions

- `app/api.py` — FastAPI server (`make api` → uvicorn on 127.0.0.1:8001)
- `app/auth/initdata.py` — Telegram WebApp `initData` HMAC verifier
- `app/auth/siwe.py` + `app/auth/siwe_parse.py` — SIWE pipeline (parse →
  domain/address/expiry/nonce → call sidecar)
- `app/redis_store.py` — async Redis nonce store (SET NX EX + Lua
  compare-and-delete for one-shot consume)
- `webapp_verifier/` — Node sidecar (Express + viem ≥ 2.x) on
  127.0.0.1:8090. `make verifier-install && make verifier`
- `webapp/` — React Mini App (next sub-session)

Three processes total (each runs as its own systemd unit in
`infra/systemd/`):

| Service | Port | Purpose |
|---|---|---|
| `tg-token-bot` | — | Long-poll worker; receives `chat_join_request` |
| `tg-token-api` | 8002 | Mini App backend + webhook receivers (S5) |
| `tg-token-verifier` | 8090 | viem signature verifier |

> Port 8001 is reserved by project-hypeV2's LLM service — don't touch it.

### Prereqs

- S0 + S1 done.
- Node 18+ on `$PATH` for the verifier (`node --version` ≥ v18).
- A public HTTPS URL for the Mini App. For dev use a tunnel:
  ```
  cloudflared tunnel --url http://localhost:5173
  ```
  Set `WEBAPP_URL=https://<random>.trycloudflare.com` in `.env`.

### Step 1 — Start the verifier sidecar

```bash
make verifier-install      # one-time: npm install
make verifier              # foreground, port 8090
```

Verify health:
```bash
curl -s http://127.0.0.1:8090/health
```

### Step 2 — Start the FastAPI server

```bash
make api                   # foreground, port 8001
curl -s http://127.0.0.1:8001/health
```

### Step 3 — Start the bot (separate terminal)

```bash
make dev
```

Logs should include `bot_starting … allowed_updates=[…] mongo_db=tg_token`
just like S1.

### Step 4 — Live smoke

The S1 burner whitelist entry will short-circuit the SIWE flow. To test
S2's verify path, delete it first:

```bash
set -a; source .env; set +a
.venv/bin/python <<'PY'
import asyncio
from app.db import make_client, get_db

async def go():
    c = make_client()
    db = get_db(c)
    res = await db.whitelist.delete_one({"chat_id": -5202535300, "tg_user_id": 8626694223})
    print(f"deleted: {res.deleted_count}")
    c.close()
asyncio.run(go())
PY
```

Then:

1. Burner leaves the test group (or: from a fresh second account).
2. **Burner DMs `@tg_token21_bot` `/start` first** — Telegram blocks bots
   from initiating DMs without this.
3. Burner clicks the invite link → *Request to join* → tap.
4. Bot logs:
   - `join_request_received chat_id=-5202535300 tg_user_id=…`
   - `verify_dm_sent reason=requires_siwe_verification`
5. Burner receives a DM with a **Verify your wallet** button.
6. Burner taps the button → Mini App opens → wallet connect → sign SIWE
   → success message.
7. Backend logs:
   - `siwe_nonce_issued tg_user_id=… chat_id=…`
   - `siwe_verify_received …`
   - `siwe_verify_ok approved_join=true`
8. Burner is now in the group.

### Done criteria

- ✅ unit suite green (`make test` — 56+ tests)
- ✅ integration suite green with all three services up (12+ tests)
- ✅ live: stranger gets DM with WebApp button (does NOT auto-decline)
- ✅ live: Mini App SIWE round-trip approves the still-pending request
- ✅ live: replay of the same nonce/signature is rejected

### Mini App URL gotcha

If the chat owner sets `WEBAPP_URL` to an HTTP (non-HTTPS) URL,
Telegram silently refuses to open the Mini App on iOS / Android. The
bot's DM looks fine but the button does nothing. Always use HTTPS
(cloudflared tunnel, ngrok, or a real Vercel deploy).

---

## Session 3 — TBD (EVM holdings aggregator)
