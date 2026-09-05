#!/usr/bin/env bash
#
# Scaleway cost guardrail: budget -> alert threshold -> optional webhook.
# See docs/DEPLOYMENT_SCALEWAY.md §8.
#
# Run this BEFORE the GPU instance exists. That instance is the line item the
# alert guards, and an alert created afterwards guards nothing that already burned.
#
# Terraform cannot express any of this — the Scaleway provider exposes billing as
# a read-only data source only. This runs alongside `terraform apply`, never
# inside it.
#
# Usage:
#   BUDGET_LIMIT=50 ALERT_THRESHOLD=40 [WEBHOOK_URL=https://...] \
#   [SCW_PROFILE=localchat-test] \
#     bash scripts/scaleway/bootstrap_billing_alert.sh
#
# Needs `scw` and Python 3 on PATH. Deliberately not jq — Python is already a
# hard dependency of this repo and one fewer tool to install is one fewer thing
# that is missing at the moment you need the guardrail.
#
# VERIFIED against `scw` 2.61.0 and a live account, 2026-09-05.
#
# `scw billing ... create` is not idempotent, and the read paths are lopsided:
# `budget-alert list` and `budget-alert-notification list` do not exist. What
# saves this is that `budget list` returns the whole tree — every budget with its
# `alerts[]`, and every alert with its `notifications[]`. One read establishes all
# three levels; that single call is why nothing here has to create blind.
#
# A budget carries no name (create takes only `consumption-limit` and `enabled`),
# so budgets are told apart by nothing at all. More than one is refused.

set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

: "${BUDGET_LIMIT:?set BUDGET_LIMIT — the monthly ceiling in account currency, e.g. 50}"
: "${ALERT_THRESHOLD:?set ALERT_THRESHOLD — the figure at which the alert fires, e.g. 40}"
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

# Never let a failed call read as "absent" — that is what would create a duplicate.
scw_json() {
  local raw
  if ! raw=$(scw "${PROFILE_ARGS[@]}" "$@" -o json 2>&1); then
    die "'scw $*' failed, so state could not be established:"$'\n'"$raw"
  fi
  printf '%s' "$raw"
}

# Reads the budget tree and reports the state of all three levels at once.
# Exits non-zero rather than reporting "absent" when the reply is unreadable.
read -r -d '' READ_STATE <<'PY' || true
import json, sys

# Windows text mode would emit CRLF here, and the CR survives into the
# shell variables read below, where it corrupts every id it is part of.
sys.stdout.reconfigure(newline="\n")

want = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
if not isinstance(rows, list):
    sys.exit("reply was not a JSON array")
for row in rows:
    if not isinstance(row, dict):
        sys.exit("reply contained a non-object entry")

print("budget_count=%d" % len(rows))
if len(rows) != 1:
    raise SystemExit(0)

budget = rows[0]
if not budget.get("id"):
    sys.exit("the budget carries no id")
print("budget_id=%s" % budget["id"])

# consumption_limit is {currency_code, units, nanos}, not a scalar.
limit = budget.get("consumption_limit")
if isinstance(limit, dict):
    print("budget_limit=%s" % limit.get("units", "?"))
else:
    print("budget_limit=%s" % (limit if limit is not None else "?"))

alerts = budget.get("alerts") or []
if not isinstance(alerts, list):
    sys.exit("alerts was not a list")
for alert in alerts:
    if not isinstance(alert, dict):
        sys.exit("an alert was not an object")
    # Thresholds arrive as numbers; compare as text so 40 and "40" both match.
    if str(alert.get("threshold")) == want:
        if not alert.get("id"):
            sys.exit("the matching alert carries no id")
        print("alert_id=%s" % alert["id"])
        print("alert_notified=%d" % (1 if alert.get("notifications") else 0))
        break
PY

raw=$(scw_json billing budget list)
if ! state=$(printf '%s' "$raw" | "$PYTHON" -c "$READ_STATE" "$ALERT_THRESHOLD" 2>&1); then
  die "could not read the budget list ($state); refusing to create blind:"$'\n'"$raw"
fi

budget_count=0; budget_id=""; budget_limit=""; alert_id=""; alert_notified=0
while IFS='=' read -r key value; do
  case "$key" in
    budget_count)   budget_count="$value" ;;
    budget_id)      budget_id="$value" ;;
    budget_limit)   budget_limit="$value" ;;
    alert_id)       alert_id="$value" ;;
    alert_notified) alert_notified="$value" ;;
  esac
done <<< "$state"

read -r -d '' READ_ID <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")
try:
    obj = json.load(sys.stdin)
except Exception as exc:
    sys.exit("reply was not JSON: %s" % exc)
if not isinstance(obj, dict) or not obj.get("id"):
    sys.exit("reply carried no id")
print(obj["id"])
PY

read_id() {
  local raw="$1" what="$2" out
  if ! out=$(printf '%s' "$raw" | "$PYTHON" -c "$READ_ID" 2>&1); then
    die "could not read the reply to $what ($out):"$'\n'"$raw"
  fi
  printf '%s' "$out"
}

echo "Budget:"
if [[ "$budget_count" -gt 1 ]]; then
  # Ambiguous by construction: with no name to match on, there is no way to tell
  # which of several budgets is this guardrail. Refusing beats guessing.
  die "$budget_count budgets exist and a budget has no name to tell them apart."$'\n'"Resolve by hand, then re-run."
elif [[ -n "$budget_id" ]]; then
  note "exists ($budget_id, limit $budget_limit)"
  if [[ "$budget_limit" == "$BUDGET_LIMIT" ]]; then
    note "limit already $BUDGET_LIMIT — leaving it alone"
  else
    note "changing the limit to $BUDGET_LIMIT"
    scw_json billing budget update budget-id="$budget_id" \
      consumption-limit="$BUDGET_LIMIT" enabled=true >/dev/null
  fi
else
  note "absent — creating with a $BUDGET_LIMIT ceiling"
  budget_id=$(read_id "$(scw_json billing budget create \
    consumption-limit="$BUDGET_LIMIT" enabled=true)" "budget create")
  note "created ($budget_id)"
fi

echo "Alert at $ALERT_THRESHOLD:"
if [[ -n "$alert_id" ]]; then
  note "exists ($alert_id) — not creating a second one"
else
  note "absent — creating"
  alert_id=$(read_id "$(scw_json billing budget-alert create \
    budget-id="$budget_id" threshold="$ALERT_THRESHOLD")" "budget-alert create")
  note "created ($alert_id)"
  alert_notified=0
fi

echo "Webhook notification:"
if [[ -z "$WEBHOOK_URL" ]]; then
  note "WEBHOOK_URL unset — skipping. The alert still notifies by whatever the"
  note "account has configured, which is email/SMS: a person reacting, not a"
  note "script. §8 is why the webhook is the half that stops the burn."
elif [[ "$alert_notified" -eq 1 ]]; then
  # The reply lists notifications but not their destinations, so "already
  # notified" is as far as this can tell. Repointing means deleting first.
  note "the alert already has a notification — not adding a second one"
  note "to point it elsewhere, delete it first; this never updates in place"
else
  note "creating for $WEBHOOK_URL"
  notif_id=$(read_id "$(scw_json billing budget-alert-notification create \
    budget-alert-id="$alert_id" webhook-urls.0="$WEBHOOK_URL")" \
    "budget-alert-notification create")
  note "created ($notif_id)"
fi

echo
echo "Done. This is an alert, not a cap — it is an estimate, it lags the real"
echo "invoice, and nothing stops spend on its own. See §8."
