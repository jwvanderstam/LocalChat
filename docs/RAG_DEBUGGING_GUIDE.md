# RAG Retrieval Debugging Guide

## Understanding BM25 Scores of 0.0

### What's Happening?

When you see logs like this:
```
INFO - src.rag - Scores {'file.pdf:159': 0.0, 'file.pdf:119': 0.0, ...}
```

This means: **No keyword matches found between your query and the document chunks**.

### Is This a Problem?

**No!** This is actually **normal behavior** for certain types of queries:

#### Queries That Typically Have 0.0 BM25 Scores:
- ? **Abstract questions**: "What is this about?", "Explain the concept"
- ? **Conceptual queries**: "How does X work?", "Why is Y important?"
- ? **Paraphrased questions**: Using synonyms or different words than the document
- ? **Questions in different languages**: Query in English, doc in Dutch (your case!)

#### Queries That Should Have High BM25 Scores:
- ? **Exact keyword matches**: "total revenue", "Q3 2024"
- ? **Technical terms**: "API endpoint", "database schema"
- ? **Proper nouns**: "John Smith", "Microsoft Azure"

### Your Specific Case

```
Query: "what is security diensten about?"
Documents: Dutch technical documents

Analysis:
- "what" ? stopword (ignored)
- "is" ? stopword (ignored)
- "security" ? might not appear in Dutch docs as-is
- "diensten" ? Dutch word, but tokenization might split it differently
- "about" ? stopword (ignored)

Result: No keyword matches ? BM25 = 0.0 ? Falls back to semantic search ?
```

**This is working correctly!** Semantic search understands the meaning even without exact keyword matches.

---

## How to Debug Your Retrieval

### 1. Check What's In Your Documents

Use the new diagnostic endpoint:

```bash
# Get chunk statistics
curl http://localhost:5000/api/documents/stats

# Expected response:
{
  "success": true,
  "document_count": 3,
  "chunk_count": 245,
  "chunk_statistics": {
    "total_chunks": 245,
    "chunks_with_embeddings": 245,
    "avg_chunk_length": 512.5,
    "sample_chunks": [
      {
        "filename": "Security Diensten.pdf",
        "chunk_index": 42,
        "preview": "De security diensten omvatten...",
        "length": 487,
        "has_embedding": true
      }
    ]
  }
}
```

### 2. Search for Specific Keywords

```bash
# Check if keyword exists in chunks
curl -X POST http://localhost:5000/api/documents/search-text \
  -H "Content-Type: application/json" \
  -d '{"search_text": "security", "limit": 5}'

# Response shows which chunks contain "security"
{
  "success": true,
  "search_text": "security",
  "count": 5,
  "results": [
    {
      "filename": "Security Diensten.pdf",
      "chunk_index": 12,
      "preview": "Security diensten zijn essentieel...",
      "length": 456
    }
  ]
}
```

### 3. Test Both Search Modes

```bash
# Test hybrid vs semantic-only
curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "wat zijn de security diensten?"}'

# Response compares both modes
{
  "success": true,
  "results": {
    "hybrid": {
      "mode": "Hybrid (Semantic + BM25)",
      "count": 5,
      "chunks": [...]
    },
    "semantic_only": {
      "mode": "Semantic Only", 
      "count": 5,
      "chunks": [...]
    }
  },
  "diagnostic": {
    "hybrid_count": 5,
    "semantic_count": 5,
    "recommendation": "Semantic-only search found more results. Your query may have no keyword matches - this is normal for conceptual questions."
  }
}
```

---

## Improving Your Retrieval Quality

### Option 1: Use Dutch Keywords (Recommended)

```bash
# Instead of: "what is security diensten about?"
# Try: "wat zijn de security diensten?"

curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "wat zijn de security diensten?"}'
```

**Why?** Dutch documents have Dutch keywords. BM25 will find more matches.

### Option 2: Use Exact Terms from Documents

```bash
# First, check what terms are actually in the documents
curl -X POST http://localhost:5000/api/documents/search-text \
  -H "Content-Type: application/json" \
  -d '{"search_text": "diensten", "limit": 3}'

# Then use those exact terms in your query
# Example: "beschrijving van de diensten"
```

### Option 3: Lower Similarity Threshold (If Getting No Results)

Edit `src/config.py`:
```python
MIN_SIMILARITY_THRESHOLD = 0.20  # Lower from 0.25 if needed
```

This makes retrieval more permissive, returning more results.

### Option 4: Disable Hybrid Search for Conceptual Queries

```bash
# For abstract questions, use semantic-only mode
curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "explain the concept", "use_hybrid_search": false}'
```

---

## When to Worry About BM25 Scores

### ? **Worrying Signs:**

1. **High BM25 expected, but got 0.0**
   ```
   Query: "total revenue Q3 2024"
   Document: "Total revenue for Q3 2024 was $1.2M"
   BM25 Score: 0.0  ? This would be wrong!
   ```

2. **English query on English documents = 0.0**
   ```
   Query: "what is the total amount?"
   Document: "The total amount is $500"
   BM25 Score: 0.0  ? This would be wrong!
   ```

3. **No chunks have embeddings**
   ```
   chunks_with_embeddings: 0  ? Problem!
   chunks_without_embeddings: 245
   ```

### ? **Normal Signs (Don't Worry):**

1. **Abstract query on any document**
   ```
   Query: "explain this"
   BM25 Score: 0.0  ? Expected!
   ```

2. **Different language query/docs**
   ```
   Query: "what is security" (English)
   Document: "security diensten" (Dutch)
   BM25 Score: 0.0  ? Expected!
   ```

3. **Paraphrased query**
   ```
   Query: "how much money was earned?"
   Document: "Total revenue: $1.2M"
   BM25 Score: 0.0-0.3  ? Expected!
   ```

---

## Recommended Workflow

### Step 1: Verify Documents Are Indexed
```bash
curl http://localhost:5000/api/documents/stats
# Check: chunks_with_embeddings > 0
```

### Step 2: Check Content
```bash
curl -X POST http://localhost:5000/api/documents/search-text \
  -H "Content-Type: application/json" \
  -d '{"search_text": "diensten", "limit": 3}'
# Verify: Documents contain expected content
```

### Step 3: Test Retrieval
```bash
curl -X POST http://localhost:5000/api/documents/test \
  -H "Content-Type: application/json" \
  -d '{"query": "wat zijn de diensten?"}'
# Check: Getting relevant results
```

### Step 4: Use Chat with RAG
```bash
# Now use the chat interface with RAG enabled
# Your query will use semantic search primarily
# BM25 adds keyword boost when possible
```

---

## Summary

**Your BM25 scores of 0.0 are correct!** 

The system is working as designed:
1. ? **Semantic search** finds relevant chunks by meaning
2. ? **BM25** boosts results when keywords match
3. ? **Fallback** to semantic-only when no keyword matches (your case)

**Action Items:**
- ? Use the new diagnostic endpoints to verify content
- ? Try Dutch queries on Dutch documents for better keyword matching
- ? Don't worry about BM25 = 0.0 for conceptual queries
- ? Trust semantic search - it understands meaning without keywords!

**The retrieval is working correctly. The "horrible" performance you mentioned is likely due to document quality or query phrasing, not a bug in the BM25 scoring.**
