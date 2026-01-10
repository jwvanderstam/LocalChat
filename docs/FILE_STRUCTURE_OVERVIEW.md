# ?? LocalChat - Complete File Structure Overview

## ?? **Quick Statistics**

| Metric | Count |
|--------|-------|
| **Total Files** | 100+ |
| **Source Files** | 12 Python modules |
| **Test Files** | 15+ test modules |
| **Documentation** | 50+ markdown files |
| **Templates** | 5 HTML pages |
| **Scripts** | 10+ utility scripts |

---

## ??? **Root Directory**

```
LocalChat/
??? app.py                  # Application launcher (entry point)
??? requirements.txt        # Python dependencies
??? pytest.ini             # Pytest configuration
??? .gitignore             # Git ignore rules
??? README.md              # Main documentation
??? .env                   # Environment variables (not in repo)
```

### **app.py** - Application Entry Point
**Purpose**: Main launcher for the Flask application  
**Function**: 
- Starts the web server
- Initializes all services
- Handles command-line startup

**Key Features**:
- Single entry point for the entire application
- Simple interface: `python app.py`
- Redirects to `src/app.py` for actual application logic

---

## ?? **src/ - Source Code**

Main application source code directory containing all Python modules.

### **Core Application Files**

#### **src/app.py** - Flask Web Application
**Lines**: ~800  
**Purpose**: Main Flask application with routes and API endpoints  
**Function**:
- Web routes (/, /chat, /documents, /models, /overview)
- REST API endpoints (/api/*)
- Request handling and response formatting
- Integration of all components

**Key Features**:
- ?? Web interface routes
- ?? REST API for chat, documents, models
- ?? Server-Sent Events (SSE) for streaming
- ??? Error handling with custom exceptions
- ? Input validation with Pydantic

**API Endpoints**:
```
GET  /                      ? Chat page
GET  /chat                  ? Chat interface
GET  /documents             ? Document management
GET  /models                ? Model management
GET  /overview              ? System overview

POST /api/chat              ? Chat with RAG or direct LLM
POST /api/documents/upload  ? Upload and process documents
GET  /api/documents/list    ? List all documents
POST /api/documents/test    ? Test retrieval
GET  /api/models            ? List available models
POST /api/models/active     ? Set active model
POST /api/models/pull       ? Pull new model
```

---

#### **src/config.py** - Configuration Management
**Lines**: ~200  
**Purpose**: Application configuration and state management  
**Function**:
- Load environment variables
- Define application constants
- Manage runtime state (active model, document count)

**Key Configuration**:
```python
# Database
PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB

# RAG Settings
CHUNK_SIZE = 512           # Chunk size in characters
CHUNK_OVERLAP = 128        # Overlap between chunks
TOP_K_RESULTS = 30         # Initial retrieval count
MIN_SIMILARITY_THRESHOLD = 0.35

# LLM Settings
DEFAULT_TEMPERATURE = 0.0  # For factual responses
MAX_CONTEXT_LENGTH = 4096

# Security (Week 1)
SECRET_KEY, JWT_SECRET_KEY
RATELIMIT_ENABLED, RATELIMIT_CHAT
```

**Classes**:
- `AppState`: Manages active model and document count

---

#### **src/db.py** - Database Layer
**Lines**: ~600  
**Purpose**: PostgreSQL database operations with pgvector support  
**Function**:
- Connection pooling (2-10 connections)
- Document and chunk CRUD operations
- Vector similarity search
- Database initialization and schema management

**Key Features**:
- ?? Connection pooling for efficiency
- ?? Vector similarity search (HNSW index)
- ?? Batch operations for performance
- ??? Transaction management
- ?? Statistics and diagnostics

**Main Methods**:
```python
initialize()                    # Setup database
insert_document()               # Add new document
insert_chunks_batch()           # Batch insert chunks
search_similar_chunks()         # Vector similarity search
search_similar_chunks_with_scores()  # With metadata
get_adjacent_chunks()           # Context expansion
get_document_count()            # Statistics
get_chunk_count()               # Statistics
document_exists()               # Duplicate detection
delete_all_documents()          # Clear database
```

---

#### **src/rag.py** - RAG Engine
**Lines**: ~800  
**Purpose**: Document processing and retrieval-augmented generation  
**Function**:
- Document loading (PDF, DOCX, TXT, MD)
- Text chunking (hierarchical, semantic-aware)
- Embedding generation
- Context retrieval and ranking
- Hybrid search (semantic + BM25)

**Key Features**:
- ?? Multi-format document support
- ?? Smart hierarchical chunking
- ?? Batch embedding generation
- ?? Hybrid search (semantic + keyword)
- ?? Result re-ranking
- ?? Context window expansion

**Main Classes**:
```python
DocumentProcessor:
    load_document()             # Load from file
    chunk_text()                # Hierarchical chunking
    generate_embeddings_batch() # Batch embeddings
    ingest_document()           # Full pipeline
    retrieve_context()          # Search and retrieve
    format_context_for_llm()    # Format for LLM
```

---

#### **src/ollama_client.py** - Ollama API Client
**Lines**: ~400  
**Purpose**: Interface with Ollama LLM service  
**Function**:
- LLM chat completions
- Embedding generation
- Model management (list, pull, delete)
- Streaming response handling

**Key Features**:
- ?? Chat completion (streaming & non-streaming)
- ?? Embedding generation
- ?? Model management
- ?? Connection pooling with sessions
- ? Parallel embedding generation

**Main Methods**:
```python
check_connection()              # Health check
list_models()                   # Get available models
pull_model()                    # Download new model
delete_model()                  # Remove model
generate_chat_response()        # Chat (streaming)
generate_embedding()            # Single embedding
generate_embeddings_batch()     # Batch embeddings
```

---

### **Supporting Modules**

#### **src/exceptions.py** - Custom Exceptions
**Lines**: ~150  
**Purpose**: Application-specific exception classes  
**Function**:
- Define custom exception hierarchy
- Map exceptions to HTTP status codes
- Provide structured error information

**Exception Classes**:
```python
LocalChatException              # Base exception
OllamaConnectionError           # Ollama service issues
DatabaseConnectionError         # Database issues
DocumentProcessingError         # Document processing
EmbeddingGenerationError        # Embedding failures
InvalidModelError               # Model not found
ValidationError                 # Input validation
ConfigurationError              # Config issues
ChunkingError                   # Chunking issues
SearchError                     # Search failures
FileUploadError                 # Upload issues
```

---

#### **src/models.py** - Pydantic Validation Models
**Lines**: ~400  
**Purpose**: Request/response validation with Pydantic  
**Function**:
- Validate API requests
- Ensure data integrity
- Provide clear error messages

**Validation Models**:
```python
ChatRequest                     # Chat API requests
DocumentUploadRequest           # File uploads
ModelRequest                    # Model operations
RetrievalRequest                # Search requests
ModelPullRequest                # Model downloads
ModelDeleteRequest              # Model deletion
ChunkingParameters              # Chunking config
ErrorResponse                   # Error formatting
```

---

#### **src/security.py** - Security Middleware
**Lines**: ~300  
**Purpose**: Authentication, rate limiting, and security  
**Function**:
- JWT authentication
- Rate limiting
- CORS configuration
- Security headers

**Features**:
- ?? JWT token authentication
- ?? Rate limiting per endpoint
- ?? CORS configuration
- ??? Security headers
- ?? Health check endpoints

---

### **Utilities**

#### **src/utils/logging_config.py** - Logging System
**Lines**: ~150  
**Purpose**: Structured logging configuration  
**Function**:
- Setup rotating file handlers
- Colored console output
- Module-level loggers

**Features**:
- ?? Rotating file logs (10MB max, 5 backups)
- ?? Colored console output
- ??? Module-level loggers
- ?? Structured logging

---

#### **src/utils/sanitization.py** - Input Sanitization
**Lines**: ~200  
**Purpose**: Security-focused input cleaning  
**Function**:
- Sanitize filenames (prevent path traversal)
- Clean user queries (prevent XSS)
- Validate model names

**Functions**:
```python
sanitize_filename()             # Clean filenames
sanitize_query()                # Clean search queries
sanitize_model_name()           # Validate model names
```

---

#### **src/utils/__init__.py** - Utilities Package
**Purpose**: Package initialization for utilities

---

## ?? **templates/ - HTML Templates**

Jinja2 templates for the web interface.

### **templates/base.html** - Base Template
**Purpose**: Master template with common layout  
**Features**:
- Bootstrap 5 UI framework
- Navigation sidebar
- Common CSS/JS includes

### **templates/chat.html** - Chat Interface
**Purpose**: Interactive chat page with RAG toggle  
**Features**:
- Message input and history
- RAG mode toggle
- Streaming response display
- Copy/clear functionality

### **templates/documents.html** - Document Management
**Purpose**: Upload and manage documents  
**Features**:
- Multi-file upload with progress
- Document list with metadata
- Test retrieval interface
- Statistics display

### **templates/models.html** - Model Management
**Purpose**: Manage Ollama models  
**Features**:
- List installed models
- Pull new models with progress
- Set active model
- Delete unused models

### **templates/overview.html** - System Overview
**Purpose**: System status and architecture view  
**Features**:
- Service status indicators
- System metrics
- Architecture diagram
- Feature list with accordions

---

## ?? **static/ - Static Assets**

### **static/css/style.css** - Application Styles
**Lines**: ~500  
**Purpose**: Custom CSS styling  
**Features**:
- Responsive design
- Dark mode support
- Custom component styles

### **static/js/chat.js** - Chat Interface Logic
**Lines**: ~300  
**Purpose**: Chat page JavaScript  
**Features**:
- Message sending via fetch API
- SSE for streaming responses
- History management
- Copy to clipboard

### **static/js/ingestion.js** - Document Upload Logic
**Lines**: ~400  
**Purpose**: Document management JavaScript  
**Features**:
- Multi-file upload
- Progress tracking
- Document list display
- Test retrieval

---

## ?? **tests/ - Test Suite**

Comprehensive test coverage with pytest.

### **Test Configuration**

#### **tests/conftest.py** - Test Fixtures
**Lines**: ~400  
**Purpose**: Shared pytest fixtures  
**Fixtures**:
- Mock database
- Mock Ollama client
- Sample data (text, embeddings, documents)
- Request/response examples

#### **pytest.ini** - Pytest Configuration
**Purpose**: Test runner configuration  
**Settings**:
- Test discovery patterns
- Coverage reporting
- Custom markers

---

### **Unit Tests**

#### **tests/test_exceptions_comprehensive.py**
**Tests**: 18  
**Purpose**: Test custom exception classes  
**Coverage**: 100% of exceptions.py

#### **tests/test_validation_comprehensive.py**
**Tests**: 27  
**Purpose**: Test Pydantic validation models  
**Coverage**: 95% of models.py

#### **tests/unit/test_config.py**
**Tests**: 15+  
**Purpose**: Test configuration management

#### **tests/unit/test_sanitization.py**
**Tests**: 20+  
**Purpose**: Test input sanitization functions

---

## ?? **scripts/ - Utility Scripts**

Helper scripts for setup, testing, and maintenance.

### **Setup Scripts**

#### **scripts/setup_db.sql**
**Purpose**: Database schema setup  
**Function**: SQL commands to initialize database

#### **scripts/db_init.py**
**Purpose**: Python script to initialize database

---

### **Testing Scripts**

#### **scripts/test_ollama.py**
**Purpose**: Test Ollama connection and models

#### **scripts/test_pgvector.py**
**Purpose**: Test PostgreSQL with pgvector

#### **scripts/test_rag.py**
**Purpose**: Test RAG retrieval

#### **scripts/test_validation_error.py**
**Purpose**: Test validation error messages

---

### **Maintenance Scripts**

#### **scripts/suppress_warnings.py**
**Purpose**: Apply warning suppressions  
**Function**:
- Update src/__init__.py with filters
- Create backups
- Verify changes

#### **scripts/verify_no_errors.py**
**Purpose**: Check for errors and warnings  
**Function**:
- Test imports
- Check syntax
- Verify suppressions
- Test configuration

---

## ?? **docs/ - Documentation**

Comprehensive documentation for developers and users.

### **User Documentation**

#### **docs/INSTALLATION.md**
**Purpose**: Complete installation guide

#### **docs/SETUP_GUIDE.md**
**Purpose**: Configuration and setup

#### **docs/README_OLD.md**
**Purpose**: User manual

#### **docs/TROUBLESHOOTING.md**
**Purpose**: Common issues and solutions

---

### **Developer Documentation**

#### **docs/DEVELOPMENT.md**
**Purpose**: Development guidelines

#### **docs/API.md**
**Purpose**: API endpoint documentation

#### **docs/ARCHITECTURE.md**
**Purpose**: System design and components

---

### **Feature Documentation**

#### **docs/features/RAG_HALLUCINATION_FIXED.md**
**Purpose**: RAG implementation details

#### **docs/features/PDF_TABLE_EXTRACTION.md**
**Purpose**: Table extraction feature

#### **docs/features/DUPLICATE_PREVENTION.md**
**Purpose**: Smart duplicate detection

#### **docs/features/RAG_OPTIMIZATION.md**
**Purpose**: Performance optimization guide

---

### **Testing Documentation**

#### **docs/testing/TESTING_GUIDE.md**
**Purpose**: How to write and run tests

#### **docs/testing/COMPLETION_REPORT.md**
**Purpose**: Test coverage details

#### **docs/testing/IMPLEMENTATION_PLAN.md**
**Purpose**: Testing strategy

---

### **Fix Documentation**

#### **docs/fixes/ERROR_SUPPRESSION_GUIDE.md**
**Purpose**: Guide to handling warnings

#### **docs/fixes/ERROR_RESOLUTION_COMPLETE.md**
**Purpose**: Error resolution summary

#### **docs/fixes/WEEK1_IMPLEMENTATION.md**
**Purpose**: Week 1 implementation summary

---

## ?? **Other Directories**

### **logs/** (gitignored)
**Purpose**: Application log files  
**Files**:
- `app.log` - Main application log (rotating)
- `error.log` - Error-specific log

### **uploads/** (gitignored)
**Purpose**: Temporary file storage for uploads

### **htmlcov/** (gitignored)
**Purpose**: HTML coverage reports from pytest

### **__pycache__/** (gitignored)
**Purpose**: Python bytecode cache

---

## ?? **Dependency Files**

### **requirements.txt**
**Purpose**: Production dependencies  
**Key Packages**:
```
flask==3.0.0
psycopg[binary]==3.1.14
psycopg-pool==3.2.0
ollama==0.1.6
PyPDF2==3.0.1
python-docx==1.1.0
numpy==1.26.2
pydantic==2.9.2
flask-jwt-extended
flask-limiter
flask-cors
```

### **.gitignore**
**Purpose**: Exclude files from version control  
**Excludes**:
- `__pycache__/`, `*.pyc`
- `venv/`, `env/`
- `.vs/`
- `logs/`, `uploads/`
- `.env`
- `htmlcov/`, `.pytest_cache/`

---

## ?? **File Statistics by Category**

| Category | Count | Total Lines |
|----------|-------|-------------|
| **Source Code** | 12 files | ~4,000 lines |
| **Templates** | 5 files | ~1,500 lines |
| **Tests** | 15+ files | ~2,500 lines |
| **Scripts** | 10+ files | ~1,000 lines |
| **Documentation** | 50+ files | ~10,000+ lines |
| **Configuration** | 5 files | ~200 lines |

**Total Project**: ~19,000+ lines of code and documentation

---

## ?? **Key File Relationships**

```
app.py (entry)
    ?
src/app.py (Flask app)
    ?? src/config.py (configuration)
    ?? src/db.py (database)
    ?? src/rag.py (document processing)
    ?? src/ollama_client.py (LLM)
    ?? src/exceptions.py (errors)
    ?? src/models.py (validation)
    ?? src/security.py (auth & security)
    ?? src/utils/ (utilities)
        ?? logging_config.py
        ?? sanitization.py

templates/ (views)
    ?? base.html
    ?? chat.html
    ?? documents.html
    ?? models.html
    ?? overview.html

static/ (assets)
    ?? css/style.css
    ?? js/chat.js
    ?? js/ingestion.js
```

---

## ?? **Quick Reference**

### **Need to...**

| Task | File to Edit |
|------|--------------|
| Add new API endpoint | `src/app.py` |
| Change RAG settings | `src/config.py` |
| Modify chunking logic | `src/rag.py` |
| Update database schema | `src/db.py` |
| Add validation rule | `src/models.py` |
| Handle new error type | `src/exceptions.py` |
| Change UI layout | `templates/base.html` |
| Add JavaScript feature | `static/js/*.js` |
| Write new test | `tests/unit/*.py` |
| Update documentation | `docs/*.md` |

---

**Last Updated**: 2026-01-10  
**Total Files**: 100+  
**Lines of Code**: ~19,000+  
**Documentation**: Comprehensive  
**Test Coverage**: 59% (target: 80%)
