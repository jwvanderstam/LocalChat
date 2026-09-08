# The cost kill switch

**Scaleway has no spend cap.** Not on the account, not on a project, not on a resource.
A budget alert is an estimate, it lags the invoice, and it stops nothing — it emails you.
This page is the thing that actually stops the burn, and you should read it *before* you
need it.

---

## The brake

Two commands. The first shows you what would go; the second does it.

```bash
# 1. What is billable in the LocalChat test project?
PROJECT_ID=986172ba-5b88-4fd0-8d6d-83ac3872a692 \
  bash scripts/scaleway/panic_teardown.sh

# 2. Stop it.
PROJECT_ID=986172ba-5b88-4fd0-8d6d-83ac3872a692 CONFIRM=DESTROY \
  bash scripts/scaleway/panic_teardown.sh
```

Without `CONFIRM=DESTROY` it only lists. The panic path is therefore: run it, read it,
run it again with the word. One token to remember, and no way to fire it by accident.

If a delete fails the sweep continues, and the survivors are named at the end with a
non-zero exit. Those you finish by hand in the console — a partial teardown that hides
what it missed is worse than none.

---

## What happened when it was tested

*Run in anger against the full test stack on 2026-09-05 — the first `CONFIRM=DESTROY`
ever executed. Six resources found, five gone on the first pass.*

```
deleted   instance localchat-embeddings (fr-par-2)
deleted   namespace localchat (fr-par)          <- takes its container with it
deleted   database localchat (fr-par)
FAILED    private network localchat-backend
          precondition failed: resource is still in use,
          Private Network must be empty to be deleted
```

Three things this settled, and one of them was worth the exercise on its own.

**`with-volumes` and `with-ip` work.** The block-volume and reserved-IP sections came back
*empty* — not skipped, but genuinely nothing left to find, because deleting the instance
had already taken them. That is the single most important property of this script, and it
had never been observed until this run.

**The private network failed on a race, not a design error.** A delete returns before the
deleted resource's network attachments are released, so the network was seconds away from
deletable when it was asked. A second run cleared it. The script now retries that one
level three times with a short delay — bounded, because an account that is burning cannot
wait forever, and free to retry, because a Private Network costs nothing.

**The failure was loud, which is the point.** It named the survivor, told the operator to
finish it by hand, and exited non-zero. A teardown that quietly leaves something behind is
worse than none — that is the whole design, and it held under a real failure.

> **Re-running is safe and is the first thing to try.** The second run reported
> *"Nothing billable found in this project"* and exited 0.

*Two further runs in anger, 2026-09-06 and 2026-09-08, both exited 0 unattended.* The
private network needed the retry each time — it succeeded on attempt three on both — so
that race is the normal case, not the exception, and the bounded retry is what turns it
back into a clean run. The volume and IP sections came back empty both times as well, which
is now three observations rather than one.

---

## Why it deletes instead of stopping

A stopped Instance is not a free Instance. Its block volumes bill at full price, and a
reserved flexible IP bills whether or not anything is attached to it. "Stop the server"
feels like the safe, reversible choice and is the reason people find a surprise on the
invoice a week later.

So the script deletes, and it deletes *with* the things that hide behind a server:

```bash
scw instance server delete server-id=<id> zone=<zone> \
  with-volumes=all with-ip=true force-shutdown=true
```

Drop `with-volumes` or `with-ip` and you have deleted the cheap part and kept the rest.

**This is only acceptable because nothing here is worth keeping.** The image redeploys
from a version tag, the data is test data, and the database is recreated by one command.
The moment that stops being true, this page needs rewriting — not ignoring.

---

## What bills, worst first

| What | Rate | Notes |
|---|---|---|
| **GPU Instance** `L4-1-24G` | **€0.787/h ≈ €575/month** | The only thing here that can produce a frightening number. At a €50 budget it burns the ceiling in about 3 days. |
| Serverless Container, min scale 1 | per-second while an instance is up | D2 keeps one warm on purpose; that is a deliberate cost, not a leak. |
| Serverless SQL Database | per CPU-second, `cpu_min = 0` | Scales to zero. Idle costs storage only. |
| Block volumes | per GB-hour, **attached or not** | Survives a naive server delete. |
| Flexible IP | per minute, **attached or not** | Same. |
| Private Network, budget, project, IAM | free | Deleted last, or not at all. |

---

## What is actually running right now

*Checked 2026-09-05.* Consumption for the current period was **€2.31 total**, and none of
it is LocalChat's:

| Project | What | Cost so far |
|---|---|---|
| `Test_Belgium_Atos` (default) | `poc-hello-world-par`, a **running** PLAY2-PICO at 212.47.234.196 | €1.60 |
| `Test_Belgium_Atos` | a flexible IP and a block volume | €0.71 |
| `localchat-test` | the `localchat` database, scaled to zero | €0.00 |

That PLAY2-PICO is **not part of this stack** and the kill switch will never touch it —
see below. It is listed here because "what is billing?" should have an answer you can
read, and because a small instance left running is how most cloud bills actually happen.

---

## What the brake deliberately does not cover

**The organisation's default project is refused outright.** `PROJECT_ID` equal to the
organisation id is rejected with no way to override it, because that project holds work
that is not ours — the PLAY2-PICO above. Emptying it is a different act from emptying a
scoped project, and it is not one a script should make easy.

That refusal is the reason the LocalChat stack lives in its own project. Scoping is not
tidiness; it is what makes a blunt instrument safe to swing.

**Object Storage is not swept.** `scw object bucket` exists and buckets bill for what
they store, but the script does not delete them — a bucket is the one thing in this stack
that might hold something you cannot regenerate. There are none today (`scw object bucket
list` returns `[]`); if that changes, delete them deliberately.

**Revoking an API key does not stop billing.** It stops new resources being created; it
does nothing about the ones already running. If your reflex under a runaway bill is to
kill the credentials, that reflex is wrong — and worse, it removes your own ability to
run the teardown.

---

## By hand, if the script is not available

Same order, most expensive first. `zone=all` and `region=all` work on every list.

```bash
P=986172ba-5b88-4fd0-8d6d-83ac3872a692

scw instance server list  zone=all   project-id=$P -o json   # then: server delete …
scw container namespace list region=all project-id=$P -o json # deleting the namespace
                                                              # removes its containers
scw sdb-sql database list region=all project-id=$P -o json
scw block volume list     zone=all   project-id=$P -o json
scw instance ip list      zone=all   project-id=$P -o json
scw vpc private-network list region=all project-id=$P -o json
```

The delete verbs take a single zone or region — the one the resource reported, not `all`.

---

## Verifying it stopped

```bash
scw billing consumption list -o json
```

**Consumption lags.** A zero here five minutes after a teardown means nothing; re-check
after an hour. What settles it immediately is the resource lists above coming back empty —
if nothing exists, nothing is billing, whatever the consumption endpoint says yet.

---

## Rebuilding afterwards

Teardown is cheap to reverse, which is the other half of why it is the right reflex:

```bash
scw sdb-sql database create name=localchat cpu-min=0 cpu-max=1 project-id=$P
```

Then redeploy the container from its version tag (never `latest` — see
[DEPLOYMENT_SCALEWAY.md §1](DEPLOYMENT_SCALEWAY.md)). The schema is recreated by the app's
own migration chain on first boot.

---

*The budget alert (§8 of the deployment guide) is the smoke detector: €50 ceiling, warning
at €40. This page is the fire extinguisher. Neither replaces the other, and only one of
them puts anything out.*
