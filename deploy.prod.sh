#!/usr/bin/env bash
# tg-token production deploy — Base mainnet (DUST_CHAIN_ID=8453)
# Hardened: fail-fast + explicit docker build gate before compose up.
set -euo pipefail

TG_DIR="/home/hammad/Desktop/claude_folder/claude/tg-token"
cd "$TG_DIR"

echo "==> [1/5] git pull (tree confirmed clean, on main)"
git pull

echo "==> [2/5] ensure .env.prod (seed from .env only if absent)"
if [ ! -f .env.prod ]; then
  cp .env .env.prod
  echo "    created .env.prod from .env"
else
  echo "    .env.prod already present — leaving content as-is"
fi

echo "==> [3/5] pin Base mainnet (DUST_CHAIN_ID=8453)"
if grep -q 'DUST_CHAIN_ID' .env.prod; then
  sed -i 's/.*DUST_CHAIN_ID.*/DUST_CHAIN_ID=8453/' .env.prod
else
  echo 'DUST_CHAIN_ID=8453' >> .env.prod
fi
grep DUST_CHAIN_ID .env.prod

echo "==> [4/5] docker build (GATE: abort before compose up on non-zero exit)"
# --provenance=false: avoid BuildKit attestation-manifest index, which fails to
# retag an existing tag on the containerd image store ("image ...: already exists").
if ! docker build --provenance=false -t tg-token-bot:latest .; then
  echo "ERROR: docker build failed — aborting before compose up. Running containers untouched." >&2
  exit 1
fi
echo "    build OK"

echo "==> [5/5] compose up"
docker compose -f infra/docker-compose.prod.yml up -d --remove-orphans

sleep 10
echo "==> docker logs --tail 40 tg-token-bot:"
docker logs --tail 40 tg-token-bot 2>&1 || {
  echo "(container name 'tg-token-bot' not found — showing compose status + service logs)"
  docker compose -f infra/docker-compose.prod.yml ps
  docker compose -f infra/docker-compose.prod.yml logs --tail 40 2>&1 || true
}
