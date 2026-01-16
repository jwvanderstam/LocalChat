# RAG Synthesis Fix - Better Summaries

## The Problem You Showed Me

**Query:** "summarize these documents"  
**Result:** Mechanical listing of 6 sources, no actual summary  
**Root Cause:** RAG treated summary like a fact-finding query

## What Was Wrong

### 1. System Prompt Too Prescriptive
- Forced citation for every statement
- Made LLM list chunks mechanically
- No guidance for synthesis vs. fact-finding

### 2. Too Many Small Chunks (6 from 2 documents)
- LLM treated each chunk as separate item
- Listed them one-by-one
- No synthesis across chunks

### 3. Poor Context Organization
- Chunks mixed across documents
- No document grouping
- Hard for LLM to see document boundaries

## Changes Made

### 1. Improved System Prompt
**Added query-type awareness:**
```
For specific questions: Answer with facts, cite sources
For summaries: Synthesize across sources, create narrative
```

**Before:** "Always cite sources for every fact"  
**After:** "For summaries, synthesize and create cohesive narrative"

### 2. Reduced Chunk Count
- **Was:** 6 chunks (too fragmented)
- **Now:** 4 chunks (better for synthesis)
- **Config:** RERANK_TOP_K = 6 ? 4

### 3. Document-Grouped Context Format
**Before:**
```
Source 1: doc1.pdf (chunk 5)
Source 2: doc2.pdf (chunk 3)
Source 3: doc1.pdf (chunk 7)
Source 4: doc2.pdf (chunk 8)
...
```

**After:**
```
Context from 2 documents:

=== Document 1: doc1.pdf ===
*** Section (chunk 5, 92% relevance):
[content]

+ Section (chunk 7, 78% relevance):
[content]

=== Document 2: doc2.pdf ===
*** Section (chunk 3, 85% relevance):
[content]
```

**Benefits:**
- Clear document boundaries
- Chunks grouped by source
- Easier for LLM to synthesize

### 4. Optimized Retrieval
- TOP_K_RESULTS: 30 ? 20 (fewer candidates)
- MIN_SIMILARITY: 0.25 ? 0.30 (higher quality)
- Focus on quality over quantity

## Expected Results

### For "Summarize" Queries
**Before:**
- Lists each source separately
- Mechanical "Source 1 says..., Source 2 says..."
- No synthesis

**After:**
- Cohesive summary across both documents
- Main themes identified
- Natural narrative flow
- Document names mentioned contextually

### Example Expected Output
```
These documents cover data storage and cloud hosting management:

The Legacy Hosting document (Bijlage 2-005) details data storage 
operations including backup procedures, archiving workflows, and 
different storage classes (Near-Line Business, Near-Line Tape). 
Key activities include request management, monitoring, and SLA 
compliance with typical timelines of 15 minutes to 1 day for changes.

The Private Cloud Hosting document (Bijlage 2-006) focuses on 
business continuity and disaster recovery, including maintaining 
DR plans, operational recovery procedures, and annual BC reporting. 
It references alignment with general service standards from 
Bijlage 2-002.

Together, these documents establish comprehensive guidelines for 
both legacy and cloud-based hosting environments with emphasis on 
data protection and service continuity.
```

## Configuration Changes

### src/config.py
```python
TOP_K_RESULTS = 20        # Was: 30
MIN_SIMILARITY = 0.30     # Was: 0.25
RERANK_TOP_K = 4          # Was: 6
```

### src/rag.py
- Groups chunks by document
- Document-based formatting
- Better for synthesis

### src/app.py
- Query-aware system prompt
- Different guidance for summaries vs. questions

## Testing

**Restart the application:**
```bash
python -m src.app
```

**Test with:**
1. "Summarize these documents" - Should give cohesive summary
2. "What is X?" - Should answer with citations
3. "List all..." - Should extract and list
4. "Compare..." - Should synthesize comparison

## Why This Fixes Your Issue

**Your Example:**
- 2 documents, 6 fragments ? mechanical listing
- No synthesis, just regurgitation

**After Fix:**
- 2 documents, 4 grouped chunks ? cohesive summary
- LLM sees document structure
- Prompted to synthesize for summaries
- Natural narrative instead of list

## Impact

? **Better summaries** - Synthesizes across sources  
? **Document awareness** - Groups by document  
? **Query-appropriate** - Different handling for different query types  
? **Fewer chunks** - 4 instead of 6, more focused  
? **Higher quality** - Better threshold (0.30 vs 0.25)  

**Result:** LLM will actually summarize instead of listing!
