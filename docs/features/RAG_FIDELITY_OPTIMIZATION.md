# RAG Fidelity Optimization - 90%+ Exact Match Goal

**Date:** January 18, 2026  
**Goal:** Achieve 90%+ fidelity (exact text matching) in RAG responses  
**Status:** ?? IN PROGRESS

---

## Problem Statement

**Current Issues:**
- ? LLM inventing words ("overzichtskijk", "Appliacatien", "eieren")
- ? Paraphrasing instead of copying exact text
- ? Garbled output at end of responses
- ? Low fidelity to source documents

**Root Causes:**
1. **Prompt issues:** LLM not strictly copying text
2. **Chunk size issues:** 1200-token chunks too large for precise retrieval
3. **Overlap issues:** 12.5% overlap insufficient for context continuity

---

## Solution: Two-Pronged Approach

### 1. Prompt Optimization ? DONE
**Changed to Perplexity-style prompt:**
- Every sentence must start with verbatim quote
- Prefix format: `[source: filename, p.X]: [exact text]`
- Explicit reasoning steps
- Clear output structure

**Commit:** `1a3f667` + Latest

---

### 2. Chunking Optimization ?? NEW

**Changed Parameters:**

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| CHUNK_SIZE | 1200 tokens | **300 tokens** | Smaller = more precise retrieval |
| CHUNK_OVERLAP | 150 tokens (12.5%) | **60 tokens (20%)** | Better context continuity |
| TOP_K_RESULTS | 20 | **10** | Focus on quality over quantity |
| MIN_SIMILARITY | 0.30 | **0.40** | Higher quality threshold |
| RERANK_TOP_K | 4 | **6** | More chunks for comprehensive answers |

---

## Why 300 Tokens + 20% Overlap?

### Chunking Theory

**Smaller Chunks (300 tokens) Benefits:**
1. ? **Precise retrieval** - Each chunk is focused on one topic
2. ? **Less noise** - Don't retrieve irrelevant surrounding text
3. ? **Better embeddings** - Semantic meaning more concentrated
4. ? **Easier to copy** - LLM can copy 300 tokens verbatim more easily than 1200

**20% Overlap Benefits:**
1. ? **Context preservation** - Important sentences at chunk boundaries aren't lost
2. ? **Better continuity** - Related concepts span across chunks smoothly
3. ? **Industry standard** - Proven effective in production RAG systems

**Example:**
```
Chunk 1 (tokens 0-300): "... ends with service requirements."
                         [overlap: tokens 240-300]
Chunk 2 (tokens 240-540): "service requirements. Additional specifications..."
```

---

## Testing Strategy

### 1. Fidelity Test Script

**Created:** `scripts/test_rag_fidelity.py`

**What it tests:**
- Word exact-match ratio
- Detection of invented words ("eieren", "overzichtskijk")
- Sample text quality
- Overall fidelity score

**Usage:**
```bash
python scripts/test_rag_fidelity.py
```

**Goal:** 90%+ average fidelity across test queries

---

### 2. Test Queries

```python
test_queries = [
    ("eisen voor cloud hosting", ["eisen", "cloud", "hosting"]),
    ("service level agreements", ["service", "level"]),
    ("technisch applicatiebeheer", ["technisch", "applicatiebeheer"]),
    ("backup procedures", ["backup"]),
    ("disaster recovery", ["disaster", "recovery"]),
]
```

---

### 3. Metrics

**Per Query:**
- ? Word match ratio (% of expected words found exactly)
- ? Invented words count
- ? Sample text quality

**Overall:**
- ? Average fidelity across all queries
- ? Total invented words
- ? Goal achievement (>=90%)

---

## Implementation Steps

### Step 1: Update Config ? DONE
```python
# src/config.py
CHUNK_SIZE = 300              # Was 1200
CHUNK_OVERLAP = 60            # Was 150 (20% of 300)
TOP_K_RESULTS = 10            # Was 20
MIN_SIMILARITY_THRESHOLD = 0.40  # Was 0.30
RERANK_TOP_K = 6              # Was 4
```

### Step 2: Create Test Script ? DONE
- Created `scripts/test_rag_fidelity.py`
- Implements exact-match scoring
- Detects invented words
- Measures overall fidelity

### Step 3: Re-ingest Documents ?? TODO
**IMPORTANT:** Existing chunks use old 1200-token size!

```bash
# Option 1: Clear and re-upload through UI
# Option 2: Run migration script
python scripts/reingest_documents.py
```

### Step 4: Run Tests ?? TODO
```bash
python scripts/test_rag_fidelity.py
```

### Step 5: Iterate ?? TODO
- If fidelity < 90%, adjust parameters
- Test different chunk sizes (200, 300, 400)
- Test different overlaps (15%, 20%, 25%)
- Fine-tune similarity threshold

---

## Expected Improvements

### Before Optimization
- ? Chunk size: 1200 tokens (too large)
- ? Overlap: 12.5% (too small)
- ? Fidelity: ~60-70% (estimated)
- ? Invented words: Multiple per response

### After Optimization
- ? Chunk size: 300 tokens (precise)
- ? Overlap: 20% (standard)
- ? Fidelity: **Target 90%+**
- ? Invented words: **Target 0**

---

## Validation Checklist

**Before deployment:**
- [ ] Run `python scripts/test_rag_fidelity.py`
- [ ] Check fidelity >= 90%
- [ ] Verify 0 invented words
- [ ] Test with real user queries
- [ ] Compare before/after quality

**After deployment:**
- [ ] Monitor fidelity in production
- [ ] Collect user feedback
- [ ] Adjust parameters if needed
- [ ] Document any issues

---

## Rollback Plan

**If optimization degrades quality:**

```bash
# Revert config changes
git checkout HEAD~1 -- src/config.py

# Re-ingest with old parameters
python scripts/reingest_documents.py
```

**Old values:**
```python
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
TOP_K_RESULTS = 20
MIN_SIMILARITY_THRESHOLD = 0.30
RERANK_TOP_K = 4
```

---

## References

**Industry Best Practices:**
- LangChain recommends 300-500 tokens for most use cases
- 20-25% overlap is standard for context preservation
- Smaller chunks = better precision, larger = better context
- Balance depends on document type and query complexity

**Related Documentation:**
- `docs/features/PHASE_1.1_ENHANCED_CITATIONS.md`
- `docs/planning/RAG_ROADMAP_2025.md`
- `src/config.py` - Configuration parameters

---

## Next Steps

1. ? **Update configuration** - Parameters optimized
2. ? **Create test script** - Fidelity testing ready
3. ?? **Re-ingest documents** - Use new chunk size
4. ?? **Run tests** - Measure improvements
5. ?? **Deploy if 90%+ achieved** - Or iterate

---

**Status:** Ready for testing after document re-ingestion  
**Priority:** HIGH - Fixes critical accuracy issues  
**Impact:** Should eliminate word invention and improve fidelity significantly
