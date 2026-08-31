# LocalChat documentation

Organised with [Diátaxis](https://diataxis.fr/): every document does exactly one of four
jobs. Which one you need depends on what you are doing right now, not on the topic.

|  | You are **working** | You are **studying** |
|---|---|---|
| **Practical steps** | [How-to guides](#how-to-guides) — achieve a goal | [Tutorials](#tutorials) — learn by doing |
| **Theory** | [Reference](#reference) — look something up | [Explanation](#explanation) — understand why |

---

## Tutorials

*Learning-oriented: a guided first run where the outcome is guaranteed.*

- **[Quick start](../README.md#quick-start)** — clone, start the services, sign in, ask
  the first question.

## How-to guides

*Goal-oriented: you know what you want; these are the steps.*

| Guide | Use it when |
|---|---|
| [Deployment](DEPLOYMENT.md) | Running the stack with Docker Compose, TLS, secrets, upgrades |
| [Deployment on Scaleway](DEPLOYMENT_SCALEWAY.md) | Standing up a managed-cloud test stack — service mapping, cost ceilings, what is still unverified |
| [Operations](OPERATIONS.md) | Backup, restore, routine maintenance |
| [Migrations](MIGRATIONS.md) | Applying, writing or rolling back a schema change |
| [Workspace API keys](WORKSPACE_API_KEYS.md) | Giving a bot or workflow scoped access to one workspace |
| [Connect a Discord bot with n8n](n8n-discord-setup.md) | Wiring an external chat client to the API |
| [Integration tests](INTEGRATION_TESTS.md) | Running the suites that need real services |
| [Troubleshooting](TROUBLESHOOTING.md) | Something is broken and you need it working |

## Reference

*Information-oriented: precise, factual, structured for lookup rather than reading.*

| Document | Contents |
|---|---|
| [Configuration](CONFIGURATION.md) | Every environment variable, its default and effect |
| [Database schema](SCHEMA.md) | Tables, columns, indexes, ER diagram |
| [Route permissions](PERMISSIONS.md) | Minimum role per route, plus the public allowlist |
| [RAG settings](SETTINGS.md) | Per-parameter descriptions; source of truth for the Settings UI help text |
| [Module index](../.claude/rules/file-map.md) | Every file in the codebase and its role |
| API (Swagger) | Served live at `/api/docs/` |

## Explanation

*Understanding-oriented: why the system is the way it is.*

| Document | Question it answers |
|---|---|
| [Architecture decisions](ADR.md) | What was decided, and what would reopen it |
| [Lessons learned](LESSONS_LEARNED.md) | How the design got here, chronologically |
| [Roadmap](ROADMAP.md) | What is planned and in what order |
| [Production plan](PRODUCTION_PLAN.md) | What "production-ready" would require, and what is left |
| [Authentication plan](AUTH_PLAN.md) | How local login, OIDC and the bypasses fit together |
| [Test quality audit](TEST_QUALITY_AUDIT.md) | Why coverage percentage hid weak tests |
| [n8n integration report](bugreport-n8n-localchat.md) | What broke wiring the first external client |

## Contributor standards

Binding rules rather than documentation, but they belong in the map:

- [Project instructions](../CLAUDE.md) — the entry point for anyone, human or agent
- [Architecture rules](../.claude/rules/architecture.md) · [Python](../.claude/rules/python.md) · [Testing](../.claude/rules/testing.md) · [Plugin contract](../.claude/rules/plugins.md)
- [Security policy](../SECURITY.md) · [Plugin authoring](../plugins/README.md)

---

## Writing documentation here

Pick the quadrant **first**, then write. Most unclear documentation is a how-to guide with
explanation mixed in, or reference that stops to teach — each is readable alone and
confusing together.

- **Tutorial** — the reader is learning. Guarantee the outcome; do not offer choices.
- **How-to** — the reader has a goal. Steps only; link elsewhere for the reasoning.
- **Reference** — the reader is looking something up. Be complete, be dry, use tables.
- **Explanation** — the reader wants to understand. Give context, alternatives, and why
  the other option was rejected.

Prose follows the
[Google developer documentation style guide](https://developers.google.com/style):
second person, present tense, active voice, sentence case in headings.

Any document that states a fact about the code must be verifiable against the code. When
you change behaviour, update the document in the same commit — the file map and this index
included.
