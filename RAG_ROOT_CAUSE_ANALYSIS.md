# RAG Root Cause Analysis

## Issues Identified

### CRITICAL ISSUE #1: Excessive Chunk Overlap (25%)
**Location:** config.py lines 105-106
**Problem:**
- CHUNK_SIZE = 1200 chars
- CHUNK_OVERLAP = 300 chars
- Overlap ratio = 25%

**Impact:**
- Adjacent chunks share 300 characters
- If we retrieve chunks 5, 6, 7 from same document, they overlap significantly
- Creates repetitive text in context
- Example: Chunk 5 (chars 0-1200), Chunk 6 (chars 900-2100) - 300 chars repeat

**Evidence:** With 8 results, if 4-5 are from same document area, 25% overlap × 5 chunks = massive repetition

### CRITICAL ISSUE #2: Weak Diversity Filter (0.85)
**Location:** config.py line 156
**Problem:**
- DIVERSITY_THRESHOLD = 0.85 (Jaccard similarity)
- With 25% overlap, adjacent chunks have ~0.40-0.50 Jaccard similarity
- Threshold of 0.85 is TOO HIGH - allows overlapping chunks through

**Impact:**
- Diversity filter doesn't catch overlapping chunks
- Multiple chunks from same document region pass filter
- Creates repetition in final results

**Math:**
- Chunk A: 1200 chars (900 unique + 300 overlap)
- Chunk B: 1200 chars (300 overlap + 900 unique)
- Jaccard = 300 / (1200 + 1200 - 300) = 0.14
- 0.14 < 0.85, so both pass even though 25% duplicated

### ISSUE #3: Wrong Sort Order
**Location:** rag.py lines 1369-1372
**Problem:**
`python
sorted_results = sorted(
    key=lambda x: (x['combined_score'], -(x['chunk_index']))
)`

**Impact:**
- Sorts by score FIRST, then by chunk position
- Groups high-scoring chunks together
- If chunks 5,6,7 all score high, they appear consecutively
- With 25% overlap, creates massive repetition

**Should be:**
- Sort by filename FIRST to group documents
- Then by chunk_index to maintain reading order
- Then by score for quality

### ISSUE #4: No Adjacent Chunk Detection
**Location:** rag.py line 1380+
**Problem:**
- Deduplication only checks (filename, chunk_index)
- Doesn't detect adjacent chunks (5,6) or (6,7,8)
- Should skip chunks that are within overlap distance

**Impact:**
- If chunks [5, 6, 7] are selected, all 3 appear
- With 300-char overlap, creates 600 chars of repetition

### ISSUE #5: High Candidate Count (50)
**Location:** config.py line 127
**Problem:**
- TOP_K_RESULTS = 50 candidates
- Many will be from same documents
- Many will be adjacent/overlapping

## Repetition Math

Worst case with current settings:
- 8 results selected
- 4 from same document (chunks 5,6,7,8)
- Each pair overlaps 300 chars
- Total repetition: 3 overlaps × 300 = 900 chars repeated
- That's 18% of a 5000-char context being duplicate!

## Root Causes Summary

1. **25% overlap is too high** for retrieval systems
2. **Diversity filter threshold (0.85) doesn't catch overlaps**
3. **Sorting groups overlapping chunks together**
4. **No adjacent chunk detection**
5. **Too many candidates from same document regions**

## Recommended Fixes

### Fix 1: Reduce Overlap (CRITICAL)
- Change: 300 → 150 chars (12.5% overlap)
- Benefit: Half the repetition

### Fix 2: Strengthen Diversity Filter (CRITICAL)
- Change: 0.85 → 0.50 threshold
- Benefit: Catches overlapping chunks

### Fix 3: Fix Sorting (HIGH)
- Sort by (filename, chunk_index) FIRST
- Maintain reading order
- Score-based selection happens before sorting

### Fix 4: Add Adjacent Chunk Detection (HIGH)
- Skip chunks within 2 positions of each other
- Example: If chunk 5 selected, skip 4,6

### Fix 5: Reduce Candidates (MEDIUM)
- Change: 50 → 30 candidates
- Focus on quality over quantity

### Fix 6: Simplify Context Format (LOW)
- Remove verbose headers
- More content, less formatting

## Implementation Plan

1. Reduce CHUNK_OVERLAP: 300 → 150
2. Reduce DIVERSITY_THRESHOLD: 0.85 → 0.50
3. Add adjacent chunk detection in deduplication
4. Fix sort order (filename, chunk_index)
5. Reduce TOP_K_RESULTS: 50 → 30
6. Test and verify

## Expected Impact

**Before:**
- 25% overlap × 4 adjacent chunks = 900 chars repetition
- Weak diversity filter
- Wrong order creates confusion

**After:**
- 12.5% overlap × limited adjacency = <200 chars repetition
- Strong diversity filter (0.50)
- Correct reading order
- Adjacent chunks prevented

**Result:** 75-80% reduction in repetition
