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

## How to add an entry

One section per session, newest at the bottom. Record what was done, what was found that
the plan did not predict, and what it cost. An entry that only says what was done is a
changelog; the value is in the second part.

Read [§10b](DEPLOYMENT_SCALEWAY.md) before writing one: claims stated confidently and never
run are the specific failure this project has already made repeatedly, and a log entry is
another place to make it.
