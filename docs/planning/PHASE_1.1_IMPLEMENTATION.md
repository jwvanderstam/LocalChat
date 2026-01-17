# Phase 1.1 Implementation: Enhanced Citations

## Current Status
**Priority:** High  
**Effort:** 2-3 days  
**Impact:** High - Better source verification and user trust  

## Architecture Changes Needed

### 1. Database Schema Enhancement

**Current:**
```sql
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER,
    chunk_text TEXT,
    chunk_index INTEGER,
    embedding vector(768),
    created_at TIMESTAMP
)
```

**Enhanced:**
```sql
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER,
    chunk_text TEXT,
    chunk_index INTEGER,
    embedding vector(768),
    metadata JSONB,  -- NEW: Store page_number, section_title
    created_at TIMESTAMP
)
```

**Migration SQL:**
```sql
-- Add metadata column
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- Create GIN index for metadata queries
CREATE INDEX IF NOT EXISTS document_chunks_metadata_idx 
ON document_chunks USING GIN (metadata);
```

---

### 2. PDF Extraction Enhancement

**File:** `src/rag.py` - `_load_pdf` method

**Current Approach:**
- Extracts all pages into single text string
- No page number tracking

**Enhanced Approach:**
```python
def _load_pdf_with_pages(self, file_path: str) -> Tuple[bool, Union[List[Dict], str]]:
    """
    Load PDF with page-by-page tracking.
    
    Returns:
        Tuple of (success, List[page_data] or error_message)
        
        page_data = {
            'page_number': int,
            'text': str,
            'has_tables': bool,
            'section_title': Optional[str]  # Extracted from headings
        }
    """
    pages = []
    
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text()
            tables = page.extract_tables()
            
            # Extract section title (look for large/bold text at page start)
            section_title = self._extract_section_title(page_text)
            
            pages.append({
                'page_number': page_num,
                'text': page_text,
                'has_tables': len(tables) > 0,
                'section_title': section_title
            })
    
    return True, pages
```

**Section Title Extraction:**
```python
def _extract_section_title(self, page_text: str) -> Optional[str]:
    """
    Extract likely section title from page text.
    
    Rules:
    - First non-empty line
    - Under 100 characters
    - Ends with colon or is title-cased
    - Not a numbered list item
    """
    lines = page_text.strip().split('\n')
    
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        
        # Skip empty lines
        if not line:
            continue
            
        # Skip numbered lines (1., 2., etc.)
        if re.match(r'^\d+\.', line):
            continue
        
        # Check if looks like a title
        if (len(line) < 100 and 
            (line.endswith(':') or line.istitle())):
            return line.rstrip(':')
    
    return None
```

---

### 3. Chunking with Page Tracking

**File:** `src/rag.py` - `_chunk_document` method

**Enhanced:**
```python
def _chunk_document_with_metadata(
    self, 
    pages: List[Dict],
    chunk_size: int = 1200,
    overlap: int = 150
) -> List[Dict]:
    """
    Chunk document while preserving page numbers and sections.
    
    Returns:
        List[{
            'text': str,
            'page_number': int,
            'section_title': str,
            'chunk_index': int
        }]
    """
    chunks_with_metadata = []
    global_chunk_index = 0
    
    current_section = None
    
    for page_data in pages:
        page_num = page_data['page_number']
        page_text = page_data['text']
        section_title = page_data['section_title'] or current_section
        
        # Update current section if found
        if page_data['section_title']:
            current_section = page_data['section_title']
        
        # Chunk the page text
        page_chunks = self._chunk_text_standard(
            page_text, 
            chunk_size, 
            overlap
        )
        
        # Add metadata to each chunk
        for chunk_text in page_chunks:
            chunks_with_metadata.append({
                'text': chunk_text,
                'page_number': page_num,
                'section_title': section_title,
                'chunk_index': global_chunk_index
            })
            global_chunk_index += 1
    
    return chunks_with_metadata
```

---

### 4. Database Storage Update

**File:** `src/db.py` - `insert_chunks` method

**Enhanced:**
```python
def insert_chunks(self, chunks_with_metadata: List[Dict], embeddings, document_id: int):
    """
    Insert chunks with metadata.
    
    Args:
        chunks_with_metadata: List of chunk dictionaries with metadata
        embeddings: Numpy array of embeddings
        document_id: Document ID
    """
    with self.get_connection() as conn:
        with conn.cursor() as cursor:
            for idx, chunk_data in enumerate(chunks_with_metadata):
                metadata = {
                    'page_number': chunk_data.get('page_number'),
                    'section_title': chunk_data.get('section_title')
                }
                
                cursor.execute("""
                    INSERT INTO document_chunks 
                    (document_id, chunk_text, chunk_index, embedding, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    document_id,
                    chunk_data['text'],
                    chunk_data['chunk_index'],
                    embeddings[idx].tolist(),
                    Json(metadata)  # psycopg Json adapter
                ))
            
            conn.commit()
```

---

### 5. Retrieval Update

**File:** `src/db.py` - `search_similar_chunks` method

**Enhanced to return metadata:**
```python
def search_similar_chunks(self, query_embedding, top_k: int = 10):
    """
    Search similar chunks and return metadata.
    
    Returns:
        List[(chunk_text, filename, chunk_index, similarity, metadata)]
    """
    with self.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    dc.chunk_text,
                    d.filename,
                    dc.chunk_index,
                    1 - (dc.embedding <=> %s::vector) as similarity,
                    dc.metadata  -- NEW: Include metadata
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE 1 - (dc.embedding <=> %s::vector) > %s
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            """, (
                query_embedding,
                query_embedding,
                config.MIN_SIMILARITY_THRESHOLD,
                query_embedding,
                top_k
            ))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'chunk_text': row[0],
                    'filename': row[1],
                    'chunk_index': row[2],
                    'similarity': row[3],
                    'metadata': row[4] or {}  # Parse JSONB
                })
            
            return results
```

---

### 6. Citation Format Update

**File:** `src/rag.py` - `format_context_for_llm` method

**Enhanced citation format:**
```python
def _format_chunk_header(
    self, 
    filename: str, 
    chunk_index: int, 
    similarity: float,
    metadata: Dict
) -> str:
    """
    Format chunk header with enhanced citation info.
    
    Returns:
        "*** Source 1: filename.pdf, Section: 'Title', chunk 5, page 12 (92% match)"
    """
    # Determine marker
    if similarity >= 0.80:
        marker = "***"
    elif similarity >= 0.65:
        marker = " + "
    else:
        marker = " - "
    
    # Build citation parts
    citation_parts = [filename]
    
    if metadata.get('section_title'):
        citation_parts.append(f"Section: \"{metadata['section_title']}\"")
    
    citation_parts.append(f"chunk {chunk_index}")
    
    if metadata.get('page_number'):
        citation_parts.append(f"page {metadata['page_number']}")
    
    # Join with commas
    citation = ", ".join(citation_parts)
    
    # Format: "*** Source 1: file.pdf, Section: 'Title', chunk 5, page 12 (92%)"
    return f"{marker} Source: {citation} ({int(similarity * 100)}% relevance):\n"
```

**Example Output:**
```
*** Source: Legacy_Hosting.pdf, Section: "Data Storage", chunk 5, page 12 (92% relevance):
Data storage operations include backup procedures...

+ Source: Private_Cloud.pdf, chunk 3, page 8 (78% relevance):
Business continuity management includes...
```

---

### 7. System Prompt Update

**File:** `src/app.py` - `RAG_SYSTEM_PROMPT`

**Update citation guidance:**
```python
CORE PRINCIPLES:
...
4. Cite sources with full details: (Source: filename, Section: "Title", chunk N, page M)
5. Express confidence: "strongly supported" vs. "mentioned once" vs. "inferred"
```

---

## Implementation Steps

### Day 1: Database & Schema (3-4 hours)

**Tasks:**
1. ? Add metadata column to document_chunks table
2. ? Create migration script
3. ? Test with sample data
4. ? Update database insertion methods

**Files to modify:**
- `src/db.py` (schema, insert, search methods)
- `scripts/migrate_add_metadata.py` (new migration script)

**Testing:**
```python
# Test metadata storage
db.insert_chunk_with_metadata(
    chunk_text="Test",
    metadata={'page_number': 5, 'section_title': 'Introduction'}
)

# Verify storage
result = db.search_chunks("test")[0]
assert result['metadata']['page_number'] == 5
```

---

### Day 2: PDF Extraction (4-5 hours)

**Tasks:**
1. ? Enhance PDF loading to track pages
2. ? Implement section title extraction
3. ? Update chunking to preserve metadata
4. ? Test with real PDFs

**Files to modify:**
- `src/rag.py` (_load_pdf, _chunk_document methods)

**Testing:**
```python
# Test with real PDF
pages = doc_processor._load_pdf_with_pages("test.pdf")
assert all('page_number' in p for p in pages)

# Test chunking
chunks = doc_processor._chunk_document_with_metadata(pages)
assert all('page_number' in c for c in chunks)
assert all('section_title' in c for c in chunks)
```

---

### Day 3: Citation & Integration (3-4 hours)

**Tasks:**
1. ? Update context formatting
2. ? Enhance citation format
3. ? Update system prompt
4. ? End-to-end testing

**Files to modify:**
- `src/rag.py` (format_context_for_llm)
- `src/app.py` (RAG_SYSTEM_PROMPT)

**Testing:**
```python
# Test full flow
doc_id = doc_processor.ingest_document("test.pdf")
results = doc_processor.retrieve_context("test query")
formatted = doc_processor.format_context_for_llm(results)

# Verify enhanced citations
assert "page" in formatted
assert "Section:" in formatted
```

---

## Migration Script

**File:** `scripts/migrate_add_metadata.py`

```python
#!/usr/bin/env python3
"""
Add metadata column to existing document_chunks.

For existing chunks without metadata:
- Set page_number = None
- Set section_title = None
- Will be populated on next re-index
"""

from src.db import db
from src.utils.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

def migrate():
    """Add metadata column and index."""
    logger.info("Starting metadata migration...")
    
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Add column if not exists
            cursor.execute("""
                ALTER TABLE document_chunks 
                ADD COLUMN IF NOT EXISTS metadata JSONB 
                DEFAULT '{}'::jsonb;
            """)
            
            # Create index
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS document_chunks_metadata_idx 
                ON document_chunks USING GIN (metadata);
            """)
            
            # Update existing rows with empty metadata
            cursor.execute("""
                UPDATE document_chunks 
                SET metadata = '{}'::jsonb 
                WHERE metadata IS NULL;
            """)
            
            conn.commit()
    
    logger.info("Migration complete!")
    logger.info("Note: Existing documents will need to be re-indexed for full metadata")

if __name__ == '__main__':
    migrate()
```

---

## Testing Checklist

### Unit Tests
- [ ] Metadata storage and retrieval
- [ ] Page number extraction from PDFs
- [ ] Section title detection
- [ ] Citation format with metadata

### Integration Tests
- [ ] End-to-end: Upload PDF ? Chunk ? Store ? Retrieve ? Format
- [ ] Multiple PDFs with different structures
- [ ] PDFs without clear sections (fallback behavior)

### Quality Tests
- [ ] Citations are accurate (page numbers match PDF)
- [ ] Section titles are relevant
- [ ] No performance degradation

---

## Expected Results

### Before
```
Query: "What are the backup procedures?"

Response:
According to the retrieved documents (Source: Legacy_Hosting.pdf, chunk 5), 
backup procedures include...
```

### After
```
Query: "What are the backup procedures?"

Response:
According to the retrieved documents (Source: Legacy_Hosting.pdf, 
Section: "Data Storage", chunk 5, page 12), backup procedures include...

Users can now verify this information on page 12 of the source document.
```

---

## Success Metrics

- [ ] **100% of chunks** have page numbers (for PDFs)
- [ ] **80%+ of chunks** have section titles
- [ ] **No performance degradation** (< 5% slower ingestion)
- [ ] **User feedback:** Improved trust and verification
- [ ] **Zero migration issues** with existing documents

---

## Rollback Plan

If issues arise:
```sql
-- Remove metadata column
ALTER TABLE document_chunks DROP COLUMN IF EXISTS metadata;

-- Revert code changes
git checkout main src/db.py src/rag.py src/app.py
```

---

## Next Steps After Completion

Once enhanced citations are working:
1. ? User testing and feedback
2. ? Documentation update
3. ? **Start Phase 1.2:** Query Rewriting (1-2 days)
4. ? **Start Phase 1.3:** Conversation Memory (3-4 days)

---

**Status:** Ready to implement  
**Estimated Completion:** End of Day 3  
**Risk Level:** Low (additive changes, no breaking changes)  
**Dependencies:** None (standalone feature)

---

*Implementation Guide Version: 1.0*  
*Created: January 2025*  
*See: RAG_ROADMAP_2025.md for full context*
