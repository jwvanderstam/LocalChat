# RAG Duplicate Fix

## Issues Identified

1. **Context window expansion was broken**
   - Function existed but did nothing
   - May have been causing duplicate entries
   - Solution: Disabled until properly implemented

2. **No duplicate detection**
   - Same chunks could appear multiple times
   - Different sorting could create apparent duplicates
   - Solution: Added strict deduplication by (filename, chunk_index)

3. **Too many results (15 chunks)**
   - Overwhelming the LLM
   - Creating confusing, repetitive responses
   - Solution: Reduced to 8 chunks

## Fixes Applied

### 1. Disabled Context Expansion
- **Was:** Calling _expand_context_windows() (broken)
- **Now:** Disabled with comment explaining why
- **Impact:** Prevents duplicate generation

### 2. Added Strict Deduplication
`python
key = (filename, chunk_index)
if key not in seen:
    seen.add(key)
    results.append(chunk)
``n- **Impact:** Guarantees unique chunks only

### 3. Reduced Result Count
- **Was:** 15 chunks (RERANK_TOP_K = 15)
- **Now:** 8 chunks (RERANK_TOP_K = 8)
- **Impact:** Cleaner, more focused responses

### 4. Better Candidate Pool
- **Was:** 60 initial candidates
- **Now:** 50 initial candidates (still plenty)
- **Threshold:** 0.25 (balanced)

## Expected Improvements

✅ **No duplicate chunks**
   - Strict deduplication by (filename, chunk_index)
   
✅ **Correct document count**
   - Will show actual number of unique documents
   
✅ **No repeated text**
   - Each chunk appears once only
   
✅ **Better quality responses**
   - 8 focused chunks vs 15 overwhelming chunks
   - LLM can process information better

## Testing

Restart application and test:1. Query should show correct number of documents
2. No duplicate text in response
3. Response should be coherent, not jumbled
4. Should list unique document names
