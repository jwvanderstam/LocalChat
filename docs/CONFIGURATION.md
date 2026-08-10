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

# Ollama Configuration
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
export CORS_ENABLED=False
export CORS_ORIGINS=http://localhost:3000

# Observability
# Leave METRICS_TOKEN empty to allow unauthenticated Prometheus scraping
# (acceptable on a private network). Set a strong token in production.
export METRICS_TOKEN=
```

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
