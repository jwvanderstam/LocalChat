# Quick Start: Implementing Phase 1.1 Enhanced Citations

## Ready to Start? Here's Your Implementation Path

### Prerequisites ?
- Current RAG system working (A- grade)
- PostgreSQL with pgvector installed
- Python environment set up
- Git repository clean

### Time Estimate: 2-3 Days (10-12 hours total)

---

## Step-by-Step Implementation

### ?? Day 1: Database Foundation (Morning)

#### 1. Create Migration Script (30 min)

```bash
# Create migration file
touch scripts/migrate_add_metadata.py
```

**Copy this code:**
```python
#!/usr/bin/env python3
"""Add metadata column to document_chunks table."""

from src.db import db
from src.utils.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

def migrate():
    logger.info("Adding metadata column...")
    
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Add metadata column
            cursor.execute("""
                ALTER TABLE document_chunks 
                ADD COLUMN IF NOT EXISTS metadata JSONB 
                DEFAULT '{}'::jsonb;
            """)
            
            # Create GIN index for metadata queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS document_chunks_metadata_idx 
                ON document_chunks USING GIN (metadata);
            """)
            
            conn.commit()
    
    logger.info("Migration complete!")

if __name__ == '__main__':
    migrate()
```

**Run migration:**
```bash
python scripts/migrate_add_metadata.py
```

**Verify:**
```sql
-- Check column exists
\d document_chunks

-- Expected: metadata column present with JSONB type
```

---

#### 2. Update Database Insert Method (1 hour)

**File:** `src/db.py`

**Find the `insert_chunks` method** and enhance it:

```python
# Add psycopg Json import at top
from psycopg.types.json import Json

# Update insert_chunks method
def insert_chunks(self, chunks_data, embeddings, document_id):
    """
    Insert chunks with metadata.
    
    Args:
        chunks_data: List of dicts with 'text', 'page_number', 'section_title'
        embeddings: Numpy array of embeddings
        document_id: Document ID
    """
    with self.get_connection() as conn:
        with conn.cursor() as cursor:
            for idx, chunk_data in enumerate(chunks_data):
                # Build metadata
                metadata = {}
                if 'page_number' in chunk_data:
                    metadata['page_number'] = chunk_data['page_number']
                if 'section_title' in chunk_data:
                    metadata['section_title'] = chunk_data['section_title']
                
                cursor.execute("""
                    INSERT INTO document_chunks 
                    (document_id, chunk_text, chunk_index, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    document_id,
                    chunk_data.get('text', chunk_data.get('chunk_text', '')),
                    idx,
                    embeddings[idx].tolist(),
                    Json(metadata)
                ))
            
            conn.commit()
```

---

#### 3. Update Search Method (30 min)

**Still in `src/db.py`**

**Find `search_similar_chunks` method** and add metadata to results:

```python
def search_similar_chunks(self, query_embedding, top_k=50, threshold=0.25):
    """Search with metadata."""
    with self.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    dc.chunk_text,
                    d.filename,
                    dc.chunk_index,
                    1 - (dc.embedding <=> %s::vector) as similarity,
                    dc.metadata
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE 1 - (dc.embedding <=> %s::vector) > %s
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            """, (
                query_embedding, query_embedding, threshold,
                query_embedding, top_k
            ))
            
            return [
                {
                    'chunk_text': row[0],
                    'filename': row[1],
                    'chunk_index': row[2],
                    'similarity': row[3],
                    'metadata': row[4] or {}
                }
                for row in cursor.fetchall()
            ]
```

---

### ?? Day 1: PDF Enhancement (Afternoon)

#### 4. Add Section Title Extraction (1 hour)

**File:** `src/rag.py`

**Add this new method to DocumentProcessor class:**

```python
def _extract_section_title(self, page_text: str) -> Optional[str]:
    """
    Extract likely section title from page start.
    
    Returns:
        Section title or None
    """
    if not page_text:
        return None
    
    lines = page_text.strip().split('\n')
    
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        
        if not line or len(line) < 3:
            continue
        
        # Skip numbered lines
        if re.match(r'^\d+\.', line):
            continue
        
        # Check if looks like title
        if len(line) < 100 and (line.endswith(':') or line.istitle()):
            return line.rstrip(':')
    
    return None
```

---

#### 5. Enhance PDF Loading (1.5 hours)

**Still in `src/rag.py`**

**Find `_load_pdf` method** and modify to track pages:

```python
def _load_pdf(self, file_path: str) -> Tuple[bool, Union[str, List[Dict]]]:
    """Load PDF with page tracking."""
    if not PDF_AVAILABLE:
        return False, "PyPDF2 not installed"
    
    try:
        import pdfplumber as pdfp
        
        pages_data = []
        
        with pdfp.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text() or ""
                
                if page_text:
                    section_title = self._extract_section_title(page_text)
                    
                    pages_data.append({
                        'page_number': page_num,
                        'text': page_text,
                        'section_title': section_title
                    })
        
        # Return pages data instead of concatenated text
        return True, pages_data
        
    except Exception as e:
        logger.error(f"Error loading PDF: {e}", exc_info=True)
        return False, str(e)
```

---

### ?? Day 2: Chunking with Metadata

#### 6. Update Chunking to Preserve Metadata (2 hours)

**Still in `src/rag.py`**

**Modify `_chunk_document` method:**

```python
def _chunk_document(
    self, 
    content: Union[str, List[Dict]], 
    file_type: str = 'txt'
) -> List[Dict]:
    """
    Chunk document with metadata preservation.
    
    Returns:
        List of chunk dictionaries with text and metadata
    """
    chunk_size = config.CHUNK_SIZE
    overlap = config.CHUNK_OVERLAP
    
    # Handle page-by-page data (from PDF)
    if isinstance(content, list) and all(isinstance(p, dict) for p in content):
        chunks_with_metadata = []
        current_section = None
        chunk_index = 0
        
        for page_data in content:
            page_num = page_data['page_number']
            page_text = page_data['text']
            section = page_data.get('section_title') or current_section
            
            if page_data.get('section_title'):
                current_section = page_data['section_title']
            
            # Chunk the page
            page_chunks = self._chunk_text_standard(page_text, chunk_size, overlap)
            
            for chunk_text in page_chunks:
                if len(chunk_text.strip()) >= 10:
                    chunks_with_metadata.append({
                        'text': chunk_text,
                        'chunk_text': chunk_text,  # Compatibility
                        'page_number': page_num,
                        'section_title': section,
                        'chunk_index': chunk_index
                    })
                    chunk_index += 1
        
        return chunks_with_metadata
    
    # Handle plain text (original behavior)
    else:
        text_chunks = self._chunk_text_smart(content, chunk_size, overlap)
        return [
            {
                'text': chunk,
                'chunk_text': chunk,
                'chunk_index': idx
            }
            for idx, chunk in enumerate(text_chunks)
        ]
```

---

### ?? Day 2: Update Ingestion Flow (Afternoon)

#### 7. Modify Ingest Document Method (1 hour)

**Still in `src/rag.py`**

**Find `ingest_document` method** - verify it passes chunks correctly:

```python
# In ingest_document method, after chunking:

# Generate embeddings
embeddings = self.embedder.embed_batch([c.get('text', c.get('chunk_text')) for c in chunks])

# Store chunks with metadata
db.insert_chunks(chunks, embeddings, doc_id)
```

---

#### 8. Test with Real PDF (1 hour)

Create test file `tests/test_enhanced_citations.py`:

```python
import pytest
from src.rag import doc_processor
from src.db import db

def test_pdf_metadata_extraction():
    """Test PDF loads with page numbers."""
    success, pages = doc_processor._load_pdf("tests/fixtures/sample.pdf")
    
    assert success
    assert isinstance(pages, list)
    assert all('page_number' in p for p in pages)
    assert all('text' in p for p in pages)

def test_chunk_metadata_preservation():
    """Test chunks preserve metadata."""
    pages = [
        {'page_number': 1, 'text': 'Page 1 content', 'section_title': 'Introduction'},
        {'page_number': 2, 'text': 'Page 2 content', 'section_title': None}
    ]
    
    chunks = doc_processor._chunk_document(pages, file_type='pdf')
    
    assert len(chunks) > 0
    assert all('page_number' in c for c in chunks)
    assert chunks[0]['section_title'] == 'Introduction'

def test_database_metadata_storage():
    """Test metadata stored and retrieved."""
    # This would use a test database
    # (Implementation depends on your test setup)
    pass
```

**Run tests:**
```bash
pytest tests/test_enhanced_citations.py -v
```

---

### ?? Day 3: Citation Formatting

#### 9. Update Context Formatting (2 hours)

**File:** `src/rag.py`

**Find `format_context_for_llm` method** and update chunk formatting:

```python
# In the document grouping loop, update header format:

# Build enhanced citation
citation_parts = [filename]

if metadata.get('section_title'):
    citation_parts.append(f"Section: \"{metadata['section_title']}\"")

citation_parts.append(f"chunk {chunk_index}")

if metadata.get('page_number'):
    citation_parts.append(f"page {metadata['page_number']}")

citation = ", ".join(citation_parts)

# Format header
header = f"{marker} Source: {citation} ({int(similarity * 100)}% relevance):\n"
```

---

#### 10. Update System Prompt (15 min)

**File:** `src/app.py`

**Update citation guidance in `RAG_SYSTEM_PROMPT`:**

```python
CORE PRINCIPLES:
1. Use only information from the retrieved context
2. If information is missing, state: "I don't have that information"
3. Never invent or assume information not in the context
4. Cite sources with full details: (Source: filename, Section: "Title", chunk N, page M)
5. Express confidence: "strongly supported" vs. "mentioned once" vs. "inferred"
```

---

#### 11. End-to-End Testing (1 hour)

**Test the complete flow:**

```bash
# Start application
python -m src.app

# Upload a PDF through UI
# Query about content
# Verify response includes page numbers and sections
```

**Expected output:**
```
According to the documentation (Source: Legacy_Hosting.pdf, 
Section: "Data Storage", chunk 5, page 12), the backup 
procedures include...
```

---

#### 12. Documentation & Cleanup (30 min)

**Update README or docs:**
- Add note about enhanced citations
- Document new metadata format
- Update examples

**Clean up:**
```bash
# Run all tests
pytest tests/ -v

# Check code quality
flake8 src/

# Commit your changes
git add .
git commit -m "feat: Enhanced citations with page numbers and sections"
git push origin feature/enhanced-citations
```

---

## Success Checklist

- [ ] ? Migration script runs successfully
- [ ] ? PDFs extract with page numbers
- [ ] ? Section titles detected (80%+ of chunks)
- [ ] ? Metadata stored in database
- [ ] ? Metadata retrieved with chunks
- [ ] ? Citations show page numbers and sections
- [ ] ? All tests pass
- [ ] ? No performance degradation
- [ ] ? Documentation updated

---

## Troubleshooting

### Issue: Migration fails
```bash
# Check if column already exists
psql -d localchat -c "\d document_chunks"

# If column exists, skip migration
```

### Issue: Page numbers not appearing
```python
# Debug PDF loading
success, pages = doc_processor._load_pdf("test.pdf")
print(f"Loaded {len(pages)} pages")
print(f"First page: {pages[0]}")
# Should show page_number in output
```

### Issue: Section titles always None
```python
# Check extraction logic
text = "1. Introduction\n\nThis is content..."
title = doc_processor._extract_section_title(text)
print(f"Extracted: {title}")
# Should be None (starts with number)

text = "Introduction:\n\nThis is content..."
title = doc_processor._extract_section_title(text)
print(f"Extracted: {title}")
# Should be "Introduction"
```

---

## What's Next?

After completing Phase 1.1:

1. ? **Gather feedback** - Test with real users
2. ? **Measure impact** - Track citation usage
3. ? **Start Phase 1.2** - Query Rewriting (1-2 days)

---

## Need Help?

**Reference documents:**
- Full details: `PHASE_1.1_IMPLEMENTATION.md`
- Architecture: `OVERVIEW.md`
- Roadmap: `RAG_ROADMAP_2025.md`

**Common commands:**
```bash
# Run tests
pytest tests/ -v

# Check database
psql -d localchat

# View logs
tail -f logs/app.log

# Restart app
python -m src.app
```

---

**Ready to begin? Start with Day 1, Step 1!** ??

*Quick Start Guide Version: 1.0*  
*Estimated Time: 2-3 days*  
*Difficulty: Medium*  
*Risk: Low*
