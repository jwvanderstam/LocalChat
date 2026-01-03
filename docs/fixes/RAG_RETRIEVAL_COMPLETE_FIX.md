# RAG RETRIEVAL NOT WORKING - COMPLETE FIX GUIDE

## ? **PROBLEM IDENTIFIED**

**Symptom**: RAG retrieval returns 0 results even though documents are uploaded.

```
INFO - src.rag - Database search returned 0 results
WARNING - src.rag - No chunks passed similarity threshold 0.22
```

**Root Cause**: Embeddings are stored as **TEXT strings** instead of PostgreSQL **VECTOR** type in the database.

### Evidence from Diagnostic:
```
Sample embedding type: <class 'str'>      # ? WRONG! Should be list/vector
Sample embedding length: 8547             # ? String length, not 768 dimensions!
```

The database contains strings like `"[0.123,0.456,...]"` instead of proper vector objects.

---

## ?? **IMMEDIATE SOLUTION**

### Step 1: Clear Corrupted Data
```bash
cd C:\Users\Gebruiker\Desktop\source\repos\LocalChat

python -c "from src.db import db; db.initialize(); db.delete_all_documents(); print('? Database cleared - ready for re-upload')"
```

### Step 2: Restart Application
```bash
python app.py
```

### Step 3: Re-Upload Documents
1. Open http://localhost:5000/documents
2. Click "Choose Files"
3. Select your PDF/TXT/DOCX files
4. Click "Upload Documents"
5. Wait for processing to complete (watch progress bar)

### Step 4: Verify Fix
1. Go to "Test RAG Retrieval" section
2. Enter a test query like "What is this about?"
3. Click "Test Retrieval"
4. You should see results with similarity scores

---

## ?? **WHY THIS HAPPENED**

The embeddings were inserted with incorrect format in an earlier version of the code. The current code is correct, but the existing data was corrupted.

**How Data Was Stored (Incorrectly)**:
```sql
-- Stored as TEXT string
embedding = "[0.123,0.456,0.789,...]"  -- String with 8547 characters
```

**How Data Should Be Stored (Correctly)**:
```sql
-- Stored as VECTOR type
embedding = vector([0.123,0.456,0.789,...])  -- Actual 768-dimension vector
```

---

## ?? **VERIFICATION AFTER FIX**

### Run Diagnostic Script:
```bash
python scripts/diagnose_rag.py
```

**Expected Output After Fix**:
```
Sample embedding type: <class 'list'>     # ? CORRECT!
Sample embedding length: 768              # ? Correct dimension!
Search returned: 5 results                # ? Working!
```

### Test in Browser:
1. Go to http://localhost:5000/documents
2. Upload a document
3. Test retrieval with a query
4. Should see matching chunks with similarity scores
5. Go to http://localhost:5000/chat
6. Toggle RAG ON
7. Ask a question about your document
8. Should get relevant answer with context

---

## ?? **TECHNICAL DETAILS**

### The Problem:
```python
# OLD/BROKEN insertion (resulted in TEXT storage)
embedding_str = self._embedding_to_pg_array(embedding)  # "[0.1,0.2,...]"
cursor.execute("INSERT ... VALUES (%s)", (embedding_str,))
# PostgreSQL received it as TEXT, not VECTOR
```

### The Fix (Current Code):
```python
# CURRENT/WORKING insertion
embedding_str = self._embedding_to_pg_array(embedding)  # "[0.1,0.2,...]"
cursor.execute("INSERT ... VALUES (%s::vector)", (embedding_str,))
#                                      ^^^^^^^^^^
#                                      Explicit cast to vector type
```

The `::vector` cast tells PostgreSQL to treat the string as a vector type, not plain text.

---

## ?? **PREVENTION**

To prevent this in the future, the code now:
1. ? Explicitly casts to `::vector` type in SQL
2. ? Validates embedding format before insertion
3. ? Logs embedding type and dimensions
4. ? Checks vector search is working after insertion

---

## ?? **COMMON MISTAKES TO AVOID**

### ? DON'T:
- Upload documents and immediately expect them to work
- Skip the database clearing step
- Try to "fix" the existing data (not possible)

### ? DO:
- Clear the database first
- Re-upload ALL documents
- Wait for processing to complete
- Test retrieval before using chat

---

## ?? **CHECKLIST**

Before claiming RAG is working:
- [ ] Database cleared (`db.delete_all_documents()`)
- [ ] Application restarted
- [ ] Documents re-uploaded via web interface
- [ ] Upload shows "Success" messages
- [ ] Test retrieval returns results (in Documents page)
- [ ] RAG toggle works in chat
- [ ] Chat responses include document context
- [ ] No "No results" warnings in console

---

## ?? **TROUBLESHOOTING**

### Still No Results After Re-upload?

**1. Check Ollama is running:**
```bash
curl http://localhost:11434/api/tags
```

**2. Check embedding model:**
```bash
ollama list | grep nomic-embed-text
```

**3. Check database connection:**
```bash
python -c "from src.db import db; print('Connected' if db.initialize()[0] else 'Failed')"
```

**4. Check chunks were created:**
```bash
python -c "from src.db import db; db.initialize(); print(f'Chunks: {db.get_chunk_count()}')"
```

**5. Run full diagnostic:**
```bash
python scripts/diagnose_rag.py
```

---

## ?? **EXPECTED BEHAVIOR AFTER FIX**

### Document Upload:
```
? Processing document.pdf...
? Chunking document...
? Generated 42 chunks
? Generating embeddings...
? Processing: 100% (42/42 chunks)
? Successfully ingested document.pdf (42 chunks)
```

### Test Retrieval:
```
Query: "What is the revenue?"
? Retrieved 5 chunks:
  1. document.pdf chunk 15: 0.892
  2. document.pdf chunk 16: 0.854
  3. document.pdf chunk 14: 0.823
  ...
```

### Chat with RAG:
```
User: "What was the revenue in Q1?"
Assistant: "According to the document, the revenue in Q1 was $2.5M. [Source: document.pdf]"
```

---

## ?? **SUCCESS INDICATORS**

When RAG is working correctly, you'll see in console:
```
INFO - src.rag - Using embedding model: nomic-embed-text:latest
INFO - src.rag - Generated query embedding: dimension 768
INFO - src.rag - Database search returned 5 results      # ? Not 0!
INFO - src.rag - Chunk: document.pdf #15 (sim: 0.892)
[CHAT API] Retrieved 5 chunks                            # ? Not 0!
[CHAT API] Context added to message (total length: 2543)
```

---

## ?? **FINAL NOTES**

### Why Re-upload is Required:
- Embeddings cannot be "converted" from TEXT to VECTOR
- Database migration would be complex and error-prone
- Re-uploading is faster and guarantees correctness

### One-Time Fix:
- This is a ONE-TIME issue
- Once you re-upload, data will be stored correctly
- Future uploads will work fine

### Time Required:
- Clearing database: < 1 second
- Re-uploading documents: ~30 seconds per document
- Testing: ~10 seconds

**Total time**: Usually < 5 minutes

---

## ?? **SUMMARY**

| Step | Action | Time | Status |
|------|--------|------|--------|
| 1 | Clear database | 1s | Required |
| 2 | Restart app | 10s | Required |
| 3 | Re-upload docs | 30s/doc | Required |
| 4 | Test retrieval | 10s | Verify |
| 5 | Test chat | 10s | Verify |

**Total**: ~5 minutes to complete fix

---

## ?? **SUPPORT**

If RAG still doesn't work after following this guide:

1. Run diagnostic: `python scripts/diagnose_rag.py`
2. Check logs: `logs/app.log`
3. Verify services: Ollama + PostgreSQL running
4. Check documentation: `docs/fixes/`

---

**Status**: ? FIX DOCUMENTED  
**Action Required**: Clear database and re-upload documents  
**Time to Fix**: ~5 minutes  
**Complexity**: Easy (just re-upload)  
**Prevention**: Automatic (current code is correct)

