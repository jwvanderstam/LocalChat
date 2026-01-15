# RAG Quality Boost - Maximum Resources

## Changes Applied

### 1. Context Window: 30KB → 50KB (+67%)
- **Was:** 30,000 characters
- **Now:** 50,000 characters
- **Impact:** Can include much more document content

### 2. Retrieved Chunks: 12 → 15 (+25%)
- **Was:** Max 12 chunks after reranking
- **Now:** Max 15 chunks
- **Impact:** More comprehensive coverage

### 3. Initial Candidates: 40 → 60 (+50%)
- **Was:** Retrieve 40 candidates for reranking
- **Now:** Retrieve 60 candidates
- **Impact:** Better chance of finding all relevant content

### 4. Similarity Threshold: 0.28 → 0.20 (Lower)
- **Was:** 0.28 minimum similarity
- **Now:** 0.20 minimum similarity
- **Impact:** Catches more potentially relevant content

### 5. Chunk Size: 1024 → 1200 (+17%)
- **Was:** 1024 characters per chunk
- **Now:** 1200 characters per chunk
- **Impact:** Less fragmentation, fewer broken words

### 6. Chunk Overlap: 200 → 300 (+50%)
- **Was:** 200 characters overlap (20%)
- **Now:** 300 characters overlap (25%)
- **Impact:** Better continuity, no broken words at boundaries

### 7. Context Window Expansion: 1 → 2 chunks
- **Was:** Include 1 chunk before/after
- **Now:** Include 2 chunks before/after
- **Impact:** Much better context around key passages
- **Note:** This was accidentally removed in previous fix, now restored!

### 8. LLM Context Limit: 20K → 50K
- **Was:** 20,000 character limit
- **Now:** 50,000 character limit
- **Impact:** Can handle all the retrieved context

## Expected Improvements

✅ **No weird out-of-context words**
   - Larger overlap (300 chars) prevents word breaks
   - Context window expansion provides surrounding text

✅ **More complete information**
   - 50KB context vs 30KB (67% more)
   - 15 chunks vs 12 (25% more)
   - 60 candidates vs 40 (50% more)

✅ **Better recall**
   - Lower threshold (0.20) catches more content
   - More candidates ensures nothing important missed

✅ **Better continuity**
   - 2-chunk context windows (was 1)
   - Larger chunks (1200 vs 1024)
   - More overlap (300 vs 200)

## Resource Usage

**Increased:**
- Memory: ~40% more (larger chunks, more cache)
- CPU: ~30% more (more reranking, expansion)
- API calls: ~50% more candidates retrieved
- LLM tokens: ~67% more context sent

**Worth it for:** Maximum quality responses

## Testing

Restart application and test with queries that had:
- Out-of-context words → Should be fixed
- Missing information → Should be more complete
- Fragmented responses → Should flow better
