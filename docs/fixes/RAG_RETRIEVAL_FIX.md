# RAG NOT WORKING - ROOT CAUSE IDENTIFIED

## Problem
Embeddings are stored as **STRING** in database instead of PostgreSQL **VECTOR** type!

### Evidence
```
Sample embedding type: <class 'str'>
Sample embedding length: 8547  # String length, not vector dimension!
```

This means the embeddings look like:
```
"[0.123,0.456,0.789,...]"  # TEXT STRING
```

Instead of:
```
vector([0.123,0.456,0.789,...])  # PROPER VECTOR TYPE
```

## Root Cause
The `insert_chunks_batch()` method in `db.py` is converting embeddings to strings:
```python
embedding_str = self._embedding_to_pg_array(embedding)  # Creates "[0.1,0.2,...]"
cursor.execute("... VALUES (%s)", (embedding_str,))      # Inserts as STRING!
```

The `::vector` cast is missing or not working properly.

## Solution

### Immediate Fix Required:
You need to **re-upload ALL documents** so they use the correct embedding format.

### Steps:

1. **Clear the database**:
   ```python
   python -c "from src.db import db; db.initialize(); db.delete_all_documents(); print('Database cleared')"
   ```

2. **Start the app**:
   ```bash
   python app.py
   ```

3. **Re-upload documents** via http://localhost:5000/documents

The existing code should work - the issue is that your current data was inserted with the wrong format.

## Technical Details

The `_embedding_to_pg_array` method creates a string like `[val1,val2,...]` and the SQL uses `%s::vector` cast, but PostgreSQL is receiving it as a string parameter and not casting it properly.

The correct approach used by the current code should be:
- Pass embedding as Python list
- Use `_embedding_to_pg_array()` to format it
- Cast with `::vector` in SQL

But somehow the data got inserted as raw strings.

## Verification After Re-upload

Run this to check:
```python
python scripts/diagnose_rag.py
```

You should see:
```
Sample embedding type: <class 'list'>  # or numpy.ndarray
Sample embedding length: 768           # Correct dimension!
```

## Why This Happened

Possible causes:
1. Documents were uploaded with an older version of the code
2. The `::vector` cast wasn't working in a previous version
3. Database schema was created before pgvector was properly installed

## Action Required

**CRITICAL**: Delete all documents and re-upload them.

This will fix the RAG retrieval immediately!
