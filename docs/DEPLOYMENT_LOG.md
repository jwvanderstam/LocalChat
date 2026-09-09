# Deployment log

A record of every session that touched the Scaleway deployment: what was done, what it
found, and what it cost. [DEPLOYMENT_SCALEWAY.md](DEPLOYMENT_SCALEWAY.md) is the plan and
the reference; this is the history of running it.

It exists because the stack is ephemeral. Deploy, test, destroy is the pattern, so nothing
in the account is evidence of what happened — the resources are gone by the time anyone
asks. Without a log, each rebuild starts from the same blank page the last one did.

> ## No secrets, ever
>
> **No key, password, token, connection string or secret value appears in this file**, and
> none may be added to it later. Incidents involving secrets are recorded by *what happened
> and what was done about it*, never by what the value was. Credentials live only in
> mode-600 files outside the repository, written by `provision.sh` and
> `deploy_container.sh`.
>
> Resource IDs, hostnames, prices and timings are fine, and are what make an entry useful.

---

## 2026-09-05 — first deployment

**Done.** Authenticated the CLI via browser SSO. Rewrote the billing guardrail against the
real CLI surface. Created the scoped project, the Serverless SQL Database and a
project-scoped IAM identity. Built and tested the cost kill switch. Deployed the container,
added a CPU Instance serving embeddings, and proved the document path end to end. Tore it
all down again.

**Found.**

| | |
|---|---|
| Half the `scw billing` surface the guardrail assumed | did not exist — no `budget-alert list`, and a budget has no name |
| `scw sdb`, and Terraform's `max_cpu = 15` default | wrong command; the CLI requires both CPU bounds, so the trap is Terraform-only |
| `hnsw.ef_search` through the pooler (§4's open caveat) | survives — the feared defect does not exist |
| TLS to the database | structural, not hardening: routing is by TLS SNI |
| "Retrieval works without Ollama" | false — ingest embeds through Ollama, so nothing is stored at all |
| The version endpoint | not on `/api/status`; it is admin-only on `/api/settings/stats` |
| `memory-limit-bytes` | needs a G/GB unit, not bytes |
| Compressed image size | 2.99 GB over 10 layers, of which one layer is 2.96 GB |
| GPU price | `L4-1-24G` is €0.787/h ≈ €575/month |

**Kill switch, first live run.** Five of six resources gone on the first pass; the private
network refused because deletes release their network attachments asynchronously. It named
the survivor and exited non-zero, which is the design. A retry was added afterwards.

**Cost.** €0.13 for the whole exercise.

---

## 2026-09-06 — hardening, automation, and a rerun

**Done.** Fixed two generic application defects the deployment exposed. Scripted phases 2
to 4 from what the manual run actually did. Gave the landing host TLS and a security group
of its own. Rebuilt the entire stack from nothing using only the scripts, which is what
exposed the rest of this entry.

**Application defects fixed.**

- `/api/health` echoed a boot-time flag and reported the database healthy through a total
  outage. It now probes the pool, cached for five seconds.
- The connection pool handed out connections the server had already closed. Reproduced by
  idling: the first request failed after 2.8 s, a second in 0.22 s, and recovery came
  minutes later with no intervention. Fixed by checking a connection on checkout.
- Staged uploads outlived an interrupted ingest. `UPLOAD_FOLDER` is a staging area, not a
  store — a correction to an earlier claim in this project's own documentation that
  uploads were lost on restart and needed object storage. They are not, and it does not.

**Script defects, all found by running from nothing.**

- **A failure path published six secrets.** `scw` takes secrets as command arguments, and
  the error handler printed the failing command. One transient-state rejection disclosed
  every application secret and the database credential. **All were rotated immediately.**
  The error path now redacts them; the underlying exposure through the process table is
  documented in §10c and accepted for a single-operator laptop, not for shared CI.
- The credential file went stale when a database was recreated while its key survived. The
  summary printed the new host and the file kept the old one — the worst combination,
  because nothing looks broken until a deployment cannot connect.
- `deploy_embeddings.sh` raced itself, issuing a second container update while the first
  was still applying.

**Landing host.** `atospoc.solbyco.nl` served a placeholder over plain HTTP on Scaleway's
Default security group, which accepts all inbound — port 22 open to the internet. Now:
Let's Encrypt with renewal proven by dry-run, and a security group allowing 80 and 443
publicly with SSH from the operator's address alone. Enforcement on the running instance
was verified by listening on an unlisted port and confirming it unreachable.

**The UI was unusable, and the assets were fine.** `/static/css/style.css` returned 200,
`text/css`, 37012 bytes over HTTPS — while the page asked for it over `http`. Starlette's
`url_for` builds an absolute URL from the request, and behind TLS termination that is
`http`, which browsers block as mixed content. Every stylesheet and every script refused;
the "Loading…" that never resolved was the same cause, since the JavaScript never ran.
Fixed by referencing same-origin assets root-relative, which needs no proxy trust at all.

**Kill switch, second live run.** Clean, exit 0 — and the private network deleted itself on
attempt three, so the retry added after the first run did its job unattended.

---

## 2026-09-08 — a stack found running, and a rebuild from the scripts

**Done.** Found the 2026-09-06 stack still standing and still billing. Tore it down with
the kill switch, rebuilt the whole thing from the three scripts onto the current `main`
build, verified it end to end, and ran the rate-limiting check §11 had been carrying since
the plan was written. Then found chat broken on the running stack, traced it to a defect in
the application, wrote it up, and tore the stack down.

**Found.**

| | |
|---|---|
| The previous session's stack | **still running**, 35 hours after this log recorded a clean teardown. The teardown happened; the rebuild that followed it was never written down |
| `deploy_embeddings.sh` | **silently rolled the container back to the default image tag.** Phase 4 rewires the container by re-running Phase 2, passing it two variables — every other knob, `DEPLOY_IMAGE_TAG` among them, fell back to Phase 2's default of `3.0.0`. The inner run is redirected to `/dev/null`, so nothing said so |
| `verify_deployment.py`'s image check | **cannot see that.** `app_version` is `3.0.0` in every build since the tag, so "deployed image is the expected one" passed against the wrong image |
| `X-Forwarded-For` at the edge (§7, §11) | **Everyone shares one bucket.** Measured, not inferred — see below |
| The kill switch, third live run | clean, exit 0. The Private Network again needed the retry, landing on attempt 3; the instance delete took its volume and its IP with it, so the later passes found nothing to do |
| The stale-credential fix | works. The database was recreated with a new host while its API key survived, and `provision.sh` reused the stored secret and rewrote the connection details — the exact combination that broke on 2026-09-06 |
| Chat, on the verified stack | **broken, and nothing said so.** An embedding model had been made the active chat model — see below |
| The mixed-content fix (#364) | holds in the real environment: `/login` on the deployed image references `/static/css/style.css` root-relative, where the `3.0.0` image emitted an absolute `http://` URL |

**The image revert, and why nothing caught it.** Phase 2 was deployed on `sha-359069a`,
Phase 4 reported success, and the container was afterwards running `3.0.0` — a release tag
four fixes behind `main`. Two independent guards should have caught it and neither could:
the deploy script prints nothing about the inner run, and the verifier's version check reads
`app_version`, which is a constant in `config.py` rather than anything derived from the
build. `deploy_embeddings.sh` now reads the deployed image and hands it back, prints what it
kept, and `tests/unit/test_deploy_scripts.py` asserts the update carries it. The verifier is
**deliberately left as it is**: over HTTP there is nothing to compare against, since the
application does not know which image it came from. Treat its version row as "an app
answered", not "the right build is deployed".

**The rate-limiting check (§11, §7).** 14 login attempts with one fixed
`X-Forwarded-For` gave 9 x 401 then 429 — the 10/min limit. Eight more with a rotating
header, and three with no header at all, stayed 429 throughout. A forged header therefore
buys nothing: `TRUSTED_PROXY_IPS` is empty on this deployment, so no `ProxyHeadersMiddleware`
is mounted and the limiter keys on Scaleway's ingress address for every caller. **D8's
shared-bucket failure mode is the live one**, which is the outcome §7 recommends accepting.

What the check does *not* settle is §7's other half — whether the edge would pass a forged
header through if the app were told to trust it. It cannot: with no proxy trusted, "the edge
stripped it" and "the app ignored it" look identical from outside. Settling that means
setting `TRUSTED_PROXY_IPS` deliberately and repeating the probe, which is worth doing only
if anyone proposes to fix the shared bucket that way.

**The billing guardrail warns at €20, not €40 — and until today it warned nobody at all.**
Two things about `budget-alert` that this session established:

- **`threshold` is a percentage.** Nothing renders a unit — the API returns a bare
  `"threshold": 40`, and `consumption_limit` comes back with an empty `currency_code` — so
  looking at it in the console or the API settles nothing. The constraint does:
  `threshold=101` and `threshold=150` are both refused with *"must be lower than or equal
  to 100"*. The guardrail created on 2026-09-05 therefore fires at 40% of €50 = **€20**,
  and this project's documentation called it €40 in five places for three days. Earlier and
  more conservative than intended, which is exactly why nobody noticed.
- **The alert had no notification at all** (`notifications: []`), so firing it would have
  produced nothing anywhere. `budget-alert-notification create` accepts
  `email-addresses` and `sms-phone-numbers` alongside `webhook-urls`; an email notification
  is now attached.

**The webhook is dropped, and the payload check with it.** The shape only matters to code
that parses it, and that code should not exist: a consumer that tears a stack down on an
unauthenticated POST is a liability, and a budget alert lags consumption by hours, so it can
never be the brake — `panic_teardown.sh` with a human in front of it is. Email needs no
endpoint, no public surface and no third party.

**Whether the alert actually delivers is still unproven.** A 1% alert (€0.50) against ~€5
of consumption, with email attached, produced no mail in 2 h 33 min. Two candidates, neither
established: the evaluation runs on a slow cadence, or an alert fires on a *crossing* and
one created above the line never fires at all. If it is the second, the guardrail is a
tripwire that must be armed before the spend — and this test was the wrong shape rather than
the notification being broken.

**Chat was broken, and the cause is in the application, not the deployment.** Every chat
request came back `{"error": "GenerationError", "message": "Failed to generate response"}`
while upload and retrieval worked and `/api/status` reported `ready: true`. The reason
appeared in one place only, the log:

```
ERROR src.ollama_client | Ollama API error 400: {"error":"\"nomic-embed-text:latest\" does not support chat"}
```

The active chat model *was the embedding model*. `_init_ollama_service()` picks an active
model at startup when none is set; `get_first_available_model()` filters embedding families
out and then — this is the defect — falls back to the unfiltered list when the filter leaves
nothing. Phase 4 pulls `nomic-embed-text` and deliberately nothing else, so the fallback is
guaranteed to fire on exactly the stack this project builds. It prefers a wrong answer to no
answer, and the wrong answer reaches the user as five opaque words.

Pulling `llama3.2:1b` afterwards did not fix it: the active model is chosen only when unset,
so it stayed on the embedding model. `POST /api/models/active` did fix it — the same
question then streamed tokens and cited the right chunks in 32 s.

Written up in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and beside Phase 4 in the plan.
**Not fixed in code** — the fix is a two-line change (drop the fallback, or refuse to make an
embedding model active) plus a decision about what the app should do when it has no model it
can chat with, and that decision is worth making deliberately rather than at the end of a
deployment session.

> *Fixed 2026-09-09, after this session.* The decision turned out to be already made and
> already in the code: `api_chat` returns a 400 `NoModelConfigured` naming the remedy when
> no model is active, and the fallback was the only thing routing past it. Dropping it was
> enough. `tests/unit/test_active_model_is_chat_capable.py` holds it. The operator note
> above still stands — a model pulled into a running instance is not selected automatically.

**A second thing the chat showed, and it is not a defect.** With `llama3.2:1b` active, the
model answered that the canary phrase "is not mentioned in the provided document" — while
the chunk containing it was the second source it cited. Retrieval did its job; a 1B model on
three vCPUs did not. That is Phase 5's question, and this is not the instrument for it.

**What was built, and then destroyed.**

```
project    localchat-test         986172ba-5b88-4fd0-8d6d-83ac3872a692
database   localchat              d68f9ef0-4e06-496f-b485-cd22b4ef3382   ready, scaled to zero
namespace  localchat              c69ca6ba-2047-44af-9380-c60312d3daea
container  localchat              d8af0eb1-5208-4982-821c-87289651a182   sha-359069a
endpoint   https://localchatc69ca6ba-localchat.functions.fnc.fr-par.scw.cloud
network    localchat-backend      307c667f-26f7-4da9-8f93-2dd5ea26db3b
security   localchat-ollama       49b8625d-d0fa-46e7-a036-d9a6572fb003   inbound drop
instance   localchat-embeddings   006b6a04-db91-43f2-b925-c96d17cf5658   DEV1-M, fr-par-2, 172.16.16.2
```

Every Phase 3 check passed on this stack, ingest and semantic retrieval included, and chat
worked once the active model was corrected by hand.

**Torn down at the end of the session, and it took two runs.** The instance, the namespace
and the database went on the first pass; the Private Network did not, and this time the
three bounded retries were *not* enough — the script named the survivor and exited 1, which
is the design. A second run deleted it and exited 0. Every resource type in the project then
listed zero. So three attempts at five seconds is the usual case, not a guarantee:
`PN_RETRIES` and `PN_RETRY_DELAY` exist for that, and re-running remains the first thing to
try. Nothing was billing while it retried — a Private Network is free.

**Cost.** EUR 1.48 in the project this billing period, covering the stack found running and
this DEV1-M 0.83, database 0.31, IPv4 0.21, block storage 0.06, containers 0.07. The
container line is small only because the Serverless Containers free tier absorbed 2.25 of
2.30 — and memory has now passed 400,000 GB-s, so the tier is spent for this month and the
next day of `min_scale=1` bills in full.

---

## How to add an entry

One section per session, newest at the bottom. Record what was done, what was found that
the plan did not predict, and what it cost. An entry that only says what was done is a
changelog; the value is in the second part.

Read [§10b](DEPLOYMENT_SCALEWAY.md) before writing one: claims stated confidently and never
run are the specific failure this project has already made repeatedly, and a log entry is
another place to make it.
