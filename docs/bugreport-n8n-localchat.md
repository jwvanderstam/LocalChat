# Integration report: n8n → LocalChat → Discord

**Explanation.** What broke while wiring the first external client to the API, and what
each failure turned out to be. Two were configuration; the third was a defect in
LocalChat that had been hiding every validation message on `/api/chat`.

The working setup is [Connect a Discord bot to LocalChat with n8n](n8n-discord-setup.md).

## 1 — 401 "Authentication required"

**Symptom.** The HTTP Request node reported `Authorization failed - please check your
credentials`.

**Cause.** Authentication was set to "None", and an `X-Workspace-ID` header was being sent
instead of a credential.

**Resolution.** Generic Credential Type → Header Auth, with `Authorization: Bearer <key>`.
The `X-Workspace-ID` header was removed. **Fixed.**

## 2 — 401 "Invalid or revoked API key"

**Symptom.** With the credential in place, the error changed.

**Cause.** The key that had been pasted in was no longer valid.

**Resolution.** A new key, stored with the `Bearer ` prefix. **Fixed.**

## 3 — 500 on any `conversation_id` value

**Symptom.** Adding `conversation_id` to the body — intended to be empty for a new
conversation — produced:

```json
{ "success": false, "error": "InternalServerError", "message": "An unexpected error occurred" }
```

**Cause.** Confirmed server-side by reproduction: JSON `null` returned 200, `""` returned
500, and `"null"` returned 500.

The server never looked the conversation up. Validation worked and raised a 422 — building
that response is what failed. `exc.errors()` carries the originating `ValueError` object,
`JSONResponse` cannot serialise it, and the resulting `TypeError` escaped the handler and
became a generic 500.

**This was never specific to `conversation_id`.** Every rejected field on `/api/chat`
answered 500 "unexpected error" instead of naming the problem, which pointed the caller at
the server when the fix was in their request.

**Resolution** (PR #256):

1. Error details are built without the context object, so a rejected field returns a real
   422 with usable details.
2. An empty or whitespace `conversation_id` is read as "no conversation yet" and starts a
   new one.

The literal string `"null"` still returns 422. Silently starting a new conversation there
would drop the thread on every turn and look like the model forgetting. **Fixed.**

## Still open, on the n8n side

Per-conversation memory needs the client to store `conversation_id` per Discord channel or
thread and send it back. The field can now always be included, empty or not.

## What this cost, and why

The two authentication failures were self-describing and took minutes. The third took far
longer, because the message named the wrong side of the connection: a client-side mistake
was reported as a server fault, so the search started in the wrong place. An error that
misdirects is more expensive than an error that simply fails.
