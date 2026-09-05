#!/usr/bin/env bash
#
# Scaleway cost kill switch: delete everything billable in ONE project.
# See docs/COST_KILL_SWITCH.md.
#
# Scaleway has no spend cap (§8 of DEPLOYMENT_SCALEWAY.md). A budget alert is an
# estimate that lags the invoice and stops nothing. This is what actually stops
# the burn, and it stops it by deleting — not stopping — because a stopped
# Instance keeps billing for the volumes and the reserved IP it leaves behind.
#
# That is only acceptable because the test stack holds nothing worth keeping:
# the image is redeployable and the data is test data. Do not point this at a
# project where that stops being true.
#
# Usage:
#   PROJECT_ID=<uuid> bash scripts/scaleway/panic_teardown.sh              # dry run
#   PROJECT_ID=<uuid> CONFIRM=DESTROY bash scripts/scaleway/panic_teardown.sh
#
# Without CONFIRM it only lists what it would delete, so the panic path is:
# run it, read it, run it again with CONFIRM=DESTROY.
#
# Deliberately no `set -e`: one failed delete must not stop the sweep. Failures
# are collected and the script exits non-zero with them named.

set -uo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

: "${PROJECT_ID:?set PROJECT_ID — the project to empty. This never guesses.}"
CONFIRM="${CONFIRM:-}"

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

# The default project shares its id with the organisation. Emptying that is a
# different and much larger act than emptying a scoped project, so it is refused
# outright rather than confirmed — there is no flag for it here.
ORG_ID=$(scw "${PROFILE_ARGS[@]}" config get default-organization-id 2>/dev/null || true)
if [[ -n "$ORG_ID" && "$PROJECT_ID" == "$ORG_ID" ]]; then
  die "PROJECT_ID is the organisation's default project. Refusing.
Create a scoped project and put the stack there instead."
fi

read -r -d '' READ_ROWS <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

scope_key = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
if isinstance(rows, dict):
    # Some list verbs wrap the array; take the first list-valued field.
    rows = next((v for v in rows.values() if isinstance(v, list)), [])
for row in rows:
    if not isinstance(row, dict) or not row.get("id"):
        continue
    print("%s\t%s\t%s" % (row["id"], row.get(scope_key, ""), row.get("name", "-")))
PY

FAILED=()
PLANNED=0

# rows <scope-key> -- <scw list args...>
rows() {
  local scope_key="$1"; shift 2
  local raw
  if ! raw=$(scw "${PROFILE_ARGS[@]}" "$@" project-id="$PROJECT_ID" -o json 2>&1); then
    printf 'warning: could not list via "%s" — check by hand:\n%s\n' "$*" "$raw" >&2
    FAILED+=("list: $*")
    return
  fi
  printf '%s' "$raw" | "$PYTHON" -c "$READ_ROWS" "$scope_key"
}

# kill <label> <scw delete args...>
kill_one() {
  local label="$1"; shift
  PLANNED=$((PLANNED + 1))
  if [[ "$CONFIRM" != "DESTROY" ]]; then
    printf '  would delete  %s\n' "$label"
    return
  fi
  local out
  if out=$(scw "${PROFILE_ARGS[@]}" "$@" 2>&1); then
    printf '  deleted       %s\n' "$label"
  else
    printf '  FAILED        %s\n    %s\n' "$label" "$out" >&2
    FAILED+=("$label")
  fi
}

if [[ "$CONFIRM" == "DESTROY" ]]; then
  printf 'DESTROYING everything billable in project %s\n\n' "$PROJECT_ID"
else
  printf 'Dry run for project %s — nothing will be deleted.\n' "$PROJECT_ID"
  printf 'Re-run with CONFIRM=DESTROY to actually stop the burn.\n\n'
fi

# Ordered by burn rate. Instances first: a GPU Instance is EUR 0.787/h and up,
# which is more than everything below it combined.
echo "Instances (the expensive ones):"
while IFS=$'\t' read -r id zone name; do
  [[ -n "$id" ]] || continue
  # with-volumes and with-ip are the whole point: a plain delete leaves block
  # volumes and a reserved IP behind, and both keep billing silently.
  kill_one "instance $name ($id, $zone)" instance server delete \
    server-id="$id" zone="$zone" with-volumes=all with-ip=true force-shutdown=true
done < <(rows zone -- instance server list zone=all)

echo "Serverless Containers (namespace delete removes the containers in it):"
while IFS=$'\t' read -r id region name; do
  [[ -n "$id" ]] || continue
  kill_one "namespace $name ($id, $region)" container namespace delete \
    namespace-id="$id" region="$region"
done < <(rows region -- container namespace list region=all)

echo "Serverless SQL databases:"
while IFS=$'\t' read -r id region name; do
  [[ -n "$id" ]] || continue
  kill_one "database $name ($id, $region)" sdb-sql database delete \
    database-id="$id" region="$region"
done < <(rows region -- sdb-sql database list region=all)

echo "Block volumes left behind (detached volumes bill at full price):"
while IFS=$'\t' read -r id zone name; do
  [[ -n "$id" ]] || continue
  kill_one "volume $name ($id, $zone)" block volume delete volume-id="$id" zone="$zone"
done < <(rows zone -- block volume list zone=all)

echo "Reserved IPs (a flexible IP bills whether or not it is attached):"
while IFS=$'\t' read -r id zone name; do
  [[ -n "$id" ]] || continue
  kill_one "ip $id ($zone)" instance ip delete ip="$id" zone="$zone"
done < <(rows zone -- instance ip list zone=all)

echo "Private networks (free, but they hold references that block other deletes):"
while IFS=$'\t' read -r id region name; do
  [[ -n "$id" ]] || continue
  kill_one "private network $name ($id, $region)" vpc private-network delete \
    private-network-id="$id" region="$region"
done < <(rows region -- vpc private-network list region=all)

echo
if [[ "$PLANNED" -eq 0 ]]; then
  echo "Nothing billable found in this project."
elif [[ "$CONFIRM" != "DESTROY" ]]; then
  printf '%d resources would be deleted. Re-run with CONFIRM=DESTROY.\n' "$PLANNED"
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
  printf '\n%d did NOT go away — delete these in the console now:\n' "${#FAILED[@]}" >&2
  printf '  - %s\n' "${FAILED[@]}" >&2
  exit 1
fi

if [[ "$CONFIRM" == "DESTROY" ]]; then
  echo
  echo "Verify with:  scw billing consumption list -o json"
  echo "Consumption lags, so re-check in an hour before believing it is zero."
fi
