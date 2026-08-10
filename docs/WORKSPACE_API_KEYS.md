# Workspace API Keys — a workspace as a chatbot endpoint

A workspace can be addressed programmatically by a key scoped to that workspace: a
Discord bridge through n8n, a Slack app, a scheduled report, a CLI. The key is the
principal — **not a user account borrowed by a machine**.

That distinction is the whole point. A bridge logging in as a person has a password
nobody resets, a session that expires mid-conversation, and an audit trail naming
someone who was asleep when the request happened. A key has none of those: it is
created, used, and revoked, and the log says `key_prefix=lcw_4Nto…` because that is
what actually made the call.

## Creating a key

**Settings -> Users -> Integrations -> New key.** Pick the workspace and the access
level, and the key appears once, with a copy button. That screen is the right home for
it: it answers "who can reach this workspace", and a key is one of the answers.

The key is shown exactly once — see below for why.

### From the API instead

Workspace **owner** or global admin, from the workspace's own endpoint:

```bash
curl -X POST http://localhost:5000/api/workspaces/<workspace-id>/keys \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"name": "discord-bridge", "role": "viewer"}'
```

```json
{
  "success": true,
  "key": "lcw_4NtoQval…",
  "info": { "id": "…", "name": "discord-bridge", "key_prefix": "lcw_4NtoQval", "role": "viewer" }
}
```

**The `key` field appears exactly once.** Only its hash and prefix are stored, so a
lost key is replaced, never recovered — the same rule as a password, for the same
reason.

`role` is `viewer` (read and chat) or `editor` (also upload and delete). `owner` is
deliberately not available: a key that can mint further keys turns one leaked
credential into permanent control of the workspace.

## Using a key

Either header works. Both are accepted because most webhook tools offer only an
`Authorization` field:

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Authorization: Bearer lcw_4NtoQval…" \
  -H "Content-Type: application/json" \
  -d '{"message": "What does the onboarding guide say about laptops?"}'

curl http://localhost:5000/api/documents/list \
  -H "X-API-Key: lcw_4NtoQval…"
```

The `lcw_` prefix is what distinguishes a key from a JWT, so the two never collide
on the `Authorization` header.

**You do not send `X-Workspace-ID`.** The key already names its workspace, and that
value wins over anything the client sends — see below.

## What a key can and cannot do

| | |
|---|---|
| Reach its own workspace | ✅ |
| Reach **any other** workspace | ❌ 403, whether asked via header, query or path |
| Exceed its role | ❌ 403 |
| Reach admin routes | ❌ 401 — a key is never a global admin |
| Survive revocation | ❌ 401 immediately |

### Why the workspace cannot be overridden

A key pins its workspace onto the request, and `get_workspace_id()` prefers that
over `X-Workspace-ID`. Two failures this prevents:

- **Widening.** A key for workspace A sending `X-Workspace-ID: B` is refused, rather
  than being handed B's documents.
- **Drifting.** A request that omits the header entirely would otherwise fall through
  to the *default* workspace downstream — authorised against A, answering from
  whichever workspace happens to be oldest. Pinning closes that silently-wrong path.

## Revoking

```bash
curl -X DELETE http://localhost:5000/api/workspaces/<workspace-id>/keys/<key-id> \
  -b cookies.txt
```

Effective immediately. The row is kept with `revoked_at` and `revoked_by` set —
Clark-Wilson soft-delete, so the audit trail survives the credential.

`GET /api/workspaces/<id>/keys` lists live keys with `key_prefix`, `role`,
`created_at` and `last_used_at`. It never returns a key or a hash. `last_used_at` is
the practical way to spot a key nothing uses any more.

## Wiring an n8n → Discord bridge

1. Create a key named after the bridge, role `viewer` unless it must upload.
2. Store it in n8n's credential store — not in the workflow JSON, which is usually
   exported and shared.
3. HTTP Request node: `POST http://<host>:5000/api/chat`, header
   `Authorization: Bearer lcw_…`, body `{"message": "<the Discord message>"}`.
4. Return `response` to Discord.

One key per bridge, named for the bridge. Two bridges sharing a key cannot be told
apart in the log, and revoking one revokes both.

## Where this fits architecturally

Per the plugin contract (`.claude/rules/plugins.md`), the core owns general
capabilities and consumers use them. "A workspace is programmatically addressable
with a scoped, revocable credential" passes the contract's own test — *would this be
reasonable if the requesting consumer vanished?* Slack, Teams, cron and n8n all want
it. A `discord_bridge` service would have been a leak; this is not.

When the plugin infrastructure lands (PC-1..PC-4), a chatbot plugin consumes this
capability rather than replacing it.
