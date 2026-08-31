#!/usr/bin/env bash
#
# Scaleway cost guardrail: budget -> alert threshold -> optional webhook.
# See docs/localchat_scaleway_deployment_plan.md §11.
#
# Run this BEFORE the GPU instance exists. That instance is the line item the
# alert guards, and an alert created afterwards guards nothing that already burned.
#
# Terraform cannot express any of this — the Scaleway provider exposes billing as
# a read-only data source only. This runs alongside `terraform apply`, never
# inside it.
#
# `scw billing ... create` is not idempotent: a second blind run produces a second
# budget and a second alert, silently, and the duplicate is invisible until the
# invoice. So every level is looked up before it is created. When a lookup cannot
# be trusted — the call fails, or the payload is not the shape expected — this
# refuses to create anything rather than risk the duplicate it could not see.
#
# Usage:
#   BUDGET_AMOUNT=50 ALERT_THRESHOLD=40 [WEBHOOK_URL=https://...] \
#   [BUDGET_NAME=localchat-test-stack] [SCW_PROFILE=localchat-test] \
#     bash scripts/scaleway/bootstrap_billing_alert.sh
#
# Needs `scw` and Python 3 on PATH. Deliberately not jq — Python is already a
# hard dependency of this repo and one fewer tool to install is one fewer thing
# that is missing at the moment you need the guardrail.
#
# NOT VERIFIED against a live account. The `scw billing` verbs and the field
# names in the MATCHED ON comments below are written from the documented CLI
# surface, not from a run. Check them against `scw billing budget list -o json`
# on your account before trusting this.

set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

: "${BUDGET_AMOUNT:?set BUDGET_AMOUNT — the monthly ceiling in EUR, e.g. 50}"
: "${ALERT_THRESHOLD:?set ALERT_THRESHOLD — the EUR figure at which the alert fires, e.g. 40}"
BUDGET_NAME="${BUDGET_NAME:-localchat-test-stack}"
WEBHOOK_URL="${WEBHOOK_URL:-}"

command -v scw >/dev/null 2>&1 || die "scw not found on PATH"
PYTHON=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PYTHON="$c"; break; fi
done
[[ -n "$PYTHON" ]] || die "no python3 on PATH"

# A stray command against the wrong project is the failure mode a profile prevents.
PROFILE_ARGS=()
if [[ -n "${SCW_PROFILE:-}" ]]; then
  PROFILE_ARGS=(--profile "$SCW_PROFILE")
fi

scw_json() { scw "${PROFILE_ARGS[@]}" "$@" -o json; }

# Prints the id of the first row whose fields all match, or nothing if no row
# does. Compares stringified values, so a threshold of 40 matches whether the
# API reports it as a number or a string. Exits non-zero — never "no match" —
# when the reply is unreadable.
read -r -d '' PICK_ID <<'PY' || true
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
if not isinstance(rows, list):
    sys.exit("reply was not a JSON array")
criteria = [arg.split("=", 1) for arg in sys.argv[1:]]
for row in rows:
    if not isinstance(row, dict):
        sys.exit("reply contained a non-object entry")
    if all(str(row.get(key)) == value for key, value in criteria):
        print(row.get("id", ""))
        break
PY

# lookup_id <field=value>... -- <scw args>...
lookup_id() {
  local criteria=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do criteria+=("$1"); shift; done
  shift
  local raw found
  if ! raw=$(scw_json "$@" 2>&1); then
    die "'scw $*' failed, so existence could not be established:"$'\n'"$raw"
  fi
  # An unreadable answer must never be read as "does not exist" — that is
  # precisely what would create the duplicate.
  if ! found=$(printf '%s' "$raw" | "$PYTHON" -c "$PICK_ID" "${criteria[@]}" 2>&1); then
    die "could not read the reply to 'scw $*' ($found); refusing to create blind:"$'\n'"$raw"
  fi
  printf '%s' "$found"
}

echo "Budget '$BUDGET_NAME':"
# MATCHED ON: .name
budget_id=$(lookup_id "name=$BUDGET_NAME" -- billing budget list)

if [[ -n "$budget_id" ]]; then
  note "exists ($budget_id) — not creating a second one"
else
  note "absent — creating with a ${BUDGET_AMOUNT} EUR ceiling"
  budget_id=$(scw_json billing budget create \
    name="$BUDGET_NAME" \
    amount="$BUDGET_AMOUNT" \
    | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
  [[ -n "$budget_id" ]] || die "budget creation returned no id"
  note "created ($budget_id)"
fi

echo "Alert at ${ALERT_THRESHOLD} EUR:"
# MATCHED ON: .budget_id + .threshold. Two thresholds on one budget are a
# legitimate configuration; the same threshold twice is the duplicate.
alert_id=$(lookup_id "budget_id=$budget_id" "threshold=$ALERT_THRESHOLD" \
  -- billing budget-alert list)

if [[ -n "$alert_id" ]]; then
  note "exists ($alert_id) — not creating a second one"
else
  note "absent — creating"
  alert_id=$(scw_json billing budget-alert create \
    budget-id="$budget_id" \
    threshold="$ALERT_THRESHOLD" \
    | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
  [[ -n "$alert_id" ]] || die "alert creation returned no id"
  note "created ($alert_id)"
fi

echo "Webhook notification:"
if [[ -z "$WEBHOOK_URL" ]]; then
  note "WEBHOOK_URL unset — skipping. The alert still notifies by whatever the"
  note "account has configured, which is email/SMS: a person reacting, not a"
  note "script. §11 is why the webhook is the half that stops the burn."
else
  # MATCHED ON: .budget_alert_id. A second notification on one alert double-fires.
  notif_id=$(lookup_id "budget_alert_id=$alert_id" \
    -- billing budget-alert-notification list)
  if [[ -n "$notif_id" ]]; then
    note "exists ($notif_id) — not creating a second one"
    note "to point it elsewhere, delete it first; this never updates in place"
  else
    note "absent — creating for $WEBHOOK_URL"
    notif_id=$(scw_json billing budget-alert-notification create \
      budget-alert-id="$alert_id" \
      webhook-urls.0="$WEBHOOK_URL" \
      | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
    [[ -n "$notif_id" ]] || die "notification creation returned no id"
    note "created ($notif_id)"
  fi
fi

echo
echo "Done. This is an alert, not a cap — it is an estimate, it lags the real"
echo "invoice, and nothing stops spend on its own. See §11."
