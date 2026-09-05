# Configuration reference

**Reference.** Every environment variable LocalChat reads, with its default and effect.
Settings load once in [`src/config.py`](../src/config.py); nothing outside that file calls
`os.getenv`, so that file and this page are the whole surface.

Copy [`.env.example`](../.env.example) to `.env` and edit it. The RAG parameters are also
adjustable at runtime under **Settings** — [RAG settings](SETTINGS.md) explains what each
one does to retrieval quality.


## Environment variables

Create a `.env` file in the root directory (copy from `.env.example`):

```bash
# Database Configuration
export PG_HOST=localhost
export PG_PORT=5432
export PG_USER=postgres
export PG_PASSWORD=your_password
export PG_DB=rag_db
# TLS to the database. Default 'prefer' negotiates TLS and silently accepts an
# unencrypted connection if it fails — fine for a container on the same host.
# A managed database reached over the internet must set 'require' or stronger.
export PG_SSLMODE=prefer

# Ollama Configuration
# Host-run only. Under `docker compose up -d` the app service hardcodes
# OLLAMA_BASE_URL=http://ollama:11434, which overrides .env — see below.
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_DEFAULT_MODEL=llama3.2
export OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
# GPU layer offload: -1 = all layers on GPU (default), 0 = CPU only
export OLLAMA_NUM_GPU=-1

# Redis Configuration (Optional)
export REDIS_ENABLED=False          # Set to True to enable Redis
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=                # Leave empty if no password

# Application Configuration
export SECRET_KEY=your_secret_key_here
export JWT_SECRET_KEY=your_jwt_secret_here
export ADMIN_PASSWORD=your_admin_password_here  # Required for /api/auth/login
export APP_ENV=production
export DEBUG=False

# Security Configuration
export RATELIMIT_ENABLED=True
export RATELIMIT_CHAT=10 per minute
export RATELIMIT_UPLOAD=5 per hour
export TRUSTED_PROXY_IPS=              # Proxies allowed to set X-Forwarded-For

# Logging
export LOG_SINKS=console,file          # console | file | syslog
export LOG_MAX_BYTES=4194304           # rotation size; ceiling is
export LOG_BACKUP_COUNT=4              #   LOG_MAX_BYTES * (1 + LOG_BACKUP_COUNT) = 20 MB
export LOG_SYSLOG_ADDRESS=             # host:port or /dev/log, for the syslog sink
export LOG_SYSLOG_PROTOCOL=udp
export LOG_THIRD_PARTY_LEVEL=WARNING   # floor for httpx/huggingface/markdown chatter
export CORS_ENABLED=False
export CORS_ORIGINS=http://localhost:3000

# Observability
# Leave METRICS_TOKEN empty to allow unauthenticated Prometheus scraping
# (acceptable on a private network). Set a strong token in production.
export METRICS_TOKEN=
```

### Logging: sinks, rotation and shipping to a SIEM

`LOG_SINKS` decides where logs go — any of `console`, `file`, `syslog`, comma-separated.
The default is `console,file`.

| Sink | What it gives you |
|---|---|
| `console` | stdout/stderr, collected by the container runtime. **Does not survive container recreation** — `docker compose up -d --build` starts a new container and the old one's logs go with it. Records `INFO` and above. |
| `file` | The rotating local log. Survives recreation, and records `DEBUG` where the console records `INFO`, so it holds strictly more detail. This is the troubleshooting record, and the sink **Settings → Logs** reads. |
| `syslog` | Ships to a SOC/SIEM collector. Always emits JSON regardless of `LOG_FORMAT`, because a SIEM parses fields rather than prose. |

**Rotation is a security control, not housekeeping.** Log volume follows request volume,
and an attacker controls request volume — an unbounded log is a way to fill the disk. The
ceiling is explicit:

```
LOG_MAX_BYTES * (1 + LOG_BACKUP_COUNT)     # 4 MB * 5 = 20 MB by default
```

**Shipping to a SIEM.** Point `LOG_SYSLOG_ADDRESS` at the collector (`host:port`, or a
socket path such as `/dev/log`) and add `syslog` to `LOG_SINKS`:

```bash
LOG_SINKS=console,file,syslog
LOG_SYSLOG_ADDRESS=siem.internal:514
LOG_SYSLOG_PROTOCOL=tcp        # udp (default) or tcp
```

For destinations that ingest over HTTP rather than syslog — Splunk HEC, Loki, Elastic —
run a collector (Vector, Fluent Bit, Promtail) against the `console` sink instead. The
application deliberately does not push over HTTP itself: that needs buffering, retries,
backpressure and credential handling, and network I/O inside a logging handler can stall
the request path it is supposed to be observing.

**Third-party libraries are quietened to `WARNING`.** `httpx` narrates every request
the application makes and the markdown extension registry emits around 1275 records
per boot; together they were the bulk of the log file. That crowds out the
application's own records inside a bounded rotation, and their messages never pass
through this project's log sanitiser — `httpx` logs full URLs, query string included,
which is how third-party signed URLs reached the disk. `LOG_THIRD_PARTY_LEVEL=DEBUG`
gets it back while diagnosing one; their warnings and errors always come through.

**A sink that cannot be built is skipped, not fatal.** An unwritable log file, a refused
syslog connection or a typo'd sink name is reported at `ERROR` and startup continues with
whatever sinks remain. Losing a diagnostic channel is never a reason to stop serving —
before this, an unwritable `/app/logs/app.log` put the container into a restart loop.

### Rate limiting behind a reverse proxy

Rate limits are keyed on the client address, which the app takes from the socket
peer. Behind a reverse proxy that peer *is the proxy*, so without
`TRUSTED_PROXY_IPS` every caller shares one bucket — `RATELIMIT_LOGIN` stops
being a per-source defence against password guessing and becomes a single budget
one attacker can exhaust for everybody.

`TRUSTED_PROXY_IPS` is the list of peers whose `X-Forwarded-For` may be believed:
comma-separated addresses, CIDR ranges, or `*`. It is **empty by default**,
because honouring that header from an untrusted peer would let any caller forge
its own bucket. `docker-compose.nginx.yml` sets it, so the documented TLS path is
correct without you doing anything; set it yourself for any other proxy.

Note this is deliberately the *only* place proxy trust is configured — uvicorn is
started with `--forwarded-allow-ips ""` so its own default cannot disagree.

### Which of these the Docker stack actually reads

The supported deployment runs every component in Docker, and `docker-compose.yml`
sets some values in each service's `environment:` block. **Compose's `environment:`
beats `.env`**, so those particular variables cannot be changed by editing `.env`:

| Variable | In the compose stack | `.env` honoured? |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` (service name on the `backend` network) | No — set in compose |
| `PG_HOST` | `db` | No — set in compose |
| `REDIS_HOST` | `redis` | No — set in compose |

They matter for the host-run dev path (`python app.py`), which talks to the same
containers over published loopback ports. `db` publishes `127.0.0.1:5432` and
`ollama` publishes `${BIND_HOST:-127.0.0.1}:${OLLAMA_BIND_PORT:-11434}` for exactly
that reason — set `OLLAMA_BIND_PORT` if a natively installed Ollama already owns
11434.

To repoint a containerised service, change it in `docker-compose.yml` or supply an
override file — not in `.env`.

## Cache

LocalChat supports two caching backends:

#### Memory Cache (Default)
- **Pros**: No external dependencies, fast, simple setup
- **Cons**: Lost on restart, limited capacity, single-process only
- **Best for**: Development, testing, light loads

```bash
# Enable memory cache (default)
export REDIS_ENABLED=False
```

#### Redis Cache (Production)
- **Pros**: Persistent, distributed, large capacity
- **Cons**: Requires Redis server
- **Best for**: Production, high load, multi-process deployments

```bash
# Enable Redis cache
export REDIS_ENABLED=True
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=your_password  # Optional

# Start Redis
redis-server

# Or with Docker
docker run -d -p 6379:6379 redis:alpine
```

## RAG parameters

Core RAG parameters can be tuned **at runtime** in the Settings → RAG Parameters tab, or set via environment variables. Changes from the UI take effect immediately for all subsequent queries — no restart required.

| Parameter | Default | Env var | Range | Description |
|---|---|---|---|---|
| `TOP_K_RESULTS` | 30 | `TOP_K_RESULTS` | 10–50 | Initial retrieval candidate pool |
| `RERANK_TOP_K` | 12 | `RERANK_TOP_K` | 4–20 | Chunks passed to LLM after reranking |
| `DIVERSITY_THRESHOLD` | 0.70 | *(UI only)* | 0.50–0.90 | Jaccard threshold for near-duplicate filtering |
| `SEMANTIC_WEIGHT` | 0.70 | `SEMANTIC_WEIGHT` | 0.30–0.90 | Semantic vs. lexical blend in hybrid search |
| `RERANKER_ENABLED` | true | `RERANKER_ENABLED` | true/false | Neural cross-encoder re-ranking (see below) |

Parameters that require re-ingesting documents (chunk size, overlap) are set via environment variables only:

```bash
# Chunking — changing these requires re-uploading all documents
CHUNK_SIZE=1200          # Characters per chunk
CHUNK_OVERLAP=150        # Overlap between chunks (12.5%)

# Retrieval
TOP_K_RESULTS=30         # Initial candidates
RERANK_TOP_K=12          # Chunks sent to LLM

# Context window
OLLAMA_NUM_CTX=8192      # Token context window sent to Ollama
                         # MAX_CONTEXT_LENGTH defaults to OLLAMA_NUM_CTX × 3 chars

# Ingestion timeouts (supports files up to 15 MB)
OLLAMA_EMBED_TIMEOUT=600 # Seconds — worst-case 15 MB TXT ~280 s
UVICORN_TIMEOUT=600      # Must be >= OLLAMA_EMBED_TIMEOUT

# Cross-encoder reranker (enabled by default)
# RERANKER_ENABLED=false  # Disable on very slow / embedded hardware
```

> **Reranker:** LocalChat ships with the neural cross-encoder reranker **enabled by default** (`RERANKER_ENABLED=true`). It uses `cross-encoder/ms-marco-MiniLM-L-6-v2` (downloaded automatically, ~80 MB) to re-score each retrieved chunk against the query, substantially improving answer precision. The overhead is negligible on modern hardware — typically < 200 ms per query. Set `RERANKER_ENABLED=false` only if you are running on very constrained CPU hardware where the extra inference latency is unacceptable.

## Document capacity

LocalChat supports documents up to **15 MB** on CPU-only hardware:

| Format | Chunks @ 15 MB | DB size | Ingest time |
|--------|---------------|---------|-------------|
| TXT    | ~14,000       | ~160 MB | ~280 s      |
| DOCX   | ~8,000        | ~95 MB  | ~160 s      |
| PDF    | ~3,500        | ~40 MB  | ~70 s       |

Each chunk stores a 768-dim float32 embedding vector (~3 KB). The HNSW index scales to millions of chunks with sub-second query latency.

## Performance tuning

#### Database Optimization
```python
# Connection Pool
DB_POOL_MIN_CONN = 2
DB_POOL_MAX_CONN = 10

# HNSW Index Parameters
# ef_search is computed dynamically as max(TOP_K_RESULTS * 2, 40)
DB_INDEX_TYPE = 'hnsw'        # Use HNSW for fast ANN search
```

#### Processing Configuration
```python
# Parallel Processing
MAX_WORKERS = 8               # Concurrent threads
BATCH_SIZE = 512             # Embeddings batch size (512 chunks per call)

# Table Extraction
KEEP_TABLES_INTACT = True     # Don't split tables across chunks
MIN_TABLE_ROWS = 3           # Minimum rows to detect as table
```

---

## Complete environment variable reference

**Added 2026-08-27.** The sections above were written by hand and covered 45 of the 107
values `src/config.py` reads. The 65 below were reachable, documented nowhere, and include
the master switches for web search, tool calling, GraphRAG, MCP, plugins, model routing and
the cloud fallback — every one of them a feature you could not discover from this page.

Defaults are read from `src/config.py`; where a default is empty the feature is off or the
credential is absent. `src/config.py` remains the single source of truth — nothing else in
the codebase calls `os.getenv`.

> Under `docker compose up -d`, the `app` service's `environment:` block **overrides `.env`**
> for anything it sets. See [Which of these the Docker stack actually reads](#which-of-these-the-docker-stack-actually-reads).

### Feature switches

These turn whole subsystems on and off. Several default to `False`, so the feature is
absent unless you set it — which is the answer to "why is this doing nothing?".

| Variable | Default | Effect |
|---|---|---|
| `WEB_SEARCH_ENABLED` | `True` | DuckDuckGo live search as an LLM tool |
| `TOOL_CALLING_ENABLED` | `True` | The function-calling loop (`src/tools/`) |
| `QUERY_PLANNER_ENABLED` | `True` | Decomposes a query into a `QueryPlan` before retrieval |
| `GRAPH_RAG_ENABLED` | `False` | Entity extraction at ingest + 1-hop query expansion. **Requires spaCy's `en_core_web_sm`**; without it the flag is on and the feature is inert — the app warns at startup |
| `LONG_TERM_MEMORY_ENABLED` | `False` | Extracts durable facts from conversations and injects them into the prompt |
| `MODEL_ROUTER_ENABLED` | `false` | Rule-based routing to a model class per query |
| `AGGREGATOR_AGENT_ENABLED` | `false` | Parallel tool dispatch with retry and dedup |
| `MCP_ENABLED` | `false` | Talk to the domain MCP servers (`--profile mcp`) |
| `PLUGINS_ENABLED` | `True` | Load `.py` plugins from `PLUGINS_DIR` at startup |
| `DOCS_ENABLED` | `True` | The in-app `/docs` viewer and the Settings help text |
| `CLOUD_FALLBACK_ENABLED` | `false` | Fall back to a hosted model via LiteLLM when Ollama cannot serve |
| `REINGEST_ENABLED` | `false` | Re-ingest documents older than `REINGEST_MAX_AGE_HOURS` |
| `REDIS_STRICT` | `true` | Refuse to start if `REDIS_ENABLED=True` and Redis is unreachable, rather than silently falling back to the in-memory cache |
| `REQUIRE_DATABASE` | `false` | Refuse to start without PostgreSQL instead of degrading |

### Web search

| Variable | Default | Effect |
|---|---|---|
| `WEB_SEARCH_MAX_RESULTS` | `5` | Results requested per query |
| `WEB_SEARCH_TIMEOUT` | `10` | Seconds before a search is abandoned |
| `WEB_SEARCH_FETCH_PAGES` | `False` | Fetch and parse each result page rather than using the snippet |
| `WEB_SEARCH_MAX_PAGE_CHARS` | `2000` | Characters kept per fetched page |

### Models and routing

The `MODEL_*` values name the Ollama model for each class the router selects. All default
to empty, in which case the router falls back to the active model.

| Variable | Default | Effect |
|---|---|---|
| `DEFAULT_MODEL` | `llama3.1` | Model used when no active model has been set |
| `MODEL_FAST` / `MODEL_BASE` / `MODEL_LARGE` / `MODEL_CODE` / `MODEL_VISION` | *(empty)* | Ollama model id per routing class |
| `AGENT_MAX_RETRIES` | `1` | Retries per tool call in the aggregator |
| `TOOL_MAX_ROUNDS` | `5` | Maximum tool-call rounds before the loop stops |
| `GPU_BACKEND` | `auto` | `auto` / `nvidia` / `apple` / `cpu`. Forces the detection result (MM-1) |
| `MODEL_VRAM_HEADROOM_MB` | `1500` | VRAM left free when deciding whether a model fits |
| `SHARED_POOL_OS_RESERVE_MB` | `3000` | RAM reserved for the OS on shared-memory GPUs |
| `MODEL_ALLOW_OVERSIZED` | `false` | Permit loading a model the guard says will not fit |

### Cloud fallback

| Variable | Default | Effect |
|---|---|---|
| `CLOUD_PROVIDER` | *(empty)* | LiteLLM provider name |
| `CLOUD_MODEL` | *(empty)* | Model id at that provider |
| `CLOUD_API_KEY` | *(empty)* | Credential. Traffic on this path **leaves the machine** — the point of a local-first deployment is that it stays unset |

### MCP servers

| Variable | Default | Effect |
|---|---|---|
| `MCP_LOCAL_DOCS_URL` | `http://localhost:5001` | Local-docs server |
| `MCP_WEB_SEARCH_URL` | `http://localhost:5002` | Web-search server |
| `MCP_CLOUD_CONNECTORS_URL` | `http://localhost:5003` | Cloud-connectors server |
| `MCP_TIMEOUT` | `30` | Per-request timeout, seconds |
| `MCP_CIRCUIT_FAILURE_THRESHOLD` | `5` | Consecutive failures before the breaker opens |
| `MCP_CIRCUIT_RECOVERY_TIMEOUT` | `60` | Seconds the breaker stays open |

> The three URL defaults are **`localhost`**, which is right for a host-run app and wrong
> inside Compose, where the servers answer on their service names. The `mcp` profile sets
> them in `docker-compose.yml` — the same override rule as `OLLAMA_BASE_URL`.

### Retrieval, reranking and ingest

| Variable | Default | Effect |
|---|---|---|
| `RERANK_MIN_SCORE` | `-5.0` | Cross-encoder score below which a chunk is dropped |
| `RERANK_LOW_RELEVANCE_LIMIT` | `3` | Chunks kept when everything scores below the threshold |
| `RERANKER_WEIGHT` | `0.3` | The reranker score's share of the final blend |
| `RERANKER_MODEL_PATH` | `./models/reranker/latest` | Fine-tuned model directory; falls back to the base cross-encoder |
| `FEEDBACK_FINETUNE_MIN_PAIRS` | `50` | Feedback pairs required before a fine-tune run starts |
| `EMBEDDING_CONCURRENT_BATCHES` | `2` | Parallel embedding batches during ingest |
| `PDF_LOADER` | `auto` | PDF extraction backend |
| `REINGEST_MAX_AGE_HOURS` | `168` | Age at which a document is re-ingested (7 days) |

### Security and identity

| Variable | Default | Effect |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Username of the seeded administrator |
| `JWT_ACCESS_TOKEN_EXPIRES` | `7200` | Access-token lifetime in seconds (2 h) |
| `ENCRYPTION_KEY` | *(empty)* | Fernet key for encrypted columns. **Enforced at boot (SEC-4)** — production refuses to start without it |
| `TOKEN_ENCRYPTION_KEY` | *(empty)* | Fernet key for stored OAuth tokens |
| `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET` | *(empty)* | Entra app registration for SharePoint and OneDrive |
| `MICROSOFT_TENANT_ID` | `common` | Entra tenant |
| `MICROSOFT_REDIRECT_URI` | *(empty)* | OAuth callback URL |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | *(empty)* | Google OAuth client for Drive |
| `GOOGLE_REDIRECT_URI` | *(empty)* | OAuth callback URL |

### Rate limiting

`RATELIMIT_CHAT`, `RATELIMIT_UPLOAD` and `RATELIMIT_LOGIN` are covered above. The rest:

| Variable | Default | Effect |
|---|---|---|
| `RATELIMIT_GENERAL` | `60 per minute` | Default for routes with no specific limit |
| `RATELIMIT_MODELS` | `20 per minute` | Model list, pull and delete |

### Application

| Variable | Default | Effect |
|---|---|---|
| `APP_VERSION` | `3.0.0` | Reported by `GET /api/status`. See the note below |
| `MAX_CONTENT_LENGTH` | `16777216` | Upload ceiling in bytes (16 MB) |
| `LOG_FILE` | `logs/app.log` | Path for the file sink |
| `PLUGINS_DIR` | `plugins` | Directory scanned for plugins |
| `PRESENCE_TTL_SECONDS` | `30` | How long a workspace presence entry stays live |

> **`APP_VERSION` has three defaults, and they must be bumped together.** `src/config.py`,
> `docker-compose.yml`'s `${APP_VERSION:-...}`, and the row above all carry the number
> independently. Nothing derives it from the tag, so a release that bumps one and forgets
> the others produces a deployment that misreports its own version at `GET /api/status`.
>
> **That is not hypothetical — it is what happened.** Until 2026-08-31 the three read
> `1.0.0`, `0.5.0` and `1.0.0` against a `v3.0.0-beta.1` tag: a containerised deployment
> reported **0.5.0**, a host-run one **1.0.0**, and neither was the version being run.
> All three now read `3.0.0`, and `tests/unit/test_app_version_is_consistent.py` fails if
> they diverge again — the drift was silent precisely because no check compared them.
