# Connect a Discord bot to LocalChat with n8n

**How-to guide.** Forwards Discord messages through an n8n webhook to LocalChat's
`/api/chat`, parses the streaming response, and replies in the channel.

**Before you start:** a workspace API key. Create one in **Settings → Users →
Integrations → New key** — see [Workspace API keys](WORKSPACE_API_KEYS.md).

## The workflow

Webhook (Discord) → HTTP Request (LocalChat) → Code (SSE parser) → Send a message (Discord)

## Key point: the response is SSE, not JSON

`/api/chat` streams. The body is a sequence of text lines:

```
data: {"content": "..."}
data: {"done": true, "conversation_id": "...", "message_id": ..., "sources": [...]}
```

An HTTP Request node set to a JSON response fails on this. Set **Options → Response →
Response Format** to **Text**, with **Put Output in Field** set to `data`.

## 1. Create the credential

In n8n: **Credentials → New → Header Auth**

| Field | Value |
|---|---|
| Name | `Authorization` |
| Value | `Bearer <your-lcw_-key>` — keep the word `Bearer` |

`X-API-Key` with the bare key works too. Both are accepted, because most webhook tools
offer only one header field.

## 2. Configure the HTTP Request node

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | your internal LocalChat URL, for example `http://localchat-app-1:5000/api/chat` |
| Authentication | Generic Credential Type → Header Auth → the credential above |
| Send Body | on, JSON |
| Options → Response → Response Format | `Text` |
| Options → Response → Put Output in Field | `data` |
| Options → Timeout | `120000` — the first answer is slow while the model loads |

Body:

```json
{
  "message": "={{ $json.body.content }}",
  "use_rag": true,
  "conversation_id": "={{ $json.conversation_id }}"
}
```

**Do not send an `X-Workspace-ID` header.** The key already names its workspace and that
value wins over anything the client sends; sending the header caused conflicts here.

An empty `conversation_id` starts a new conversation, so the field can always be
included. This was not always true — see [the integration bug report](bugreport-n8n-localchat.md).

## 3. Parse the stream in a Code node

```js
const raw = $input.first().json.data;
let answer = '';
let done = null;
for (const line of raw.split('\n')) {
  if (!line.startsWith('data: ')) continue;
  const p = JSON.parse(line.slice(6));
  if (p.error) throw new Error(p.message);
  if (p.content) answer += p.content;
  if (p.done) done = p;
}
return [{ json: {
  answer,
  conversation_id: done?.conversation_id,
  sources: (done?.sources || []).map(s => s.filename),
}}];
```

## 4. Reply in Discord

Send `answer` back to the channel. Discord truncates at 2000 characters, so split or
shorten longer replies. `sources` holds the filenames the answer drew on, which works
well as a footnote.

## Common problems

**`localhost` does not reach LocalChat when n8n runs in Docker.** It resolves to the n8n
container itself. Use `http://host.docker.internal:5000`, or put n8n on the same compose
network and use the service address (`http://app:5000`, `http://localchat-app-1:5000`).
This is the most frequent cause of "connection refused".

**Per-conversation memory needs storage on the n8n side.** LocalChat returns a
`conversation_id`; keep it per Discord channel or thread (workflow static data is enough)
and send it with the next message. Without it, every message starts a new conversation.

**Testing.** Use "Debug in editor" against an existing execution to iterate on the HTTP
Request and Code nodes without sending a real Discord message. Running the node standalone
leaves it waiting on the Test URL.

## Getting help

If none of the above covers it, ask in the LocalChat Discord:
**https://discord.gg/QJVzvdFYje**

Bring the HTTP Request node's raw response — the SSE parsing problems in this guide are
much easier to diagnose from the actual body than from a description of it.
