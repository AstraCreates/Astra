#!/usr/bin/env bash
set -Eeuo pipefail

# Deploy the latest origin/main to astra-server only when the server is behind.
# This file is intentionally untracked: it is a local operator convenience.

REMOTE_HOST="${ASTRA_DEPLOY_HOST:-astra-server}"
REMOTE_DIR="${ASTRA_DEPLOY_DIR:-/opt/astra/repo}"
COMPOSE_FILE="${ASTRA_COMPOSE_FILE:-docker-compose.yml}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "Fetching origin/main..."
git fetch origin main
target_sha="$(git rev-parse origin/main)"
target_short="$(git rev-parse --short "$target_sha")"

_server_shas="$(ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' && git rev-parse HEAD && git fetch origin main >/dev/null && git rev-parse origin/main")"
server_sha="$(sed -n '1p' <<<"$_server_shas")"
server_origin_sha="$(sed -n '2p' <<<"$_server_shas")"

echo "GitHub origin/main: $target_short"
echo "Server checkout:   $(git rev-parse --short "$server_sha")"

if [[ "$server_sha" == "$target_sha" ]]; then
  echo "Server is already current; skipping pull and rebuild."
  exit 0
fi

if [[ "$server_origin_sha" != "$target_sha" ]]; then
  echo "Server fetch disagrees with local origin/main; refusing to deploy." >&2
  echo "server origin/main: $(git rev-parse --short "$server_origin_sha")" >&2
  echo "local  origin/main: $target_short" >&2
  exit 1
fi

echo "Updating server to $target_short and rebuilding frontend/backend..."
ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' \
  && git reset --hard origin/main \
  && docker compose -f '$COMPOSE_FILE' up -d --build --force-recreate backend frontend"

echo "Waiting for backend readiness..."
for attempt in {1..30}; do
  if ssh "$REMOTE_HOST" "curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null"; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    echo "Backend did not become ready." >&2
    ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' && docker compose -f '$COMPOSE_FILE' ps backend frontend" >&2 || true
    exit 1
  fi
  sleep 2
done

ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' \
  && test \"\$(git rev-parse HEAD)\" = \"$target_sha\" \
  && docker compose -f '$COMPOSE_FILE' ps backend frontend \
  && curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null"

echo "Deployed $target_short successfully."
