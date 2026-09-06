#!/usr/bin/env bash
#
# Phase 2 of docs/DEPLOYMENT_SCALEWAY.md: the Serverless Container namespace and
# the container itself. Idempotent — a second run updates the existing container
# rather than creating a second one.
#
# Everything here was learned by deploying once by hand (D3). Three details cost
# a failed attempt each, and none of them is guessable from the CLI help:
#
#   * `memory-limit-bytes` does NOT take bytes. It requires a G/GB unit —
#     3072000000 is refused outright with "size must be defined using the G or
#     GB unit". Pass 3GB.
#   * An update REPLACES the environment map rather than merging into it, so
#     every variable and every secret is re-sent on every run. Sending only the
#     one you changed silently drops the rest.
#   * Secrets belong in `secret-environment-variables`. Scaleway stores those
#     separately and reads them back as argon2 hashes, so `container get` never
#     echoes one. Ordinary environment variables are returned in clear.
#
# Usage:
#   bash scripts/scaleway/deploy_container.sh
#   DEPLOY_IMAGE_TAG=3.0.1 bash scripts/scaleway/deploy_container.sh
#
# Reads the database credential written by provision.sh, and generates the
# application secrets on first run into a second 600-mode file outside the repo.
# ADMIN_PASSWORD in that file is how you sign in to the deployed app.
#
# Needs `scw` (authenticated) and Python 3.

set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

DEPLOY_PROJECT_NAME="${DEPLOY_PROJECT_NAME:-localchat-test}"
DEPLOY_NAMESPACE="${DEPLOY_NAMESPACE:-localchat}"
DEPLOY_CONTAINER="${DEPLOY_CONTAINER:-localchat}"
DEPLOY_IMAGE_TAG="${DEPLOY_IMAGE_TAG:-3.0.0}"
DEPLOY_IMAGE="${DEPLOY_IMAGE:-ghcr.io/jwvanderstam/localchat:$DEPLOY_IMAGE_TAG}"
DEPLOY_REGION="${DEPLOY_REGION:-fr-par}"
DEPLOY_MEMORY="${DEPLOY_MEMORY:-3GB}"
DEPLOY_MVCPU="${DEPLOY_MVCPU:-1000}"
DEPLOY_PORT="${DEPLOY_PORT:-5000}"
DEPLOY_DB_ENV="${DEPLOY_DB_ENV:-$HOME/.config/scw/localchat-db.env}"
DEPLOY_SECRET_ENV="${DEPLOY_SECRET_ENV:-$HOME/.config/scw/localchat-deploy.env}"
# Empty by default and set by deploy_embeddings.sh. Without it the app boots and
# serves everything except chat and document ingest, which both need Ollama.
DEPLOY_OLLAMA_URL="${DEPLOY_OLLAMA_URL:-}"
# Set by deploy_embeddings.sh. Handing the network to this script rather than
# applying it in a second call is what keeps the two from colliding: Scaleway
# refuses an update while the previous one is still applying, with
# "transient state error for resource 'container'".
DEPLOY_PRIVATE_NETWORK_ID="${DEPLOY_PRIVATE_NETWORK_ID:-}"

command -v scw >/dev/null 2>&1 || die "scw not found on PATH"
PYTHON=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PYTHON="$c"; break; fi
done
[[ -n "$PYTHON" ]] || die "no python3 on PATH"

PROFILE_ARGS=()
if [[ -n "${SCW_PROFILE:-}" ]]; then
  PROFILE_ARGS=(--profile "$SCW_PROFILE")
fi

# Secrets are passed to `scw` as arguments, so a failure that echoes the command
# publishes every one of them — to the terminal, and to whatever collects it.
# That happened once. The arguments are still shown, because a failure with no
# context is unfixable, but every secret value is replaced first.
_redact() {
  printf '%s' "$*" | sed -E 's/(secret-environment-variables[.][A-Za-z0-9_]+=)[^ ]*/\1***/g'
}

scw_json() {
  local raw
  if ! raw=$(scw "${PROFILE_ARGS[@]}" "$@" -o json 2>&1); then
    die "'scw $(_redact "$@")' failed:"$'\n'"$raw"
  fi
  printf '%s' "$raw"
}

read -r -d '' PICK <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

want = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
if isinstance(rows, dict):
    rows = next((v for v in rows.values() if isinstance(v, list)), [])
for row in rows:
    if isinstance(row, dict) and row.get("name") == want:
        print(row.get("id", ""))
        break
PY

read -r -d '' FIELD <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

try:
    obj = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
for key in sys.argv[1:]:
    value = obj.get(key)
    if value in (None, ""):
        sys.exit("reply carried no %s" % key)
    print(value)
PY

read -r -d '' MAKE_SECRETS <<'PY' || true
import os, pathlib, secrets, stat, string, sys

from cryptography.fernet import Fernet

out = pathlib.Path(sys.argv[1])
if out.exists():
    print("exists")
    raise SystemExit(0)
out.parent.mkdir(parents=True, exist_ok=True)
alphabet = string.ascii_letters + string.digits
out.write_text(
    "# LocalChat deployment secrets. Mode 600, outside the repo, never commit.\n"
    "# ADMIN_PASSWORD is how you sign in to the deployed application.\n"
    "SECRET_KEY=%s\n"
    "JWT_SECRET_KEY=%s\n"
    "ENCRYPTION_KEY=%s\n"
    "METRICS_TOKEN=%s\n"
    "ADMIN_PASSWORD=%s\n"
    % (
        secrets.token_hex(32),
        secrets.token_hex(32),
        Fernet.generate_key().decode(),
        secrets.token_hex(16),
        "".join(secrets.choice(alphabet) for _ in range(24)),
    ),
    encoding="utf-8",
    newline="\n",
)
os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
print("created")
PY

find_by_name() {  # find_by_name <name> -- <scw list args...>
  local want="$1"; shift 2
  local raw found
  raw=$(scw_json "$@")
  if ! found=$(printf '%s' "$raw" | "$PYTHON" -c "$PICK" "$want" 2>&1); then
    die "could not read the reply to 'scw $*' ($found)"
  fi
  printf '%s' "$found"
}

[[ -f "$DEPLOY_DB_ENV" ]] || die "no database credential at $DEPLOY_DB_ENV
Run scripts/scaleway/provision.sh first."

echo "Application secrets:"
umask 077
made=$("$PYTHON" -c "$MAKE_SECRETS" "$DEPLOY_SECRET_ENV")
if [[ "$made" == "created" ]]; then
  note "generated -> $DEPLOY_SECRET_ENV (mode 600)"
  note "ADMIN_PASSWORD in that file is your login. It is not printed here."
else
  note "reusing $DEPLOY_SECRET_ENV"
fi

# shellcheck disable=SC1090
set -a; . "$DEPLOY_DB_ENV"; . "$DEPLOY_SECRET_ENV"; set +a
for v in PG_HOST PG_PORT PG_DB PG_USER PG_PASSWORD SECRET_KEY JWT_SECRET_KEY \
         ENCRYPTION_KEY ADMIN_PASSWORD METRICS_TOKEN; do
  [[ -n "${!v:-}" ]] || die "$v is missing from the credential files"
done

echo "Project '$DEPLOY_PROJECT_NAME':"
PROJECT_ID=$(find_by_name "$DEPLOY_PROJECT_NAME" -- account project list)
[[ -n "$PROJECT_ID" ]] || die "project '$DEPLOY_PROJECT_NAME' does not exist — run provision.sh"
note "$PROJECT_ID"

echo "Namespace '$DEPLOY_NAMESPACE':"
NAMESPACE_ID=$(find_by_name "$DEPLOY_NAMESPACE" -- container namespace list \
  project-id="$PROJECT_ID" region="$DEPLOY_REGION")
if [[ -n "$NAMESPACE_ID" ]]; then
  note "exists ($NAMESPACE_ID)"
else
  NAMESPACE_ID=$(scw_json container namespace create name="$DEPLOY_NAMESPACE" \
    project-id="$PROJECT_ID" region="$DEPLOY_REGION" \
    description="LocalChat test stack" | "$PYTHON" -c "$FIELD" id)
  note "created ($NAMESPACE_ID)"
  for _ in $(seq 1 30); do
    st=$(scw_json container namespace get namespace-id="$NAMESPACE_ID" \
      region="$DEPLOY_REGION" | "$PYTHON" -c "$FIELD" status)
    [[ "$st" == "ready" ]] && break
    sleep 5
  done
  note "status $st"
fi

# Every variable is re-sent on every run, because an update replaces the map.
ENV_ARGS=(
  environment-variables.APP_ENV=production
  environment-variables.SERVER_PORT="$DEPLOY_PORT"
  environment-variables.UVICORN_WORKERS=1
  environment-variables.REDIS_ENABLED=false
  environment-variables.MCP_ENABLED=false
  environment-variables.PG_HOST="$PG_HOST"
  environment-variables.PG_PORT="$PG_PORT"
  environment-variables.PG_DB="$PG_DB"
  environment-variables.PG_USER="$PG_USER"
  environment-variables.PG_SSLMODE="${PG_SSLMODE:-require}"
)
NETWORK_ARGS=()
if [[ -n "$DEPLOY_PRIVATE_NETWORK_ID" ]]; then
  NETWORK_ARGS=(private-network-id="$DEPLOY_PRIVATE_NETWORK_ID")
fi

if [[ -n "$DEPLOY_OLLAMA_URL" ]]; then
  ENV_ARGS+=(
    environment-variables.OLLAMA_BASE_URL="$DEPLOY_OLLAMA_URL"
    environment-variables.OLLAMA_EMBEDDING_MODEL="${DEPLOY_EMBEDDING_MODEL:-nomic-embed-text}"
  )
fi

SECRET_ARGS=(
  secret-environment-variables.PG_PASSWORD="$PG_PASSWORD"
  secret-environment-variables.SECRET_KEY="$SECRET_KEY"
  secret-environment-variables.JWT_SECRET_KEY="$JWT_SECRET_KEY"
  secret-environment-variables.ENCRYPTION_KEY="$ENCRYPTION_KEY"
  secret-environment-variables.ADMIN_PASSWORD="$ADMIN_PASSWORD"
  secret-environment-variables.METRICS_TOKEN="$METRICS_TOKEN"
)

echo "Container '$DEPLOY_CONTAINER' ($DEPLOY_IMAGE):"
CONTAINER_ID=$(find_by_name "$DEPLOY_CONTAINER" -- container container list \
  namespace-id="$NAMESPACE_ID" region="$DEPLOY_REGION")

if [[ -n "$CONTAINER_ID" ]]; then
  note "exists ($CONTAINER_ID) — updating in place"
  scw_json container container update container-id="$CONTAINER_ID" \
    region="$DEPLOY_REGION" image="$DEPLOY_IMAGE" \
    "${NETWORK_ARGS[@]}" "${ENV_ARGS[@]}" "${SECRET_ARGS[@]}" >/dev/null
else
  note "absent — creating"
  # min/max scale 1 is D1 and D2: no scale-to-zero cold start on a 3 GB image,
  # and no way for concurrency to multiply the bill.
  CONTAINER_ID=$(scw_json container container create \
    namespace-id="$NAMESPACE_ID" name="$DEPLOY_CONTAINER" region="$DEPLOY_REGION" \
    image="$DEPLOY_IMAGE" port="$DEPLOY_PORT" protocol=http1 privacy=public \
    min-scale=1 max-scale=1 \
    memory-limit-bytes="$DEPLOY_MEMORY" mvcpu-limit="$DEPLOY_MVCPU" \
    timeout=300s \
    "${NETWORK_ARGS[@]}" "${ENV_ARGS[@]}" "${SECRET_ARGS[@]}" | "$PYTHON" -c "$FIELD" id)
  note "created ($CONTAINER_ID)"
fi

echo "Waiting for the container (a 3 GB pull takes a few minutes):"
STATUS=""
for _ in $(seq 1 60); do
  STATUS=$(scw_json container container get container-id="$CONTAINER_ID" \
    region="$DEPLOY_REGION" | "$PYTHON" -c "$FIELD" status)
  case "$STATUS" in ready|error) break;; esac
  sleep 20
done
note "status $STATUS"
[[ "$STATUS" == "ready" ]] || die "container did not become ready (status: $STATUS)"

ENDPOINT=$(scw_json container container get container-id="$CONTAINER_ID" \
  region="$DEPLOY_REGION" | "$PYTHON" -c "$FIELD" public_endpoint)

cat <<SUMMARY

Phase 2 is deployed.

  namespace  $DEPLOY_NAMESPACE  $NAMESPACE_ID
  container  $DEPLOY_CONTAINER  $CONTAINER_ID
  image      $DEPLOY_IMAGE
  endpoint   $ENDPOINT

Validate it:  python scripts/scaleway/verify_deployment.py $ENDPOINT
Add embeddings: bash scripts/scaleway/deploy_embeddings.sh
Tear it down:   docs/COST_KILL_SWITCH.md
SUMMARY
