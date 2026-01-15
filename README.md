# ?? LocalChat - Professional RAG Application

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-664%20passing-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-67--72%25-green)](htmlcov/)
[![Code Quality](https://img.shields.io/badge/code%20quality-refactored-blue)](docs/)

A production-ready Retrieval-Augmented Generation (RAG) application built with Flask, Ollama, PostgreSQL (pgvector), and Redis. Features comprehensive document processing, PDF table extraction, intelligent chunking, streaming responses, and accurate context-based answers.

---

## ? Features

### ?? Core Capabilities
- **?? Document Processing**: PDF, DOCX, TXT, Markdown with advanced table extraction
- **?? RAG Pipeline**: Intelligent retrieval with hybrid search (semantic + BM25)
- **?? Chat Interface**: Real-time streaming responses with document context
- **?? Vector Search**: Lightning-fast similarity search using pgvector HNSW
- **?? Table Extraction**: Advanced PDF table detection and preservation
- **??? Duplicate Prevention**: Smart document fingerprinting
- **? Input Validation**: Pydantic models with comprehensive sanitization
- **? Caching Layer**: Redis/Memory cache for embeddings and queries
- **?? Streaming Responses**: Server-Sent Events for real-time feedback
- **?? Security**: Rate limiting, CORS support, JWT authentication ready

### ?? Quality Assurance
- **334 Tests**: Comprehensive test coverage
- **26%+ Coverage**: 90-100% on critical modules
- **Type Safety**: 100% type hints
- **Documentation**: Extensive inline and standalone docs
- **CI/CD Ready**: GitHub Actions configuration
- **Error Handling**: Professional exception system with context preservation

### ?? Performance Features
- **Hybrid Search**: Combines semantic similarity with BM25 keyword matching
- **Multi-level Caching**: 
  - Embedding cache (5000 capacity)
  - Query cache (1000 capacity)
  - Configurable TTL
- **Efficient Indexing**: HNSW for fast approximate nearest neighbor search
- **Smart Chunking**: Context-aware with table preservation
- **Reranking**: Multi-signal fusion for improved relevance

---

## ?? Table of Contents

- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Architecture](#-architecture)
- [Usage](#-usage)
- [Project Structure](#-project-structure)
- [Documentation](#-documentation)
- [Testing](#-testing)
- [Configuration](#-configuration)
- [Development](#-development)
- [Contributing](#-contributing)
- [License](#-license)

---

## ?? Quick Start

```bash
# 1. Clone repository
git clone https://github.com/jwvanderstam/LocalChat
cd LocalChat

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up PostgreSQL with pgvector
# See docs/INSTALLATION.md for details

# 4. (Optional) Start Redis for caching
redis-server
# Or use memory cache (default)

# 5. Start Ollama
ollama serve

# 6. Run application
python app.py

# 7. Open browser
# http://localhost:5000
```

---

## ??? Architecture

### System Components

```
???????????????????????????????????????????????????????????????
?                     LocalChat RAG System                     ?
???????????????????????????????????????????????????????????????
?                                                               ?
?  ????????????????    ????????????????    ????????????????  ?
?  ?   Web UI     ?????? Flask API    ??????  Services    ?  ?
?  ?  (Browser)   ??????  (Routes)    ??????   Layer      ?  ?
?  ????????????????    ????????????????    ????????????????  ?
?                             ?                    ?            ?
?                             ?                    ?            ?
?  ????????????????????????????????????????????????????????   ?
?  ?              Application Core                         ?   ?
?  ????????????????????????????????????????????????????????   ?
?  ?                                                        ?   ?
?  ?  ??????????????  ??????????????  ??????????????     ?   ?
?  ?  ? RAG Engine ?  ?   Cache    ?  ?   Security ?     ?   ?
?  ?  ?  - Hybrid  ?  ? - Redis    ?  ? - Rate     ?     ?   ?
?  ?  ?    Search  ?  ? - Memory   ?  ?   Limit    ?     ?   ?
?  ?  ?  - Rerank  ?  ? - TTL      ?  ? - CORS     ?     ?   ?
?  ?  ??????????????  ??????????????  ??????????????     ?   ?
?  ?                                                        ?   ?
?  ?  ??????????????  ??????????????  ??????????????     ?   ?
?  ?  ? Document   ?  ?   Ollama   ?  ? Monitoring ?     ?   ?
?  ?  ? Processor  ?  ?   Client   ?  ? - Metrics  ?     ?   ?
?  ?  ? - Extract  ?  ? - LLM      ?  ? - Health   ?     ?   ?
?  ?  ? - Chunk    ?  ? - Embed    ?  ? - Logs     ?     ?   ?
?  ?  ??????????????  ??????????????  ??????????????     ?   ?
?  ?                                                        ?   ?
?  ??????????????????????????????????????????????????????????  ?
?                             ?                    ?            ?
?                             ?                    ?            ?
?  ????????????????    ????????????????    ????????????????  ?
?  ?  PostgreSQL  ?    ?    Ollama    ?    ?    Redis     ?  ?
?  ?  + pgvector  ?    ?   (LLM API)  ?    ?  (Optional)  ?  ?
?  ?  - Documents ?    ? - Embeddings ?    ?  - Caching   ?  ?
?  ?  - Chunks    ?    ? - Generation ?    ?  - Sessions  ?  ?
?  ?  - Vectors   ?    ????????????????    ????????????????  ?
?  ????????????????                                            ?
?                                                               ?
?????????????????????????????????????????????????????????????????
```

### Data Flow

```
Document Upload:
  Upload ? Validate ? Extract Text ? Detect Tables ? 
  Smart Chunk ? Generate Embeddings ? Store in DB ? 
  Update Cache

RAG Query:
  Query ? Cache Check ? Generate Query Embedding ?
  Hybrid Search (Semantic + BM25) ? Retrieve Chunks ?
  Rerank Results ? Format Context ? LLM Generation ?
  Stream Response ? Cache Result

Cache Strategy:
  - Embedding Cache: 7 days TTL, 5000 capacity
  - Query Cache: 1 hour TTL, 1000 capacity
  - LRU eviction for memory cache
  - Redis fallback to memory cache
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | HTML, CSS, JavaScript | Web interface |
| **Backend** | Flask 3.0 | Web framework |
| **Database** | PostgreSQL 15+ | Document storage |
| **Vector DB** | pgvector | Similarity search |
| **Cache** | Redis / Memory | Performance optimization |
| **LLM** | Ollama | Local inference |
| **Embeddings** | nomic-embed-text | Vector generation |
| **Validation** | Pydantic 2.12 | Input validation |
| **Testing** | pytest | Test framework |

---

## ?? Documentation

### User Guides
- **[Installation Guide](docs/INSTALLATION.md)** - Complete setup instructions
- **[Setup Guide](docs/SETUP_GUIDE.md)** - Configuration and setup
- **[User Manual](docs/README_OLD.md)** - How to use the application
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

### Developer Guides
- **[Development Guide](docs/DEVELOPMENT.md)** - Contributing and development
- **[API Documentation](docs/API.md)** - API endpoints and usage
- **[Architecture](docs/ARCHITECTURE.md)** - System design and components

### Feature Documentation
- **[RAG System](docs/features/RAG_HALLUCINATION_FIXED.md)** - RAG implementation
- **[PDF Tables](docs/features/PDF_TABLE_EXTRACTION.md)** - Table extraction
- **[Duplicate Prevention](docs/features/DUPLICATE_PREVENTION.md)** - Smart detection

### Testing Documentation
- **[Testing Guide](docs/testing/TESTING_GUIDE.md)** - How to write tests
- **[Coverage Report](docs/testing/COMPLETION_REPORT.md)** - Test coverage details
- **[Test Strategy](docs/testing/IMPLEMENTATION_PLAN.md)** - Testing approach

---

## ?? Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific category
pytest tests/unit/
pytest tests/integration/

# Run specific test file
pytest tests/unit/test_rag.py

# Run with verbose output
pytest -v

# Run tests in parallel (if pytest-xdist installed)
pytest -n auto
```

### Test Coverage

```bash
# Generate coverage report
pytest --cov=src --cov-report=html

# View report
open htmlcov/index.html

# Or view in terminal
pytest --cov=src --cov-report=term
```

### Current Test Stats

- **Total Tests**: 334
- **Passing**: 323 (96.7%)
- **Coverage**: 26.35% overall
- **Critical Modules**: 90-100% coverage

---

## ?? Configuration

### Environment Variables

Create a `.env` file in the root directory (copy from `config/.env.example`):

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

# Redis Configuration (Optional)
export REDIS_ENABLED=False          # Set to True to enable Redis
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=                # Leave empty if no password

# Flask Configuration
export SECRET_KEY=your_secret_key_here
export JWT_SECRET_KEY=your_jwt_secret_here
export FLASK_ENV=production
export DEBUG=False

# Security Configuration
export RATELIMIT_ENABLED=True
export RATELIMIT_CHAT=10 per minute
export RATELIMIT_UPLOAD=5 per hour
export CORS_ENABLED=False
export CORS_ORIGINS=http://localhost:3000
```

### Cache Configuration

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

### RAG Configuration

Edit `src/config.py` to customize RAG behavior:

```python
# Chunking Configuration
CHUNK_SIZE = 1024              # Characters per chunk (increased for better context)
CHUNK_OVERLAP = 200            # Overlap between chunks (20%)
TABLE_CHUNK_SIZE = 3000        # Larger chunks for tables

# Retrieval Configuration
TOP_K_RESULTS = 40             # Initial candidates
MIN_SIMILARITY_THRESHOLD = 0.28  # Minimum similarity score
RERANK_TOP_K = 12              # Final results after reranking

# Hybrid Search
HYBRID_SEARCH_ENABLED = True   # Combine semantic + keyword search
SEMANTIC_WEIGHT = 0.70         # Weight for semantic similarity
BM25_ENABLED = True            # Enable BM25 keyword matching

# LLM Configuration
DEFAULT_TEMPERATURE = 0.0      # Zero temperature for factual responses
MAX_CONTEXT_LENGTH = 20000     # Increased context window
STREAM_RESPONSES = True        # Enable streaming

# Cache Configuration
EMBEDDING_CACHE_SIZE = 5000    # Max cached embeddings
EMBEDDING_CACHE_ENABLED = True # Enable embedding cache
EMBEDDING_TTL = 604800         # 7 days
QUERY_TTL = 3600              # 1 hour
```

### Performance Tuning

#### Database Optimization
```python
# Connection Pool
DB_POOL_MIN_CONN = 2
DB_POOL_MAX_CONN = 10
DB_POOL_TIMEOUT = 5

# HNSW Index Parameters
DB_SEARCH_EF = 100            # Higher = more accurate but slower
DB_INDEX_TYPE = 'hnsw'        # Use HNSW for fast ANN search
```

#### Processing Configuration
```python
# Parallel Processing
MAX_WORKERS = 8               # Concurrent threads
BATCH_SIZE = 32              # Embeddings batch size

# Table Extraction
KEEP_TABLES_INTACT = True     # Don't split tables across chunks
MIN_TABLE_ROWS = 3           # Minimum rows to detect as table
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for complete configuration options.

---

## ??? Development

### Setting Up Development Environment

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run code formatters
black src/ tests/
isort src/ tests/

# Run linters
pylint src/
mypy src/
```

### Code Quality Standards

- **Type Hints**: 100% (required)
- **Docstrings**: Google-style (required)
- **Test Coverage**: ?80% for new code
- **Linting**: Pass pylint, mypy, black
- **Documentation**: Update relevant docs

### Development Workflow

1. **Create feature branch**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Write code and tests**
   ```bash
   # Add tests first (TDD)
   pytest tests/unit/test_your_feature.py
   ```

3. **Check code quality**
   ```bash
   black src/ tests/
   pylint src/
   pytest --cov
   ```

4. **Commit and push**
   ```bash
   git add .
   git commit -m "feat: your feature"
   git push origin feature/your-feature
   ```

5. **Create pull request**

---

## ?? Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Guide

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Update documentation
6. Submit a pull request

### Code of Conduct

- Be respectful and inclusive
- Follow coding standards
- Write clear commit messages
- Add tests for new features
- Update documentation

---

## ?? Project Status

### Current Version: 0.3.1

**Phase**: Month 3 Complete + Critical Bug Fixes

**Milestones**:
- ? Month 1: Professional logging, type hints, docstrings
- ? Month 2: Validation, error handling, sanitization  
- ? Month 3: Testing infrastructure, 334+ tests
- ? Bug Fixes: Flask context errors, Redis configuration, dependency management
- ?? Month 4: Performance optimization (in progress)

### Recent Updates (v0.3.1 - January 2025)

#### ?? Critical Bug Fixes
- ? Fixed Flask application context errors in all streaming endpoints
  - Document upload progress streaming
  - Chat response streaming  
  - Model download progress streaming
- ? Fixed Redis authentication errors with configurable cache backend
- ? Fixed missing package dependencies (redis, flasgger)
- ? Improved error handling with graceful degradation

#### ?? New Features
- ? Added Redis caching support with automatic fallback to memory cache
- ? Implemented Server-Sent Events (SSE) for real-time streaming
- ? Added Swagger/OpenAPI documentation at `/api/docs/`
- ? Enhanced monitoring with metrics and health checks
- ? Improved cache management with separate TTLs for embeddings and queries

#### ?? Improvements
- ? Cleaned up project structure (removed 18 duplicate directories)
- ? Consolidated documentation into organized folders
- ? Updated .gitignore with comprehensive exclusions
- ? Added verification script for testing all fixes
- ? Improved logging throughout application

#### ?? Documentation
- ? Added comprehensive fix documentation
  - Flask context handling guide
  - Redis configuration guide
  - Complete error resolution summary
- ? Updated architecture diagram with Redis
- ? Enhanced README with cache configuration
- ? Added troubleshooting guides

### Previous Updates

#### v0.3.0 - December 2024
- ? Fixed RAG hallucination with strict prompts
- ? Enhanced PDF table extraction
- ? Implemented table-aware chunking
- ? Added comprehensive test suite
- ? Improved documentation structure
- ? Organized project structure

---

## ?? Troubleshooting

### Common Issues

**Issue**: RAG not retrieving documents
```bash
# Check if documents are uploaded
curl http://localhost:5000/api/documents/stats

# Test retrieval
curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
```

**Issue**: Ollama connection failed
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
ollama serve
```

**Issue**: Database connection error
```bash
# Check PostgreSQL is running
pg_isready

# Check pgvector extension
psql rag_db -c "SELECT * FROM pg_extension WHERE extname='vector';"
```

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more solutions.

---

## ?? License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ?? Acknowledgments

- **Ollama** for local LLM inference
- **pgvector** for vector similarity search
- **Flask** for web framework
- **Pydantic** for data validation
- **pytest** for testing framework

---

## ?? Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/jwvanderstam/LocalChat/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jwvanderstam/LocalChat/discussions)

---

## ??? Roadmap

### Month 4 (Planned)
- [ ] Performance optimization
- [ ] Caching layer
- [ ] Advanced query expansion
- [ ] Multi-language support

### Month 5 (Planned)
- [ ] Docker deployment
- [ ] Kubernetes configs
- [ ] Monitoring dashboard
- [ ] API rate limiting

### Month 6 (Planned)
- [ ] Advanced RAG techniques
- [ ] Fine-tuning support
- [ ] Plugin system
- [ ] Admin dashboard

---

## ? Star History

If you find this project useful, please consider giving it a star! ?

---

**Made with ?? by the LocalChat Team**

*Professional RAG application for document-based question answering*
