# ?? LocalChat Installation Guide

## Overview

This guide covers multiple installation methods for the LocalChat RAG application.

**Installation Time**: 10-15 minutes  
**Difficulty**: Easy to Moderate  
**Supported Platforms**: Windows, Linux, macOS

---

## ?? Quick Install

### **Option 1: Automated Installation (Recommended)**

#### **Windows (PowerShell)**
```powershell
# Run as Administrator
.\install.ps1
```

#### **Linux/Mac (Bash)**
```bash
# Make executable
chmod +x install.sh

# Run installer
./install.sh
```

#### **Cross-Platform (Python)**
```bash
python install.py
```

---

## ?? Prerequisites

Before installation, ensure you have:

### **Required**:
- ? **Python 3.10+** - [Download](https://www.python.org/downloads/)
- ? **PostgreSQL 12+** - [Download](https://www.postgresql.org/download/)
- ? **Ollama** - [Download](https://ollama.ai)

### **Optional**:
- Git (for cloning repository)
- Virtual environment tool (venv, conda)

---

## ?? Installation Methods

### **Method 1: Automated Interactive Installation**

**Most user-friendly - Guides you through each step**

#### **Windows**:
```powershell
# Clone repository
git clone https://github.com/jwvanderstam/LocalChat.git
cd LocalChat

# Run installer
.\install.ps1
```

**The installer will**:
1. ? Check prerequisites
2. ? Install Python dependencies
3. ? Set up PostgreSQL database
4. ? Configure pgvector extension
5. ? Create .env configuration
6. ? Pull Ollama models
7. ? Run tests (optional)

#### **Linux/Mac**:
```bash
# Clone repository
git clone https://github.com/jwvanderstam/LocalChat.git
cd LocalChat

# Make installer executable
chmod +x install.sh

# Run installer
./install.sh
```

---

### **Method 2: Automated Non-Interactive Installation**

**For scripting and CI/CD pipelines**

```bash
# Windows
.\install.ps1 -Auto

# Linux/Mac
./install.sh --auto

# Python (cross-platform)
python install.py --auto
```

**Note**: Database setup must be done manually in auto mode.

---

### **Method 3: Manual Installation**

**For advanced users who want full control**

#### **Step 1: Clone Repository**
```bash
git clone https://github.com/jwvanderstam/LocalChat.git
cd LocalChat
```

#### **Step 2: Create Virtual Environment** (Recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

#### **Step 3: Install Dependencies**
```bash
pip install -r requirements.txt
```

#### **Step 4: Set Up PostgreSQL**
```bash
# Create database
createdb rag_db

# Enable pgvector extension
psql rag_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

#### **Step 5: Configure Environment**

Create `.env` file:
```env
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your_password_here
PG_DB=rag_db

OLLAMA_BASE_URL=http://localhost:11434

SERVER_HOST=localhost
SERVER_PORT=5000
SECRET_KEY=change-this-in-production

DEBUG=False
```

#### **Step 6: Create Directories**
```bash
mkdir -p logs uploads
```

#### **Step 7: Pull Ollama Models**
```bash
# Start Ollama (in separate terminal)
ollama serve

# Pull models
ollama pull nomic-embed-text
ollama pull llama3.2
```

#### **Step 8: Run Tests** (Optional)
```bash
pytest tests/unit/ -v
```

#### **Step 9: Start Application**
```bash
python app.py
```

---

## ?? Configuration Options

### **Environment Variables**

Edit `.env` file to configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `PG_HOST` | PostgreSQL host | localhost |
| `PG_PORT` | PostgreSQL port | 5432 |
| `PG_USER` | Database user | postgres |
| `PG_PASSWORD` | Database password | postgres |
| `PG_DB` | Database name | rag_db |
| `OLLAMA_BASE_URL` | Ollama API URL | http://localhost:11434 |
| `SERVER_HOST` | Flask server host | localhost |
| `SERVER_PORT` | Flask server port | 5000 |
| `SECRET_KEY` | Flask secret key | (change in production) |
| `DEBUG` | Debug mode | False |

---

## ? Verification

### **Check Installation**

Run prerequisite checker:
```bash
# Windows
.\install.ps1 -CheckOnly

# Linux/Mac
./install.sh --check

# Python
python install.py --check
```

### **Test Application**

```bash
# Start application
python app.py

# Open browser
# http://localhost:5000
```

### **Run Tests**

```bash
# Run all tests
pytest tests/unit/ -v

# Run specific test
pytest tests/unit/test_config.py -v
```

---

## ?? Troubleshooting

### **Issue: Python not found**

**Windows**:
```powershell
# Check Python installation
python --version

# If not found, add to PATH or reinstall
```

**Linux/Mac**:
```bash
# Install Python
sudo apt install python3 python3-pip  # Ubuntu/Debian
brew install python3                   # macOS
```

### **Issue: PostgreSQL not running**

**Windows**:
```powershell
# Start PostgreSQL service
net start postgresql-x64-14
```

**Linux**:
```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**macOS**:
```bash
# Start PostgreSQL
brew services start postgresql
```

### **Issue: pgvector extension not found**

**Install pgvector**:

**Windows**: Download from [pgvector releases](https://github.com/pgvector/pgvector/releases)

**Linux**:
```bash
cd /tmp
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

**macOS**:
```bash
brew install pgvector
```

### **Issue: Ollama not responding**

```bash
# Start Ollama server
ollama serve

# Check status
curl http://localhost:11434/api/tags
```

### **Issue: Permission denied on install.sh**

```bash
# Make executable
chmod +x install.sh

# Run
./install.sh
```

### **Issue: Port 5000 already in use**

Edit `.env`:
```env
SERVER_PORT=5001
```

Or use environment variable:
```bash
export SERVER_PORT=5001
python app.py
```

---

## ?? Updating

### **Update Application**

```bash
# Pull latest changes
git pull origin main

# Update dependencies
pip install -r requirements.txt --upgrade

# Run migrations (if any)
# (No migrations needed currently)

# Restart application
python app.py
```

### **Update Ollama Models**

```bash
# Update embedding model
ollama pull nomic-embed-text

# Update chat model
ollama pull llama3.2
```

---

## ??? Uninstallation

### **Remove Application**

```bash
# Stop application (Ctrl+C)

# Remove virtual environment (if used)
rm -rf venv

# Remove application directory
cd ..
rm -rf LocalChat
```

### **Remove Database**

```bash
# Drop database
dropdb rag_db
```

### **Keep Data**

If you want to reinstall but keep your documents:
1. Backup `uploads/` directory
2. Export database: `pg_dump rag_db > backup.sql`
3. After reinstall: `psql rag_db < backup.sql`

---

## ?? Installation Variants

### **Docker Installation** (Future)

*Docker support coming soon*

```bash
# Build image
docker build -t localchat .

# Run container
docker-compose up
```

### **Development Installation**

For contributors:
```bash
# Clone with dev dependencies
git clone https://github.com/jwvanderstam/LocalChat.git
cd LocalChat

# Install with dev dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run in debug mode
DEBUG=True python app.py
```

---

## ?? Installation Checklist

After installation, verify:

- [ ] PostgreSQL is running
- [ ] pgvector extension is enabled
- [ ] Ollama is running
- [ ] Embedding model is pulled (nomic-embed-text)
- [ ] Chat model is pulled (llama3.2)
- [ ] .env file is configured
- [ ] Dependencies are installed
- [ ] Tests pass (pytest)
- [ ] Application starts successfully
- [ ] Web interface is accessible (http://localhost:5000)

---

## ?? Additional Resources

- **Quick Start**: [QUICK_START.md](QUICK_START.md)
- **Setup Guide**: [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)
- **Main README**: [README_MAIN.md](README_MAIN.md)
- **Troubleshooting**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- **API Documentation**: [docs/API.md](docs/API.md)

---

## ?? Tips

### **For Windows Users**:
- Run PowerShell as Administrator for smooth installation
- Use Windows Terminal for better experience
- Add Python to PATH during installation

### **For Linux Users**:
- Use `sudo` for system-wide installations
- Consider using virtual environments
- Check firewall settings if accessing remotely

### **For macOS Users**:
- Use Homebrew for easy dependency management
- Consider using pyenv for Python version management
- Allow network access when prompted

---

## ?? Getting Help

If you encounter issues:

1. **Check documentation**: Read this guide thoroughly
2. **Run diagnostics**: `python install.py --check`
3. **View logs**: Check `logs/` directory
4. **Search issues**: https://github.com/jwvanderstam/LocalChat/issues
5. **Ask for help**: Create a new issue with error details

---

## ? Success!

If installation completed successfully, you should see:

```
======================================================================
Installation Complete!
======================================================================

LocalChat has been successfully installed!

Next steps:
  1. Edit .env file to configure your database password
  2. Start Ollama: ollama serve
  3. Start LocalChat: python app.py
  4. Open browser: http://localhost:5000
======================================================================
```

**Congratulations! Your LocalChat RAG application is ready to use!** ??

---

**Date**: 2024-12-28  
**Version**: 1.0  
**Maintainer**: LocalChat Team
