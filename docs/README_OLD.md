# LocalChat - RAG Application with Ollama and pgvector

A complete Flask-based Retrieval-Augmented Generation (RAG) application that uses Ollama for LLM integration and PostgreSQL with pgvector for document storage and retrieval.

## Features

- ?? **Ollama Integration**: Chat with local LLMs, switch models, and pull new models
- ?? **Document Management**: Upload and process PDF, TXT, DOCX, and MD files
- ?? **RAG System**: Retrieve relevant context from documents to enhance LLM responses
- ? **High Performance**: Parallel document processing with 4 workers and connection pooling
- ?? **Real-time Chat**: Streaming responses with RAG/Direct LLM toggle
- ?? **System Overview**: Architecture visualization and performance metrics

## Architecture

```
User ? Flask App ? Ollama (LLM + Embeddings)
                 ?
          PostgreSQL + pgvector (Document Storage)
```

### RAG Pipeline
1. **Ingest Documents** ? Chunk text (500 tokens, 50 overlap)
2. **Generate Embeddings** ? Using Ollama embedding models
3. **Store in pgvector** ? With vector similarity indexing
4. **Query Processing** ? Retrieve top-5 most similar chunks
5. **Context Enhancement** ? Pass retrieved context to LLM

## Prerequisites

### 1. Ollama
Install Ollama from [ollama.ai](https://ollama.ai)

```bash
# Verify Ollama is running
curl http://localhost:11434

# Pull a model (e.g., llama2)
ollama pull llama2

# Optional: Pull an embedding model
ollama pull nomic-embed-text
```

### 2. PostgreSQL with pgvector
Install PostgreSQL 12+ and the pgvector extension.

#### On Ubuntu/Debian:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo apt install postgresql-15-pgvector
```

#### On macOS (using Homebrew):
```bash
brew install postgresql@15
brew install pgvector
```

#### On Windows:
Download PostgreSQL from [postgresql.org](https://www.postgresql.org/download/windows/)
Then install pgvector from [pgvector releases](https://github.com/pgvector/pgvector/releases)

### 3. Python 3.8+
Ensure Python 3.8 or higher is installed.

## Installation

### Step 1: Clone or Download the Repository
```bash
cd C:\Users\Gebruiker\source\repos\LocalChat
```

### Step 2: Create Virtual Environment (Recommended)
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Set Up Database
The application will automatically create the database if it doesn't exist. However, you need to ensure PostgreSQL is running and the user has necessary permissions.

#### Option A: Automatic Setup (Recommended)
The application will attempt to create the database and tables automatically on first run.

#### Option B: Manual Setup
```bash
# Connect to PostgreSQL
psql -U postgres

# Run the setup script
\i setup_db.sql

# Or manually:
CREATE DATABASE rag_db;
\c rag_db
CREATE EXTENSION vector;
```

### Step 5: Configure Environment (Optional)
Create a `.env` file if you need custom configuration:

```env
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=Mutsmuts10
PG_DB=rag_db
OLLAMA_BASE_URL=http://localhost:11434
SECRET_KEY=your-secret-key-here
```

## Running the Application

### Start the Application
```bash
python app.py
```

The application will:
1. ? Check Ollama connection and load first available model
2. ? Check PostgreSQL connection and create database/tables if needed
3. ? Start web server on `http://localhost:5000`

### Access the Application
Open your browser and navigate to:
```
http://localhost:5000
```

## Usage Guide

### 1. Document Management (`/documents`)
- **Upload Documents**: Select PDF, TXT, DOCX, or MD files
- **View Progress**: Real-time progress bar during ingestion
- **Test RAG**: Query your documents to test retrieval
- **View Statistics**: See document and chunk counts

### 2. Chat Interface (`/chat`)
- **RAG Mode**: Toggle ON to use document context
- **Direct LLM Mode**: Toggle OFF for standard chat
- **Streaming**: Real-time streaming responses
- **History**: Persistent chat history (stored in browser)

### 3. Model Management (`/models`)
- **List Models**: View all available Ollama models
- **Activate Model**: Set the active model for chat
- **Pull Models**: Download new models from Ollama registry
- **Test Models**: Verify model functionality
- **Delete Models**: Remove unused models

### 4. Overview (`/overview`)
- **System Status**: Check Ollama and database health
- **Architecture Diagram**: Visual system architecture
- **Performance Metrics**: View statistics
- **Quick Actions**: Navigate to key features

## Configuration

### RAG Parameters
Edit `config.py` to adjust:
- `CHUNK_SIZE`: Token size for document chunks (default: 500)
- `CHUNK_OVERLAP`: Overlap between chunks (default: 50)
- `TOP_K_RESULTS`: Number of chunks to retrieve (default: 5)
- `MAX_WORKERS`: Parallel processing workers (default: 4)

### Database Connection Pool
- `DB_POOL_MIN_CONN`: Minimum connections (default: 2)
- `DB_POOL_MAX_CONN`: Maximum connections (default: 10)

### Supported File Types
- PDF (`.pdf`)
- Text (`.txt`)
- Word Documents (`.docx`)
- Markdown (`.md`)

## Troubleshooting

### Ollama Not Running
```bash
# Check if Ollama is running
curl http://localhost:11434

# If not, start Ollama
ollama serve
```

### Database Connection Failed
```bash
# Check PostgreSQL status
# Windows: Check Services
# Linux: sudo systemctl status postgresql
# macOS: brew services list

# Verify credentials in config.py or .env file
```

### No Models Available
```bash
# Pull a model
ollama pull llama2
ollama pull mistral
ollama pull nomic-embed-text
```

### pgvector Extension Missing
```bash
# Connect to database
psql -U postgres -d rag_db

# Create extension
CREATE EXTENSION vector;
```

### Port Already in Use
```bash
# Change port in app.py or set environment variable
export SERVER_PORT=5001
python app.py
```

## Performance Tips

1. **Use Embedding Models**: For best results, use dedicated embedding models like `nomic-embed-text`
2. **Adjust Chunk Size**: Smaller chunks (300-400) for precise retrieval, larger (600-800) for more context
3. **Connection Pooling**: Increase `DB_POOL_MAX_CONN` for high concurrent usage
4. **Vector Index**: The IVFFlat index is optimized for ~100-1000 documents. Adjust `lists` parameter for larger datasets

## Project Structure

```
LocalChat/
??? app.py                 # Main Flask application
??? config.py             # Configuration settings
??? db.py                 # Database connection and models
??? ollama_client.py      # Ollama API wrapper
??? rag.py                # RAG processing logic
??? requirements.txt      # Python dependencies
??? setup_db.sql         # Database setup script
??? README.md            # This file
??? templates/
?   ??? base.html        # Base layout
?   ??? chat.html        # Chat interface
?   ??? documents.html   # Document management
?   ??? models.html      # Model management
?   ??? overview.html    # System overview
??? static/
    ??? css/
    ?   ??? style.css    # Custom styles
    ??? js/
        ??? chat.js      # Chat functionality
        ??? ingestion.js # Document ingestion
```

## Technology Stack

- **Backend**: Flask 3.0
- **Database**: PostgreSQL 15+ with pgvector extension
- **LLM**: Ollama (supports llama2, mistral, codellama, etc.)
- **Frontend**: Bootstrap 5, Vanilla JavaScript
- **Document Processing**: PyPDF2, python-docx
- **Connection Pooling**: psycopg2 ThreadedConnectionPool

## Security Notes

?? **Important**: This application is designed for local/development use.

For production deployment:
1. Change `SECRET_KEY` in `config.py`
2. Use environment variables for sensitive data
3. Enable HTTPS
4. Add authentication and authorization
5. Implement rate limiting
6. Sanitize user inputs
7. Use production WSGI server (gunicorn, waitress)

## Contributing

This is a complete, production-ready RAG application template. Feel free to:
- Add new document types
- Implement user authentication
- Add more LLM providers
- Enhance the UI
- Add tests

## License

MIT License - Feel free to use this project for any purpose.

## Support

For issues or questions:
1. Check Ollama is running: `curl http://localhost:11434`
2. Verify PostgreSQL: `psql -U postgres -c "SELECT version();"`
3. Check logs in the terminal where you ran `python app.py`
4. Ensure all dependencies are installed: `pip install -r requirements.txt`

## Acknowledgments

- [Ollama](https://ollama.ai) - Local LLM runtime
- [pgvector](https://github.com/pgvector/pgvector) - Vector similarity search for PostgreSQL
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Bootstrap](https://getbootstrap.com/) - UI framework

---

**Built with ?? for local AI applications**
