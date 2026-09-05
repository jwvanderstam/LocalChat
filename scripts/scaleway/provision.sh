#!/usr/bin/env bash
#
# Stands up the LocalChat test stack's Phase 1 on Scaleway: a scoped project, a
# Serverless SQL Database, and an IAM identity that can reach that database and
# nothing else. See docs/DEPLOYMENT_SCALEWAY.md §4 and §10.
#
# Idempotent at every level except one. Re-running finds what exists and leaves
# it alone; only the API key cannot work that way, because Scaleway shows a
# secret key once and never again. That asymmetry is the whole reason this is a
# script rather than a list of commands in a runbook:
#
#   everything    -> look it up by name, create only if absent
#   the API key   -> create only when the application has none, and write the
#                    secret straight to PROVISION_ENV_OUT. If a key already exists its
#                    secret is unrecoverable, so this says so and refuses
#                    rather than quietly creating a second one.
#
# Every tunable is PROVISION_-prefixed on purpose: the application's own
# .env defines APP_NAME, and an unprefixed name silently became the name of
# the IAM application it created.
#
# Usage:
#   bash scripts/scaleway/provision.sh                       # create or verify
#   PROVISION_ENV_OUT=~/localchat-db.env bash scripts/scaleway/provision.sh
#   PROVISION_ROTATE_KEY=1 bash scripts/scaleway/provision.sh          # replace the key
#
# The secret is never printed. It goes to PROVISION_ENV_OUT (mode 600), which defaults to
# a path outside this repository so it cannot be committed by accident.
#
# Needs `scw` (authenticated — `scw login`) and Python 3.

# -e matters more here than anywhere: every lookup runs in a command
# substitution, and `die` inside one only exits the subshell. Without -e a
# refusal printed its message and then provisioned anyway.
set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

PROVISION_PROJECT_NAME="${PROVISION_PROJECT_NAME:-localchat-test}"
PROVISION_DB_NAME="${PROVISION_DB_NAME:-localchat}"
PROVISION_APP_NAME="${PROVISION_APP_NAME:-localchat-app}"
PROVISION_POLICY_NAME="${PROVISION_POLICY_NAME:-localchat-db-readwrite}"
PROVISION_CPU_MIN="${PROVISION_CPU_MIN:-0}"
PROVISION_CPU_MAX="${PROVISION_CPU_MAX:-1}"
PROVISION_KEY_EXPIRES="${PROVISION_KEY_EXPIRES:-+365d}"
PROVISION_ENV_OUT="${PROVISION_ENV_OUT:-$HOME/.config/scw/localchat-db.env}"
PROVISION_ROTATE_KEY="${PROVISION_ROTATE_KEY:-}"

# ServerlessSQLDatabaseReadWrite covers data *and* DDL, which the app needs: it
# runs its own Alembic chain and _ensure_extensions_and_tables() on boot.
# FullAccess would also permit deleting the database, which it never does.
PROVISION_PERMISSION_SET="${PROVISION_PERMISSION_SET:-ServerlessSQLDatabaseReadWrite}"

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

scw_json() {
  local raw
  if ! raw=$(scw "${PROFILE_ARGS[@]}" "$@" -o json 2>&1); then
    die "'scw $*' failed:"$'\n'"$raw"
  fi
  printf '%s' "$raw"
}

# Prints the id of the row whose `name` matches, or nothing. Exits non-zero on
# an unreadable reply so that "cannot tell" never reads as "does not exist".
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
    if not isinstance(row, dict):
        sys.exit("reply contained a non-object entry")
    if row.get("name") == want:
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

read -r -d '' COUNT_KEYS <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

rows = json.load(sys.stdin)
if isinstance(rows, dict):
    rows = next((v for v in rows.values() if isinstance(v, list)), [])
print(len(rows))
PY

read -r -d '' LIST_ACCESS_KEYS <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

rows = json.load(sys.stdin)
if isinstance(rows, dict):
    rows = next((v for v in rows.values() if isinstance(v, list)), [])
for row in rows:
    if row.get("access_key"):
        print(row["access_key"])
PY

read -r -d '' WRITE_ENV <<'PY' || true
import json, os, pathlib, stat, sys

out, host, dbname = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
try:
    key = json.load(sys.stdin)
except Exception as exc:
    sys.exit("api-key create did not return JSON: %s" % exc)
if "secret_key" not in key:
    sys.exit("api-key create returned no secret_key")

out.write_text(
    "# Scaleway Serverless SQL credential for the LocalChat test stack.\n"
    "# Written by scripts/scaleway/provision.sh - do not commit.\n"
    "# Created %s\n"
    "# EXPIRES %s  <- the deployment stops working on this date.\n"
    "PG_HOST=%s\n"
    "PG_PORT=5432\n"
    "PG_DB=%s\n"
    "PG_USER=%s\n"
    "PG_PASSWORD=%s\n"
    "PG_SSLMODE=require\n"
    % (
        key.get("created_at", "?"),
        key.get("expires_at", "never - the organisation allows unbounded keys"),
        host,
        dbname,
        key.get("application_id", ""),
        key["secret_key"],
    ),
    encoding="utf-8",
    newline="\n",
)
os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
print("  created %s, secret written to %s (mode 600)" % (key.get("access_key"), out))
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

echo "Project '$PROVISION_PROJECT_NAME':"
PROJECT_ID=$(find_by_name "$PROVISION_PROJECT_NAME" -- account project list)
if [[ -n "$PROJECT_ID" ]]; then
  note "exists ($PROJECT_ID)"
else
  PROJECT_ID=$(scw_json account project create name="$PROVISION_PROJECT_NAME" \
    description="LocalChat test stack" | "$PYTHON" -c "$FIELD" id) \
    || die "project creation returned no id"
  note "created ($PROJECT_ID)"
fi

echo "Database '$PROVISION_DB_NAME':"
DB_ID=$(find_by_name "$PROVISION_DB_NAME" -- sdb-sql database list project-id="$PROJECT_ID")
if [[ -n "$DB_ID" ]]; then
  note "exists ($DB_ID)"
else
  # cpu-min/cpu-max are required by the CLI, so the Terraform provider's
  # max_cpu = 15 default cannot silently apply on this path (§4).
  DB_ID=$(scw_json sdb-sql database create name="$PROVISION_DB_NAME" \
    cpu-min="$PROVISION_CPU_MIN" cpu-max="$PROVISION_CPU_MAX" project-id="$PROJECT_ID" \
    | "$PYTHON" -c "$FIELD" id) || die "database creation returned no id"
  note "created ($DB_ID) with cpu $PROVISION_CPU_MIN-$PROVISION_CPU_MAX"
fi

DB_ENDPOINT=$(scw_json sdb-sql database get database-id="$DB_ID" \
  | "$PYTHON" -c "$FIELD" endpoint) || die "could not read the database endpoint"
# postgres://<host>:<port>/<db>?sslmode=require -> host
DB_HOST=$(printf '%s' "$DB_ENDPOINT" | sed -e 's#^postgres://##' -e 's#[:/?].*$##')
[[ -n "$DB_HOST" ]] || die "could not parse a host out of: $DB_ENDPOINT"
note "endpoint $DB_HOST"

echo "IAM application '$PROVISION_APP_NAME':"
APP_ID=$(find_by_name "$PROVISION_APP_NAME" -- iam application list)
if [[ -n "$APP_ID" ]]; then
  note "exists ($APP_ID)"
else
  APP_ID=$(scw_json iam application create name="$PROVISION_APP_NAME" \
    description="LocalChat test stack - owns the database credential" \
    | "$PYTHON" -c "$FIELD" id) || die "application creation returned no id"
  note "created ($APP_ID)"
fi

echo "Policy '$PROVISION_POLICY_NAME' ($PROVISION_PERMISSION_SET, scoped to the project):"
POLICY_ID=$(find_by_name "$PROVISION_POLICY_NAME" -- iam policy list)
if [[ -n "$POLICY_ID" ]]; then
  note "exists ($POLICY_ID)"
else
  POLICY_ID=$(scw_json iam policy create name="$PROVISION_POLICY_NAME" \
    description="Scoped to the $PROVISION_PROJECT_NAME project only" \
    application-id="$APP_ID" \
    rules.0.permission-set-names.0="$PROVISION_PERMISSION_SET" \
    rules.0.project-ids.0="$PROJECT_ID" \
    | "$PYTHON" -c "$FIELD" id) || die "policy creation returned no id"
  note "created ($POLICY_ID)"
fi

echo "API key:"
KEY_COUNT=$(scw_json iam api-key list application-id="$APP_ID" \
  | "$PYTHON" -c "$COUNT_KEYS")

if [[ "$KEY_COUNT" -gt 0 && -z "$PROVISION_ROTATE_KEY" ]]; then
  note "$KEY_COUNT key(s) already exist on this application."
  note "A secret key is shown once and cannot be read back, so this will not"
  note "create another. If you no longer hold the secret, rotate it:"
  note "  PROVISION_ROTATE_KEY=1 bash scripts/scaleway/provision.sh"
  note "Rotating invalidates the old credential - redeploy the container after."
else
  if [[ "$KEY_COUNT" -gt 0 ]]; then
    note "rotating: deleting $KEY_COUNT existing key(s)"
    while IFS= read -r ak; do
      [[ -n "$ak" ]] || continue
      if scw "${PROFILE_ARGS[@]}" iam api-key delete access-key="$ak" >/dev/null 2>&1; then
        note "  deleted $ak"
      else
        note "  FAILED to delete $ak"
      fi
    done < <(scw_json iam api-key list application-id="$APP_ID" \
      | "$PYTHON" -c "$LIST_ACCESS_KEYS")
  fi

  umask 077
  mkdir -p "$(dirname "$PROVISION_ENV_OUT")" || die "cannot create $(dirname "$PROVISION_ENV_OUT")"
  # The secret goes from scw straight into the file. It is never echoed and
  # never held in a shell variable.
  if ! scw "${PROFILE_ARGS[@]}" iam api-key create application-id="$APP_ID" \
        expires-at="$PROVISION_KEY_EXPIRES" \
        description="LocalChat test stack database credential" -o json \
        | "$PYTHON" -c "$WRITE_ENV" "$PROVISION_ENV_OUT" "$DB_HOST" "$PROVISION_DB_NAME"; then
    die "api-key creation failed; the application may now have no usable key.
Re-run with PROVISION_ROTATE_KEY=1 once the cause is fixed."
  fi
fi

cat <<SUMMARY

Phase 1 is provisioned.

  project   $PROVISION_PROJECT_NAME  $PROJECT_ID
  database  $PROVISION_DB_NAME  $DB_ID
  host      $DB_HOST
  identity  $PROVISION_APP_NAME  $APP_ID  (policy $POLICY_ID, $PROVISION_PERMISSION_SET)
  env file  $PROVISION_ENV_OUT

The credential is scoped to this project and this database. It cannot reach the
default project, and it cannot delete the database.

Next: docs/DEPLOYMENT_SCALEWAY.md Phase 2 - the container, from a version tag.
To tear all of it down: docs/COST_KILL_SWITCH.md.
SUMMARY
