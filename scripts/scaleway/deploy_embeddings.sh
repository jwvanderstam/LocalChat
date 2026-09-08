#!/usr/bin/env bash
#
# Phase 4 of docs/DEPLOYMENT_SCALEWAY.md: an Ollama Instance that serves
# embeddings, so document ingest and retrieval work. Generation is Phase 5's
# question and belongs on a GPU.
#
# Idempotent: a second run finds the network, the security group and the
# instance, and re-wires the container to whatever private IP it has.
#
# Three decisions that came out of doing this by hand, each non-obvious:
#
#   * The security group sets `inbound-default-policy=drop`. Scaleway's default
#     is `accept`, which would put Ollama's port 11434 on the public internet.
#     The cost is that there is no SSH either — the serial console is the way in
#     if something goes wrong, and that is the right trade for a disposable box.
#   * The model is pulled through the application's own POST /api/models/pull,
#     not from cloud-init. The cloud-init pull failed silently on the first run
#     and left a box with zero models and no way in to find out why. Pulling
#     through the app is idempotent, streams its progress, and exercises the
#     private network that had to be proven anyway.
#   * Everything goes in fr-par-2, the one zone offering both the L4 and the
#     larger L40S — so Phase 5's GPU lands beside this box rather than in
#     another zone with a private network already wired.
#
# Usage:
#   bash scripts/scaleway/deploy_embeddings.sh
#
# Needs `scw` (authenticated), Python 3, and a container from deploy_container.sh.

set -euo pipefail

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

EMB_PROJECT_NAME="${EMB_PROJECT_NAME:-localchat-test}"
EMB_NETWORK_NAME="${EMB_NETWORK_NAME:-localchat-backend}"
EMB_SECGROUP_NAME="${EMB_SECGROUP_NAME:-localchat-ollama}"
EMB_INSTANCE_NAME="${EMB_INSTANCE_NAME:-localchat-embeddings}"
EMB_NAMESPACE="${EMB_NAMESPACE:-localchat}"
EMB_CONTAINER="${EMB_CONTAINER:-localchat}"
EMB_TYPE="${EMB_TYPE:-DEV1-M}"
EMB_IMAGE="${EMB_IMAGE:-ubuntu_jammy}"
EMB_ZONE="${EMB_ZONE:-fr-par-2}"
EMB_REGION="${EMB_REGION:-fr-par}"
EMB_MODEL="${EMB_MODEL:-nomic-embed-text}"
EMB_CLOUD_INIT="${EMB_CLOUD_INIT:-$(dirname "$0")/ollama-cloud-init.yaml}"

command -v scw >/dev/null 2>&1 || die "scw not found on PATH"
PYTHON=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PYTHON="$c"; break; fi
done
[[ -n "$PYTHON" ]] || die "no python3 on PATH"
[[ -f "$EMB_CLOUD_INIT" ]] || die "no cloud-init file at $EMB_CLOUD_INIT"

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
obj = obj.get(sys.argv[2], obj) if len(sys.argv) > 2 else obj
value = obj.get(sys.argv[1])
if value in (None, ""):
    sys.exit("reply carried no %s" % sys.argv[1])
print(value)
PY

# The private IPv4 the container will talk to. IPAM is the only place that knows
# it; the server object reports the NIC but not its address.
read -r -d '' PRIVATE_IP <<'PY' || true
import json, sys

sys.stdout.reconfigure(newline="\n")

want = sys.argv[1]
rows = json.load(sys.stdin)
if isinstance(rows, dict):
    rows = next((v for v in rows.values() if isinstance(v, list)), [])
for row in rows:
    resource = row.get("resource") or {}
    address = row.get("address", "")
    if resource.get("name") == want and ":" not in address:
        print(address.split("/")[0])
        break
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

echo "Project '$EMB_PROJECT_NAME':"
PROJECT_ID=$(find_by_name "$EMB_PROJECT_NAME" -- account project list)
[[ -n "$PROJECT_ID" ]] || die "project '$EMB_PROJECT_NAME' does not exist — run provision.sh"
note "$PROJECT_ID"

echo "Private network '$EMB_NETWORK_NAME':"
NETWORK_ID=$(find_by_name "$EMB_NETWORK_NAME" -- vpc private-network list \
  project-id="$PROJECT_ID" region="$EMB_REGION")
if [[ -n "$NETWORK_ID" ]]; then
  note "exists ($NETWORK_ID)"
else
  NETWORK_ID=$(scw_json vpc private-network create name="$EMB_NETWORK_NAME" \
    project-id="$PROJECT_ID" region="$EMB_REGION" | "$PYTHON" -c "$FIELD" id)
  note "created ($NETWORK_ID)"
fi

echo "Security group '$EMB_SECGROUP_NAME' (inbound drop):"
SECGROUP_ID=$(find_by_name "$EMB_SECGROUP_NAME" -- instance security-group list \
  project-id="$PROJECT_ID" zone="$EMB_ZONE")
if [[ -n "$SECGROUP_ID" ]]; then
  note "exists ($SECGROUP_ID)"
else
  SECGROUP_ID=$(scw_json instance security-group create name="$EMB_SECGROUP_NAME" \
    project-id="$PROJECT_ID" zone="$EMB_ZONE" \
    inbound-default-policy=drop outbound-default-policy=accept \
    description="Ollama embeddings: reachable on the private network, nowhere else" \
    | "$PYTHON" -c "$FIELD" id security_group)
  note "created ($SECGROUP_ID)"
fi

echo "Instance '$EMB_INSTANCE_NAME' ($EMB_TYPE, $EMB_ZONE):"
SERVER_ID=$(find_by_name "$EMB_INSTANCE_NAME" -- instance server list \
  project-id="$PROJECT_ID" zone="$EMB_ZONE")
if [[ -n "$SERVER_ID" ]]; then
  note "exists ($SERVER_ID)"
else
  SERVER_ID=$(scw_json instance server create name="$EMB_INSTANCE_NAME" \
    type="$EMB_TYPE" image="$EMB_IMAGE" zone="$EMB_ZONE" \
    project-id="$PROJECT_ID" security-group-id="$SECGROUP_ID" ip=new \
    cloud-init=@"$EMB_CLOUD_INIT" | "$PYTHON" -c "$FIELD" id)
  note "created ($SERVER_ID)"
  scw_json instance private-nic create server-id="$SERVER_ID" \
    private-network-id="$NETWORK_ID" zone="$EMB_ZONE" >/dev/null
  note "attached to the private network"
  scw "${PROFILE_ARGS[@]}" instance server start "$SERVER_ID" zone="$EMB_ZONE" >/dev/null 2>&1 || true
  note "powering on"
fi

for _ in $(seq 1 30); do
  STATE=$(scw_json instance server get "$SERVER_ID" zone="$EMB_ZONE" \
    | "$PYTHON" -c "$FIELD" state)
  [[ "$STATE" == "running" ]] && break
  sleep 10
done
note "state $STATE"
[[ "$STATE" == "running" ]] || die "instance did not reach 'running' (state: $STATE)"

PRIVATE=$(scw_json ipam ip list private-network-id="$NETWORK_ID" \
  | "$PYTHON" -c "$PRIVATE_IP" "$EMB_INSTANCE_NAME")
[[ -n "$PRIVATE" ]] || die "the instance has no private IPv4 yet — re-run in a moment"
note "private IP $PRIVATE"

echo "Wiring the container to http://$PRIVATE:11434:"
NAMESPACE_ID=$(find_by_name "$EMB_NAMESPACE" -- container namespace list \
  project-id="$PROJECT_ID" region="$EMB_REGION")
[[ -n "$NAMESPACE_ID" ]] || die "no namespace '$EMB_NAMESPACE' — run deploy_container.sh first"
CONTAINER_ID=$(find_by_name "$EMB_CONTAINER" -- container container list \
  namespace-id="$NAMESPACE_ID" region="$EMB_REGION")
[[ -n "$CONTAINER_ID" ]] || die "no container '$EMB_CONTAINER' — run deploy_container.sh first"

# Owning the whole definition cuts both ways: anything not passed to
# deploy_container.sh falls back to *its* defaults, and DEPLOY_IMAGE_TAG defaults
# to a release tag. Rewiring a container must not also roll its image back to
# that default, which is what this did until a stack deployed on an explicit tag
# came back reporting the release one. So the deployed image is read first and
# handed straight back. Any other non-default knob (memory, mvCPU) has the same
# shape; the image is the one that changes which code runs.
CURRENT_IMAGE=$(scw_json container container get container-id="$CONTAINER_ID" \
  region="$EMB_REGION" | "$PYTHON" -c "$FIELD" image) \
  || die "could not read the image deployed on container $CONTAINER_ID"

# One update, not two. Attaching the network separately and then re-running
# deploy_container.sh made Scaleway reject the second call outright:
# "transient state error for resource 'container' ... current_state: updating".
# deploy_container.sh owns the whole container definition anyway — an update
# replaces the environment map wholesale — so the network is handed to it.
DEPLOY_OLLAMA_URL="http://$PRIVATE:11434" DEPLOY_PRIVATE_NETWORK_ID="$NETWORK_ID" \
  DEPLOY_IMAGE="$CURRENT_IMAGE" \
  bash "$(dirname "$0")/deploy_container.sh" >/dev/null
note "container redeployed on the private network, with OLLAMA_BASE_URL set"
note "image kept at $CURRENT_IMAGE"

cat <<SUMMARY

Phase 4 is deployed.

  network   $EMB_NETWORK_NAME  $NETWORK_ID
  security  $EMB_SECGROUP_NAME  $SECGROUP_ID   inbound drop
  instance  $EMB_INSTANCE_NAME  $SERVER_ID   $PRIVATE

The instance is billing now (DEV1-M is about EUR 0.02/h). Tear it down when you
stop testing — see docs/COST_KILL_SWITCH.md.

Ollama has no model yet. Pull one through the application, which is idempotent
and the only path that does not need SSH:

  python scripts/scaleway/verify_deployment.py <endpoint> --pull-model $EMB_MODEL
SUMMARY
