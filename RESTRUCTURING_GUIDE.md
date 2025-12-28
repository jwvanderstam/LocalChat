# ?? LocalChat Project Restructuring Guide

## ?? Overview

This guide explains the new professional project structure and how to migrate from the old flat structure to the new organized layout.

---

## ?? New Structure Benefits

### ? **Better Organization**
- Clear separation of concerns
- Easy to find files
- Follows Python best practices

### ? **Easier Development**
- Logical grouping of related files
- Clear module boundaries
- Better IDE support

### ? **Professional Standard**
- Matches industry standards
- Ready for open source
- Easy for new contributors

### ? **Scalable**
- Easy to add new features
- Clear places for new code
- Organized documentation

---

## ?? Directory Structure

### **Before** (Flat Structure):
```
LocalChat/
??? app.py
??? config.py
??? db.py
??? rag.py
??? ollama_client.py
??? exceptions.py
??? models.py
??? utils/
?   ??? logging_config.py
?   ??? sanitization.py
??? tests/
?   ??? (all tests mixed)
??? (50+ markdown files)
??? (helper scripts mixed)
??? templates/
```

### **After** (Organized Structure):
```
LocalChat/
??? src/                    # ?? All source code
??? tests/                  # ?? Organized tests
??? docs/                   # ?? All documentation
??? scripts/                # ??? Helper scripts
??? static/                 # ?? Web assets
??? templates/              # ?? HTML templates
??? .github/                # ?? CI/CD
??? (config files at root)
```

---

## ?? Migration Steps

### **Phase 1: Create New Structure** ?

```bash
# Create main directories
mkdir -p src/utils
mkdir -p docs/{testing,features,changelog}
mkdir -p scripts/deployment
mkdir -p tests/{unit,integration,fixtures,utils}
mkdir -p static/{css,js,images}
mkdir -p .github/workflows
mkdir -p logs uploads

# Create __init__.py files
touch src/__init__.py
touch src/utils/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py
touch tests/utils/__init__.py
```

### **Phase 2: Move Source Code** ?

```bash
# Move core application files
mv app.py src/
mv config.py src/
mv db.py src/
mv rag.py src/
mv ollama_client.py src/
mv exceptions.py src/
mv models.py src/

# Move utilities
mv utils/logging_config.py src/utils/
mv utils/sanitization.py src/utils/
```

### **Phase 3: Organize Tests** ?

```bash
# Move unit tests
mv tests/test_*.py tests/unit/

# Move integration tests
mv tests/integration/test_integration.py tests/integration/

# Keep test utilities
# tests/utils/ already in place

# Keep fixtures
# tests/fixtures/ already in place
```

### **Phase 4: Organize Documentation** ?

```bash
# Testing documentation
mv MONTH3_*.md docs/changelog/
mv *TEST*.md docs/testing/

# Feature documentation
mv RAG_*.md docs/features/
mv PDF_*.md docs/features/
mv DUPLICATE_*.md docs/features/

# Main documentation
mv COMPLETE_SETUP_SUMMARY.md docs/
mv CODE_QUALITY_GUIDE.md docs/DEVELOPMENT.md
```

### **Phase 5: Organize Scripts** ?

```bash
# Move helper scripts
mv pdf_diagnostic.py scripts/
mv test_pdf_table_extraction.py scripts/
mv check_data.py scripts/

# Create new scripts
# scripts/setup.py
# scripts/test_runner.py
# scripts/db_init.py
```

### **Phase 6: Update Imports** ?

All Python files need updated imports:

**Before**:
```python
import config
from db import db
from rag import doc_processor
```

**After**:
```python
from src import config
from src.db import db
from src.rag import doc_processor
```

### **Phase 7: Update Configurations** ?

Update pytest.ini, .coveragerc, etc. to point to new paths.

---

## ?? File Migration Map

### **Source Code** ? `src/`
```
app.py                  ? src/app.py
config.py              ? src/config.py
db.py                  ? src/db.py
rag.py                 ? src/rag.py
ollama_client.py       ? src/ollama_client.py
exceptions.py          ? src/exceptions.py
models.py              ? src/models.py
utils/                 ? src/utils/
```

### **Tests** ? `tests/unit/` or `tests/integration/`
```
tests/test_*.py        ? tests/unit/test_*.py
tests/integration/     ? tests/integration/
tests/utils/           ? tests/utils/ (unchanged)
tests/fixtures/        ? tests/fixtures/ (unchanged)
```

### **Documentation** ? `docs/`
```
MONTH3_*.md           ? docs/changelog/
RAG_*.md              ? docs/features/
PDF_*.md              ? docs/features/
*_GUIDE.md            ? docs/
API docs              ? docs/API.md
Architecture          ? docs/ARCHITECTURE.md
```

### **Scripts** ? `scripts/`
```
pdf_diagnostic.py     ? scripts/pdf_diagnostic.py
check_data.py         ? scripts/check_data.py
test scripts          ? scripts/
deployment scripts    ? scripts/deployment/
```

---

## ?? Configuration Updates

### **pytest.ini**
```ini
[pytest]
pythonpath = .
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### **.coveragerc**
```ini
[run]
source = src
omit = 
    */tests/*
    */venv/*
    */__pycache__/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
```

### **pyproject.toml** (NEW)
```toml
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "localchat"
version = "0.3.0"
description = "RAG-based chat application with PDF support"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "LocalChat Team"}
]
```

---

## ?? Import Path Updates

### **In Source Files** (`src/*.py`):
```python
# OLD imports
import config
from db import db
from rag import doc_processor
from ollama_client import ollama_client
from utils.logging_config import get_logger
from utils.sanitization import sanitize_query

# NEW imports (relative within src/)
from . import config
from .db import db
from .rag import doc_processor
from .ollama_client import ollama_client
from .utils.logging_config import get_logger
from .utils.sanitization import sanitize_query
```

### **In Test Files** (`tests/unit/*.py`):
```python
# OLD imports
import config
from db import db
from rag import DocumentProcessor

# NEW imports
from src import config
from src.db import db
from src.rag import DocumentProcessor
```

### **Running the App**:
```python
# OLD
python app.py

# NEW (option 1 - run as module)
python -m src.app

# NEW (option 2 - run directly with adjusted path)
python src/app.py
```

---

## ?? Benefits of New Structure

| Aspect | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Organization** | Flat, 50+ files mixed | Categorized by purpose | ? Much clearer |
| **Finding files** | Search entire directory | Know exactly where | ? 5x faster |
| **New contributors** | Confusing | Clear structure | ? Easy onboarding |
| **Scalability** | Hard to extend | Easy to add | ? Future-proof |
| **Documentation** | Mixed with code | Separate docs/ | ? Professional |
| **IDE support** | Basic | Full support | ? Better tooling |

---

## ?? Testing After Migration

### **1. Verify Imports**
```bash
# Test all imports work
python -c "from src import config; print('OK')"
python -c "from src.db import db; print('OK')"
python -c "from src.rag import doc_processor; print('OK')"
```

### **2. Run Tests**
```bash
# Run all tests
pytest

# Should see all tests pass
# Coverage should work correctly
pytest --cov=src
```

### **3. Start Application**
```bash
# Start Flask app
python -m src.app

# Or
cd src && python app.py
```

### **4. Verify All Features**
- Upload documents
- Test RAG
- Check chat
- Verify models

---

## ?? Migration Checklist

### **Phase 1: Setup** ?
- [x] Create directory structure
- [x] Create __init__.py files
- [x] Create .gitignore
- [x] Create PROJECT_STRUCTURE.md

### **Phase 2: Source Code** ?
- [ ] Move Python files to src/
- [ ] Update imports in src files
- [ ] Test imports work

### **Phase 3: Tests** ?
- [ ] Organize tests into unit/integration
- [ ] Update test imports
- [ ] Run tests to verify

### **Phase 4: Documentation** ?
- [ ] Move docs to docs/
- [ ] Organize by category
- [ ] Create README in docs/

### **Phase 5: Scripts** ?
- [ ] Move scripts to scripts/
- [ ] Update script imports
- [ ] Test scripts work

### **Phase 6: Configuration** ?
- [ ] Update pytest.ini
- [ ] Update .coveragerc
- [ ] Create pyproject.toml
- [ ] Update requirements files

### **Phase 7: Verification** ?
- [ ] All imports work
- [ ] All tests pass
- [ ] Application runs
- [ ] Documentation accessible
- [ ] Scripts executable

---

## ?? Common Issues & Solutions

### **Issue 1: Import Errors**
```
ImportError: No module named 'config'
```

**Solution**: Update imports to use `from src import config`

### **Issue 2: Tests Can't Find Modules**
```
ModuleNotFoundError: No module named 'src'
```

**Solution**: Add `pythonpath = .` to pytest.ini

### **Issue 3: Application Won't Start**
```
Can't find config.py
```

**Solution**: Run as module: `python -m src.app`

### **Issue 4: Templates Not Found**
```
TemplateNotFound: chat.html
```

**Solution**: Update Flask template folder config in src/app.py

---

## ?? Next Steps

After completing migration:

1. ? **Commit changes** to version control
2. ? **Update README.md** with new structure
3. ? **Update CI/CD** workflows
4. ? **Test thoroughly** in development
5. ? **Deploy** to production

---

## ?? Additional Resources

- **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** - Detailed structure overview
- **[Python Packaging Guide](https://packaging.python.org/)** - Official Python packaging docs
- **[Structuring Python Projects](https://docs.python-guide.org/writing/structure/)** - Best practices

---

**Status**: ?? **Migration In Progress**  
**Priority**: High  
**Next**: Move source code to src/

---

*This restructuring follows Python best practices and industry standards for professional projects.*
