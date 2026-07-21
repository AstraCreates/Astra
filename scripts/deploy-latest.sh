#!/usr/bin/env bash
set -Eeuo pipefail

# Deploy an immutable origin/main release to astra-server. This file is
# intentionally untracked: it is a local operator convenience.

REMOTE_HOST="${ASTRA_DEPLOY_HOST:-astra-server}"
REMOTE_DIR="${ASTRA_DEPLOY_DIR:-/opt/astra/repo}"
COMPOSE_FILE="${ASTRA_COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_PROJECT="${ASTRA_COMPOSE_PROJECT:-$(basename "$REMOTE_DIR")}" # Preserve Compose's historical default.
RELEASE_ROOT="${ASTRA_RELEASE_ROOT:-$REMOTE_DIR/../astra-releases}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/deploy-latest.sh [--dry-run]

Deploy the exact local origin/main SHA as a locked remote worktree.
The remote host serializes deployments, records receipts, verifies both release
containers and HTTP smoke checks, and rolls back to the prior known-good receipt
when a release fails.

Environment:
  ASTRA_DEPLOY_HOST       SSH host (default: astra-server)
  ASTRA_DEPLOY_DIR        Persistent repository directory on the host
  ASTRA_COMPOSE_FILE      Compose file relative to the repository root
  ASTRA_COMPOSE_PROJECT   Stable Compose project name (default: astra)
  ASTRA_RELEASE_ROOT      Directory for immutable Git worktrees
  ASTRA_DEPLOY_BOOTSTRAP  Set to 1 only to establish the first known-good receipt
EOF
}

case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

[[ "$COMPOSE_FILE" != /* && "$COMPOSE_FILE" != *".."* ]] || {
  echo "ASTRA_COMPOSE_FILE must be a repository-relative path without '..'." >&2
  exit 2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if (( DRY_RUN )); then
  echo "Reading local origin/main for dry run..."
else
  echo "Fetching origin/main..."
  git fetch --quiet origin main
fi
target_sha="$(git rev-parse --verify origin/main^{commit})"
target_short="$(git rev-parse --short "$target_sha")"

if (( DRY_RUN )); then
  cat <<EOF
Dry run: no remote changes will be made.
Would acquire $REMOTE_DIR/.astra-release/deploy.lock on $REMOTE_HOST, verify the
remote origin/main SHA is $target_sha, create/reuse its detached worktree in
$RELEASE_ROOT, build
and start SHA-tagged backend/frontend containers, run identity and HTTP smokes,
record a receipt, and roll back the prior successful receipt on failure.
EOF
  exit 0
fi

echo "Deploying locked release $target_short to $REMOTE_HOST..."
ssh "$REMOTE_HOST" bash -s -- \
  "$REMOTE_DIR" "$RELEASE_ROOT" "$COMPOSE_FILE" "$COMPOSE_PROJECT" "$target_sha" \
  "${ASTRA_DEPLOY_BOOTSTRAP:-0}" <<'REMOTE_SCRIPT'
set -Eeuo pipefail

remote_dir="$1"
releases_dir="$2"
compose_file="$3"
compose_project="$4"
target_sha="$5"
bootstrap="$6"
state_dir="$remote_dir/.astra-release"
receipts_dir="$state_dir/receipts"
current_file="$state_dir/current-sha"

die() { echo "deploy: $*" >&2; exit 1; }
valid_sha() { [[ "$1" =~ ^[0-9a-f]{40}$ ]]; }
timestamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

receipt_is_success() {
  local sha="$1"
  [[ -f "$receipts_dir/$sha.json" ]] && grep -Fq '"status":"success"' "$receipts_dir/$sha.json"
}

write_receipt() {
  local sha="$1" status="$2" previous="${3:-}" note="${4:-}"
  local tmp="$receipts_dir/$sha.json.$$"
  # Inputs are fixed SHAs/status text controlled by this script, not user content.
  printf '{"sha":"%s","status":"%s","previous_sha":"%s","at":"%s","note":"%s"}\n' \
    "$sha" "$status" "$previous" "$(timestamp)" "$note" >"$tmp"
  mv -f "$tmp" "$receipts_dir/$sha.json"
}

release_dir() { printf '%s/%s' "$releases_dir" "$1"; }

ensure_release() {
  local sha="$1" dir
  dir="$(release_dir "$sha")"
  if [[ -d "$dir" ]]; then
    [[ "$(git -C "$dir" rev-parse HEAD)" == "$sha" ]] || die "release directory $dir does not match its SHA"
  else
    git -C "$remote_dir" worktree add --detach "$dir" "$sha"
  fi

  # Runtime-only files are deliberately kept outside immutable Git releases.
  [[ -e "$remote_dir/.env" && ! -e "$dir/.env" ]] && ln -s "$remote_dir/.env" "$dir/.env"
  for path in deploy/certs deploy/certbot/conf deploy/certbot/www; do
    [[ -e "$remote_dir/$path" && ! -e "$dir/$path" ]] || continue
    mkdir -p "$(dirname "$dir/$path")"
    ln -s "$remote_dir/$path" "$dir/$path"
  done
}

compose() {
  local sha="$1" dir override
  dir="$(release_dir "$sha")"
  override="$dir/.astra-release-compose.yml"
  cat >"$override" <<EOF
services:
  backend:
    image: astra-release-backend:$sha
    volumes:
      - "$dir/backend:/app/backend:ro"
    environment:
      ASTRA_RELEASE_SHA: "$sha"
    labels:
      com.astra.release.sha: "$sha"
      com.astra.release.role: backend
  frontend:
    image: astra-release-frontend:$sha
    environment:
      ASTRA_RELEASE_SHA: "$sha"
    labels:
      com.astra.release.sha: "$sha"
      com.astra.release.role: frontend
EOF
  docker compose --project-name "$compose_project" --project-directory "$remote_dir" \
    --env-file "$remote_dir/.env" -f "$dir/$compose_file" -f "$override" "${@:2}"
}

activate_release() {
  local sha="$1"
  ensure_release "$sha"
  compose "$sha" up -d --build --force-recreate backend frontend
}

smoke_release() {
  local sha="$1" attempt backend_id frontend_id backend_image frontend_image release_body
  for attempt in {1..30}; do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null \
      && curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null; then
      break
    fi
    if (( attempt == 30 )); then
      return 1
    fi
    sleep 2
  done

  backend_id="$(compose "$sha" ps -q backend)"
  frontend_id="$(compose "$sha" ps -q frontend)"
  [[ -n "$backend_id" && -n "$frontend_id" ]] || return 1
  release_body="$(curl -fsS --max-time 5 http://127.0.0.1:8000/release)" || return 1
  [[ "$release_body" == *"$sha"* ]] || return 1
  [[ "$(docker inspect -f '{{index .Config.Labels "com.astra.release.sha"}}' "$backend_id")" == "$sha" ]] || return 1
  [[ "$(docker inspect -f '{{index .Config.Labels "com.astra.release.sha"}}' "$frontend_id")" == "$sha" ]] || return 1
  backend_image="$(docker image inspect -f '{{.Id}}' "astra-release-backend:$sha")"
  frontend_image="$(docker image inspect -f '{{.Id}}' "astra-release-frontend:$sha")"
  [[ "$(docker inspect -f '{{.Image}}' "$backend_id")" == "$backend_image" ]] || return 1
  [[ "$(docker inspect -f '{{.Image}}' "$frontend_id")" == "$frontend_image" ]] || return 1
}

rollback() {
  local previous="$1"
  echo "Release failed; rolling back to known-good ${previous:0:12}..." >&2
  activate_release "$previous"
  smoke_release "$previous"
  printf '%s\n' "$previous" >"$current_file.tmp"
  mv -f "$current_file.tmp" "$current_file"
  echo "Rollback to ${previous:0:12} passed." >&2
}

mkdir -p "$releases_dir" "$receipts_dir"
exec 9>"$state_dir/deploy.lock"
flock -n 9 || die "another deployment holds $state_dir/deploy.lock"

[[ -d "$remote_dir/.git" ]] || die "$remote_dir is not a Git repository"
git -C "$remote_dir" fetch --quiet origin main
remote_target="$(git -C "$remote_dir" rev-parse --verify origin/main^{commit})"
[[ "$remote_target" == "$target_sha" ]] || die "remote origin/main ($remote_target) disagrees with requested SHA ($target_sha)"

previous_sha=""
if [[ -f "$current_file" ]]; then previous_sha="$(<"$current_file")"; fi
if [[ -n "$previous_sha" ]] && (! valid_sha "$previous_sha" || ! receipt_is_success "$previous_sha"); then
  die "current release receipt is missing or invalid; refusing unsafe deployment"
fi

if [[ "$previous_sha" == "$target_sha" ]]; then
  echo "Release ${target_sha:0:12} is already recorded as current; re-verifying it."
  smoke_release "$target_sha" || die "recorded current release failed smoke checks"
  exit 0
fi

if [[ -z "$previous_sha" ]]; then
  [[ "$bootstrap" == 1 ]] || die "no known-good receipt; set ASTRA_DEPLOY_BOOTSTRAP=1 to verify and adopt the current server SHA first"
  previous_sha="$(git -C "$remote_dir" rev-parse --verify HEAD^{commit})"
  valid_sha "$previous_sha" || die "server HEAD is not a commit"
  echo "Bootstrapping known-good release ${previous_sha:0:12}..."
  activate_release "$previous_sha"
  smoke_release "$previous_sha" || die "current server release failed bootstrap smoke checks"
  write_receipt "$previous_sha" success "" "bootstrap-verified"
  printf '%s\n' "$previous_sha" >"$current_file.tmp"
  mv -f "$current_file.tmp" "$current_file"
fi

echo "Activating ${target_sha:0:12} (previous ${previous_sha:0:12})..."
if activate_release "$target_sha" && smoke_release "$target_sha"; then
  write_receipt "$target_sha" success "$previous_sha" "backend-and-frontend-smoke-passed"
  printf '%s\n' "$target_sha" >"$current_file.tmp"
  mv -f "$current_file.tmp" "$current_file"
  echo "Deployed ${target_sha:0:12} successfully."
else
  write_receipt "$target_sha" failed "$previous_sha" "activation-or-smoke-failed"
  rollback "$previous_sha" || die "release failed and rollback failed; inspect $state_dir"
  die "release ${target_sha:0:12} failed; rollback completed"
fi
REMOTE_SCRIPT
