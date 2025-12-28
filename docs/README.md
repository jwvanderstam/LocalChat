# ?? LocalChat - RAG-Powered Document Q&A System

<div align="center">

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)
![PostgreSQL](https://img.shields.io/badge/postgresql-15+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**A production-ready Retrieval-Augmented Generation (RAG) application for intelligent document question-answering using local LLMs.**

[Features](#-features) • [Quick Start](#-quick-start) • [Documentation](#-documentation) • [Architecture](#-architecture) • [Contributing](#-contributing)

</div>

---

## ?? Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Development](#-development)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## ?? Overview

LocalChat is an advanced RAG (Retrieval-Augmented Generation) application that allows you to chat with your documents using local LLMs. It combines the power of:

- **Ollama** for local LLM inference
- **PostgreSQL + pgvector** for efficient vector storage and similarity search
- **Flask** for a responsive web interface
- **Optimized chunking strategies** for better context preservation

### ?? Demo

```
User: "What are the main points in my contract?"
Assistant: Based on your contract.pdf, the main points are:
1. Term: 2 years starting January 2024
2. Salary: $120,000 per annum
3. Benefits: Health insurance, 401(k) matching
...
```

---

## ? Features

### Core Features
- ?? **Local LLM Integration** - Use Ollama models (Llama, Mistral, etc.)
- ?? **Document Processing** - Support for PDF, DOCX, TXT, MD files
- ?? **Intelligent Retrieval** - Vector similarity search with pgvector
- ?? **Streaming Responses** - Real-time streaming for better UX
- ?? **RAG Mode Toggle** - Switch between RAG and direct LLM chat
- ?? **System Overview** - Monitor models, documents, and system health

### Advanced Features
- ? **Optimized Chunking** - Hierarchical text splitting (512 chars, 100 overlap)
- ?? **Similarity Filtering** - Threshold-based result filtering (0.3 minimum)
- ?? **Result Re-ranking** - Hybrid scoring (70% similarity + 30% word overlap)
- ?? **File Type Filtering** - Search specific document types
- ?? **Connection Pooling** - Efficient database connection management
- ?? **Copy to Clipboard** - Export conversations easily
- ??? **Database Management** - Clear and re-ingest documents

### Developer Features
- ?? **Environment-based Config** - Secure configuration management
- ?? **Comprehensive Logging** - Structured logging for debugging
- ?? **Testing Support** - Unit and integration tests
- ?? **Docker Support** - Containerized deployment
- ?? **API Documentation** - Well-documented RESTful API
- ?? **Graceful Shutdown** - Clean connection closing

---

## ??? Architecture

### System Architecture

```
???????????????
?   Browser   ?
???????????????
       ? HTTP/SSE
       ?
???????????????????????????????????????
?          Flask Application          ?
?  ???????????????????????????????   ?
?  ?   API Layer (Routes)        ?   ?
?  ???????????????????????????????   ?
?             ?                       ?
?  ???????????????????????????????   ?
?  ?   Service Layer             ?   ?
?  ?  - Chat Service             ?   ?
?  ?  - Document Service         ?   ?
?  ?  - Model Service            ?   ?
?  ???????????????????????????????   ?
?             ?                       ?
?  ???????????????????????????????   ?
?  ?   Core Layer                ?   ?
?  ?  - RAG Engine               ?   ?
?  ?  - Database Manager         ?   ?
?  ?  - Ollama Client            ?   ?
?  ???????????????????????????????   ?
???????????????????????????????????????
       ?                    ?
       ?                    ?
????????????????    ????????????????
?   Ollama     ?    ? PostgreSQL   ?
?   + Models   ?    ? + pgvector   ?
????????????????    ????????????????
```

### Data Flow (RAG Pipeline)

```
Document Upload
    ?
    ?
Text Extraction
    ?
    ?
Hierarchical Chunking (512 chars, 100 overlap)
    ?
    ?
Embedding Generation (Ollama)
    ?
    ?
Vector Storage (pgvector)

Query Processing
    ?
    ?
Query Embedding
    ?
    ?
Similarity Search (cosine distance)
    ?
    ?
Result Filtering (similarity > 0.3)
    ?
    ?
Re-ranking (hybrid scoring)
    ?
    ?
Context Assembly
    ?
    ?
LLM Generation (with context)
    ?
    ?
Streaming Response
```

---

## ?? Prerequisites

### Required
- **Python 3.10+** - Programming language
- **PostgreSQL 15+** - Database with pgvector extension
- **Ollama** - Local LLM runtime

### Optional
- **Docker** - For containerized deployment
- **Redis** - For caching (future enhancement)
- **Nginx** - For reverse proxy in production

### System Requirements
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 20GB+ for models and documents
- **CPU**: 4+ cores recommended for parallel processing

---

## ?? Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/LocalChat.git
cd LocalChat
```

### 2. Install PostgreSQL with pgvector

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo apt install postgresql-15-pgvector
```

#### macOS
```bash
brew install postgresql@15
brew install pgvector
```

#### Windows
Download from [postgresql.org](https://www.postgresql.org/download/windows/)
Then install pgvector from [GitHub releases](https://github.com/pgvector/pgvector/releases)

### 3. Install Ollama

```bash
# Visit https://ollama.ai for installation instructions
# Or use:
curl https://ollama.ai/install.sh | sh

# Pull required models
ollama pull llama3.2          # Chat model
ollama pull nomic-embed-text  # Embedding model
```

### 4. Setup Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Unix/MacOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 5. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env  # or your preferred editor
```

**Minimum required settings:**
```env
PG_PASSWORD=your-postgresql-password
SECRET_KEY=your-random-secret-key
```

### 6. Initialize Database

```bash
# Start PostgreSQL service
# Windows: Check Services
# Linux: sudo systemctl start postgresql
# macOS: brew services start postgresql

# The application will auto-create the database on first run
# Or manually:
python scripts/setup_db.py
```

### 7. Run Application

```bash
python app.py
```

Visit: **http://localhost:5000**

---

## ?? Configuration

### Environment Variables

See `.env.example` for all available options. Key configurations:

#### Database
```env
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your-password
PG_DB=rag_db
```

#### RAG Tuning
```env
CHUNK_SIZE=512              # Characters per chunk
CHUNK_OVERLAP=100           # Overlap between chunks
TOP_K_RESULTS=10            # Number of chunks to retrieve
MIN_SIMILARITY_THRESHOLD=0.3  # Minimum similarity score
```

#### LLM Settings
```env
OLLAMA_DEFAULT_MODEL=llama3.2
OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
DEFAULT_TEMPERATURE=0.1     # Lower = more factual
```

### Performance Tuning

#### For Small Documents (< 10 pages)
```env
CHUNK_SIZE=400
TOP_K_RESULTS=5
```

#### For Large Documents (> 50 pages)
```env
CHUNK_SIZE=600
TOP_K_RESULTS=15
MAX_WORKERS=8
```

#### For Technical/Code Documents
```env
CHUNK_SIZE=300
CHUNK_SEPARATORS=\n\n,\n,.,;
```

---

## ?? Usage

### Web Interface

#### 1. Upload Documents
1. Navigate to **Document Management** (`/documents`)
2. Click "Choose Files"
3. Select PDF, DOCX, TXT, or MD files
4. Click "Upload & Process"
5. Wait for processing to complete

#### 2. Chat with Documents
1. Go to **Chat** (`/chat`)
2. Ensure "RAG Mode" toggle is **ON**
3. Ask questions about your documents
4. Get contextual answers with source citations

#### 3. Manage Models
1. Visit **Model Management** (`/models`)
2. View installed models
3. Pull new models from dropdown
4. Set active model for chat
5. Test model functionality

#### 4. System Overview
1. Check **Overview** (`/overview`)
2. Monitor system status
3. View performance metrics
4. Quick action links

### API Usage

#### Chat Endpoint
```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is in my documents?",
    "use_rag": true,
    "history": []
  }'
```

#### Upload Document
```bash
curl -X POST http://localhost:5000/api/documents/upload \
  -F "files=@document.pdf"
```

#### Test RAG Retrieval
```bash
curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "What is this about?"}'
```

See [API.md](docs/API.md) for complete API documentation.

---

## ?? Documentation

- **[API Documentation](docs/API.md)** - Complete API reference
- **[Architecture](docs/ARCHITECTURE.md)** - System design and components
- **[Development Guide](docs/DEVELOPMENT.md)** - Contributing and development
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

---

## ?? Testing

### Run Tests
```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests
pytest tests/integration/

# With coverage
pytest --cov=src --cov-report=html
```

### Test Configuration
```bash
# Use test database
export APP_ENV=testing
export PG_DB=rag_db_test

# Run tests
pytest
```

---

## ?? Deployment

### Docker Deployment

```bash
# Build image
docker build -t localchat:latest .

# Run with docker-compose
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Production Deployment

```bash
# Install production dependencies
pip install -r requirements.txt

# Set environment
export APP_ENV=production
export DEBUG=False

# Run with Gunicorn
gunicorn "app:create_app()" \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --worker-class sync \
  --timeout 120 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed instructions.

---

## ?? Troubleshooting

### Common Issues

#### RAG Not Working
```
Problem: No results found in RAG retrieval
Solution: 
1. Check if documents are uploaded
2. Verify embedding model is available: ollama list
3. Check console for [RAG] logs
4. Clear database and re-upload documents
```

#### Database Connection Failed
```
Problem: Unable to connect to PostgreSQL
Solution:
1. Verify PostgreSQL is running
2. Check credentials in .env
3. Test connection: psql -U postgres -c "SELECT version();"
```

#### Ollama Not Available
```
Problem: Cannot connect to Ollama
Solution:
1. Check if Ollama is running: curl http://localhost:11434
2. Start Ollama: ollama serve
3. Pull required models: ollama pull llama3.2
```

See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more solutions.

---

## ?? Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup
```bash
# Clone repository
git clone https://github.com/yourusername/LocalChat.git
cd LocalChat

# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Check code quality
flake8 src/
black src/ --check
mypy src/
```

### Code Style
- Follow PEP 8
- Use type hints
- Write docstrings
- Add tests for new features
- Update documentation

---

## ?? License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ?? Acknowledgments

- [Ollama](https://ollama.ai) - Local LLM runtime
- [pgvector](https://github.com/pgvector/pgvector) - Vector similarity search for PostgreSQL
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Bootstrap](https://getbootstrap.com/) - UI framework

---

## ?? Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/LocalChat/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/LocalChat/discussions)
- **Email**: support@localchat.local

---

## ??? Roadmap

### Version 1.1 (Q1 2025)
- [ ] Multi-user support with authentication
- [ ] Document versioning
- [ ] Custom prompt templates
- [ ] Export conversations as PDF

### Version 1.2 (Q2 2025)
- [ ] Multi-language support
- [ ] Voice input/output
- [ ] Mobile-responsive UI
- [ ] Plugin system

### Version 2.0 (Q3 2025)
- [ ] Support for cloud LLMs (OpenAI, Anthropic)
- [ ] Advanced analytics dashboard
- [ ] Document collaboration features
- [ ] API rate limiting and quotas

---

<div align="center">

**Built with ?? for the open source community**

[? Back to Top](#-localchat---rag-powered-document-qa-system)

</div>
