#!/usr/bin/env bash
# deploy.sh — push tg-token to Hetzner and (re)start the bot stack
# Usage:  HETZNER_HOST=<ip> ./deploy.sh
#         HETZNER_HOST=<ip> HETZNER_USER=root ./deploy.sh
set -euo pipefail

HOST="${HETZNER_HOST:?set HETZNER_HOST=<server-ip>}"
USER="${HETZNER_USER:-root}"
REMOTE_DIR="/opt/tg-token"
SSH="ssh -o StrictHostKeyChecking=no ${USER}@${HOST}"
SCP="scp -o StrictHostKeyChecking=no"

echo "==> syncing code to ${HOST}:${REMOTE_DIR}"
$SSH "mkdir -p ${REMOTE_DIR}"
rsync -az --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='.git' --exclude='*.pyc' \
  ./ ${USER}@${HOST}:${REMOTE_DIR}/

echo "==> checking .env.prod exists on server"
if ! $SSH "test -f ${REMOTE_DIR}/.env.prod"; then
  echo ""
  echo "  ⚠️  .env.prod not found on server."
  echo "  Run on server:"
  echo "    cp ${REMOTE_DIR}/.env.prod.template ${REMOTE_DIR}/.env.prod"
  echo "    nano ${REMOTE_DIR}/.env.prod   # fill in BOT_TOKEN etc."
  echo ""
  echo "  Then re-run this script."
  exit 1
fi

echo "==> building image on server"
$SSH "cd ${REMOTE_DIR} && docker build -t tg-token-bot:latest ."

echo "==> (re)starting stack"
$SSH "cd ${REMOTE_DIR}/infra && docker compose -f docker-compose.prod.yml up -d --remove-orphans"

echo "==> waiting 8s for bot to connect..."
sleep 8

echo "==> recent logs"
$SSH "docker logs --tail=30 tg-token-bot"

echo ""
echo "✅ Done. Bot is running on ${HOST}."
echo "   Logs: ssh ${USER}@${HOST} 'docker logs -f tg-token-bot'"
