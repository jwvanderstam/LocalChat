# Phase 1.2 Implementation: Query Rewriting

## Overview

**Priority:** High  
**Effort:** 1-2 days  
**Impact:** High  
**Dependencies:** None (can run parallel with 1.1)

## Goal

Improve retrieval recall by generating alternative query phrasings.

**Current Limitation:**
- Single query formulation
- Misses results due to vocabulary mismatch
- Sensitive to phrasing

**After Implementation:**
- 3-5 query variants per user query
- Better recall (finds more relevant documents)
- Handles synonyms and terminology variations
- 15-25% improvement in retrieval coverage

---

## Architecture

### Query Expansion Flow

```
User Query
    ?
Query Analyzer (detect intent)
    ?
Query Expander (generate variants)
    ?
    ??? Original Query
    ??? Variant 1 (synonym replacement)
    ??? Variant 2 (paraphrase)
    ??? Variant 3 (keyword extraction)
    ??? Variant 4 (domain-specific)
    ?
Parallel Retrieval (all variants)
    ?
Result Merging (deduplicate + rerank)
    ?
Top K Results
```

---

## Implementation Details

### 1. Query Expander Class

**File:** `src/query_expansion.py` (new file)

```python
"""
Query Expansion Module
======================

Generates alternative query formulations for improved retrieval.
"""

from typing import List, Dict, Optional
import re
from dataclasses import dataclass
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ExpandedQuery:
    """Container for expanded query variants."""
    original: str
    variants: List[str]
    method: str  # 'synonym', 'paraphrase', 'keyword', 'domain'


class QueryExpander:
    """
    Expands queries into multiple variants for better retrieval.
    
    Methods:
    - Synonym replacement
    - Paraphrasing
    - Keyword extraction
    - Domain-specific expansion
    """
    
    def __init__(self, use_llm: bool = True):
        """
        Initialize query expander.
        
        Args:
            use_llm: Whether to use LLM for paraphrasing (slower but better)
        """
        self.use_llm = use_llm
        self._init_synonyms()
    
    def _init_synonyms(self):
        """Initialize domain-specific synonym dictionary."""
        self.synonyms = {
            # Technical terms
            'backup': ['copy', 'archive', 'snapshot', 'restore point'],
            'storage': ['disk', 'volume', 'data store', 'repository'],
            'server': ['host', 'machine', 'node', 'instance'],
            'cloud': ['hosted', 'remote', 'virtualized'],
            'security': ['protection', 'access control', 'authentication'],
            
            # Action verbs
            'create': ['make', 'generate', 'establish', 'set up'],
            'delete': ['remove', 'destroy', 'clear', 'erase'],
            'modify': ['change', 'update', 'edit', 'adjust'],
            'retrieve': ['get', 'fetch', 'obtain', 'access'],
            
            # Process terms
            'procedure': ['process', 'workflow', 'method', 'steps'],
            'configuration': ['setup', 'settings', 'parameters', 'options'],
            'migration': ['transfer', 'move', 'transition', 'conversion'],
            
            # Add more based on your domain...
        }
    
    def expand(
        self, 
        query: str, 
        max_variants: int = 5,
        methods: Optional[List[str]] = None
    ) -> ExpandedQuery:
        """
        Expand query into multiple variants.
        
        Args:
            query: Original query
            max_variants: Maximum variants to generate
            methods: List of methods to use (None = all)
        
        Returns:
            ExpandedQuery object with variants
        """
        logger.debug(f"Expanding query: {query}")
        
        variants = set()
        variants.add(query)  # Always include original
        
        # Apply expansion methods
        if methods is None or 'synonym' in methods:
            variants.update(self._synonym_expansion(query))
        
        if methods is None or 'keyword' in methods:
            variants.update(self._keyword_extraction(query))
        
        if methods is None or 'paraphrase' in methods:
            if self.use_llm:
                variants.update(self._llm_paraphrase(query))
            else:
                variants.update(self._rule_based_paraphrase(query))
        
        if methods is None or 'domain' in methods:
            variants.update(self._domain_expansion(query))
        
        # Convert to list and limit
        variant_list = list(variants)[:max_variants]
        
        logger.info(f"Generated {len(variant_list)} query variants")
        return ExpandedQuery(
            original=query,
            variants=variant_list,
            method='combined'
        )
    
    def _synonym_expansion(self, query: str) -> List[str]:
        """
        Replace words with synonyms.
        
        Example:
            "How to create backups?" 
            ? "How to make copies?"
            ? "How to generate archives?"
        """
        variants = []
        query_lower = query.lower()
        
        for word, synonyms in self.synonyms.items():
            if word in query_lower:
                for synonym in synonyms[:2]:  # Limit to 2 synonyms per word
                    variant = re.sub(
                        r'\b' + word + r'\b',
                        synonym,
                        query_lower,
                        flags=re.IGNORECASE
                    )
                    if variant != query_lower:
                        variants.append(variant)
        
        return variants[:3]  # Limit total variants
    
    def _keyword_extraction(self, query: str) -> List[str]:
        """
        Extract key terms and create focused query.
        
        Example:
            "What is the procedure for creating backups?"
            ? "backup creation procedure"
            ? "create backup"
        """
        # Remove question words
        query_clean = re.sub(
            r'\b(what|how|when|where|who|why|which|is|are|the|a|an)\b',
            '',
            query.lower(),
            flags=re.IGNORECASE
        ).strip()
        
        # Remove extra spaces
        query_clean = re.sub(r'\s+', ' ', query_clean)
        
        # Extract noun phrases (simple approach)
        words = query_clean.split()
        if len(words) <= 3:
            return [query_clean]
        
        # Create shorter variant
        keywords = ' '.join(words[:3])  # First 3 words
        
        return [query_clean, keywords] if keywords != query_clean else [query_clean]
    
    def _rule_based_paraphrase(self, query: str) -> List[str]:
        """
        Simple rule-based paraphrasing.
        
        Example:
            "How do I create a backup?"
            ? "backup creation method"
            ? "creating backups"
        """
        variants = []
        
        # Question ? Statement
        if query.lower().startswith(('how do i', 'how to', 'how can i')):
            # "How do I create backups?" ? "creating backups"
            action = re.sub(
                r'^how (do i|to|can i) ',
                '',
                query.lower(),
                flags=re.IGNORECASE
            )
            action = action.rstrip('?').strip()
            variants.append(action)
        
        # "What is X?" ? "X"
        if query.lower().startswith('what is'):
            concept = re.sub(r'^what is (the |a |an )?', '', query.lower())
            concept = concept.rstrip('?').strip()
            variants.append(concept)
        
        return variants
    
    def _domain_expansion(self, query: str) -> List[str]:
        """
        Add domain-specific context.
        
        Example:
            "backup procedure" 
            ? "data backup and recovery procedure"
        """
        variants = []
        query_lower = query.lower()
        
        # Domain patterns
        patterns = {
            'backup': 'data backup and recovery',
            'storage': 'data storage management',
            'server': 'server infrastructure',
            'cloud': 'cloud hosting services',
            'security': 'security and access control'
        }
        
        for keyword, expansion in patterns.items():
            if keyword in query_lower and expansion not in query_lower:
                # Prepend domain context
                variant = f"{expansion} {query_lower}"
                variants.append(variant)
        
        return variants[:2]
    
    def _llm_paraphrase(self, query: str) -> List[str]:
        """
        Use LLM to generate paraphrases.
        
        Note: Requires ollama_client integration
        """
        try:
            from src.ollama_client import ollama_client
            from src import config
            
            model = config.app_state.get_active_model()
            if not model:
                logger.warning("No active model for LLM paraphrasing")
                return []
            
            prompt = f"""Generate 2 alternative phrasings for this query.
Keep the same meaning but use different words.
Only output the alternatives, one per line.

Query: {query}

Alternatives:"""
            
            # Generate paraphrases
            response = ollama_client.generate_text(model, prompt, max_tokens=100)
            
            # Parse lines
            variants = [
                line.strip() 
                for line in response.split('\n')
                if line.strip() and line.strip() != query
            ]
            
            return variants[:2]
            
        except Exception as e:
            logger.warning(f"LLM paraphrasing failed: {e}")
            return []


# Global instance
query_expander = QueryExpander(use_llm=True)
```

---

### 2. Result Merging

**File:** `src/query_expansion.py` (continued)

```python
class ResultMerger:
    """Merge and deduplicate results from multiple query variants."""
    
    def merge_results(
        self,
        results_by_variant: Dict[str, List[Dict]],
        top_k: int = 10
    ) -> List[Dict]:
        """
        Merge results from multiple query variants.
        
        Strategy:
        1. Collect all unique results (by chunk_id)
        2. Aggregate scores (max, avg, or weighted)
        3. Rerank by aggregated score
        4. Return top_k
        
        Args:
            results_by_variant: Dict mapping variant ? results
            top_k: Number of final results
        
        Returns:
            Merged and reranked results
        """
        # Aggregate by chunk_id
        chunk_scores = {}  # chunk_id ? {scores, data}
        
        for variant, results in results_by_variant.items():
            for result in results:
                chunk_id = (result['filename'], result['chunk_index'])
                
                if chunk_id not in chunk_scores:
                    chunk_scores[chunk_id] = {
                        'data': result,
                        'scores': [],
                        'variant_count': 0
                    }
                
                chunk_scores[chunk_id]['scores'].append(result['similarity'])
                chunk_scores[chunk_id]['variant_count'] += 1
        
        # Compute aggregated scores
        merged_results = []
        for chunk_id, info in chunk_scores.items():
            # Use max score + bonus for multiple variants
            max_score = max(info['scores'])
            variant_bonus = 0.05 * info['variant_count']  # Small boost
            final_score = min(1.0, max_score + variant_bonus)
            
            result = info['data'].copy()
            result['similarity'] = final_score
            result['variant_count'] = info['variant_count']
            merged_results.append(result)
        
        # Sort by final score
        merged_results.sort(key=lambda x: x['similarity'], reverse=True)
        
        logger.info(
            f"Merged {len(chunk_scores)} unique chunks from "
            f"{len(results_by_variant)} variants"
        )
        
        return merged_results[:top_k]


# Global instance
result_merger = ResultMerger()
```

---

### 3. Integration with RAG

**File:** `src/rag.py`

**Add method to DocumentProcessor:**

```python
def retrieve_context_with_expansion(
    self,
    query: str,
    use_hybrid_search: bool = True,
    expand_query: bool = True,
    max_variants: int = 5
) -> List[Tuple[str, str, int, float]]:
    """
    Retrieve context with optional query expansion.
    
    Args:
        query: User query
        use_hybrid_search: Use hybrid search
        expand_query: Whether to expand query
        max_variants: Max query variants
    
    Returns:
        List of (chunk_text, filename, chunk_index, similarity) tuples
    """
    from src.query_expansion import query_expander, result_merger
    
    if not expand_query:
        # Use standard retrieval
        return self.retrieve_context(query, use_hybrid_search)
    
    logger.info(f"Retrieving with query expansion: {query}")
    
    # Generate query variants
    expanded = query_expander.expand(query, max_variants=max_variants)
    logger.info(f"Generated {len(expanded.variants)} variants")
    
    # Retrieve for each variant
    results_by_variant = {}
    for variant in expanded.variants:
        logger.debug(f"Retrieving for variant: {variant}")
        results = self._retrieve_raw(variant, use_hybrid_search)
        results_by_variant[variant] = results
    
    # Merge results
    merged = result_merger.merge_results(
        results_by_variant,
        top_k=config.RERANK_TOP_K
    )
    
    # Convert to tuple format
    output = [
        (r['chunk_text'], r['filename'], r['chunk_index'], r['similarity'])
        for r in merged
    ]
    
    logger.info(f"Query expansion returned {len(output)} merged results")
    return output
```

---

### 4. Configuration

**File:** `src/config.py`

**Add settings:**

```python
# Query Expansion Settings
ENABLE_QUERY_EXPANSION: bool = True      # Enable/disable feature
MAX_QUERY_VARIANTS: int = 5              # Max variants per query
USE_LLM_PARAPHRASE: bool = True          # Use LLM for paraphrasing
QUERY_EXPANSION_METHODS: List[str] = [   # Methods to use
    'synonym', 'keyword', 'paraphrase', 'domain'
]
```

---

### 5. API Integration

**File:** `src/app.py`

**Update chat endpoint:**

```python
# In api_chat function, modify RAG retrieval:

if use_rag:
    logger.debug("[RAG] Retrieving context from documents...")
    try:
        # Use query expansion if enabled
        expand_query = config.ENABLE_QUERY_EXPANSION
        
        results = doc_processor.retrieve_context_with_expansion(
            message,
            use_hybrid_search=True,
            expand_query=expand_query,
            max_variants=config.MAX_QUERY_VARIANTS
        )
        
        logger.info(
            f"[RAG] Retrieved {len(results)} chunks "
            f"(expansion: {expand_query})"
        )
        # ... rest of code
```

---

## Implementation Steps

### Day 1: Core Expansion Logic (4-5 hours)

**Morning:**
1. Create `src/query_expansion.py`
2. Implement QueryExpander class
3. Add synonym dictionary
4. Implement expansion methods

**Afternoon:**
5. Implement ResultMerger class
6. Test expansion with sample queries
7. Measure variant quality

**Testing:**
```python
from src.query_expansion import query_expander

# Test expansion
query = "How do I create backups?"
expanded = query_expander.expand(query)

print(f"Original: {expanded.original}")
for variant in expanded.variants:
    print(f"  Variant: {variant}")

# Expected output:
# Original: How do I create backups?
#   Variant: How do I create backups?
#   Variant: How do I make copies?
#   Variant: creating backups
#   Variant: backup creation method
#   Variant: data backup and recovery create backups
```

---

### Day 2: Integration & Testing (3-4 hours)

**Morning:**
1. Add configuration settings
2. Integrate with RAG pipeline
3. Update API endpoint

**Afternoon:**
4. End-to-end testing
5. Measure recall improvement
6. Document feature

**Testing:**
```python
# Test full flow
doc_processor.retrieve_context_with_expansion(
    "backup procedure",
    expand_query=True
)

# Compare with standard retrieval
standard = doc_processor.retrieve_context("backup procedure")
expanded = doc_processor.retrieve_context_with_expansion("backup procedure")

print(f"Standard: {len(standard)} results")
print(f"Expanded: {len(expanded)} results")
# Should see 15-25% more results with expansion
```

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_query_expansion.py`

```python
import pytest
from src.query_expansion import query_expander, result_merger


def test_synonym_expansion():
    """Test synonym replacement."""
    query = "create backup"
    expanded = query_expander.expand(query, methods=['synonym'])
    
    # Should have synonyms for 'create' and 'backup'
    assert len(expanded.variants) > 1
    assert any('copy' in v.lower() for v in expanded.variants)


def test_keyword_extraction():
    """Test keyword extraction."""
    query = "What is the procedure for creating backups?"
    expanded = query_expander.expand(query, methods=['keyword'])
    
    # Should have shorter keyword version
    assert any(len(v) < len(query) for v in expanded.variants)


def test_result_merging():
    """Test result merging."""
    results = {
        'variant1': [
            {'filename': 'doc1', 'chunk_index': 1, 'similarity': 0.9},
            {'filename': 'doc2', 'chunk_index': 1, 'similarity': 0.8}
        ],
        'variant2': [
            {'filename': 'doc1', 'chunk_index': 1, 'similarity': 0.85},  # Duplicate
            {'filename': 'doc3', 'chunk_index': 1, 'similarity': 0.75}
        ]
    }
    
    merged = result_merger.merge_results(results, top_k=10)
    
    # Should deduplicate doc1
    assert len(merged) == 3
    # doc1 should have highest score (appeared in both)
    assert merged[0]['filename'] == 'doc1'
```

---

### Integration Tests

```python
def test_expansion_retrieval():
    """Test end-to-end with expansion."""
    # Upload test document
    doc_id = doc_processor.ingest_document("test.pdf")
    
    # Retrieve with expansion
    results = doc_processor.retrieve_context_with_expansion(
        "backup",
        expand_query=True
    )
    
    # Should find results
    assert len(results) > 0


def test_expansion_vs_standard():
    """Compare expansion vs standard retrieval."""
    query = "server configuration"
    
    standard = doc_processor.retrieve_context(query)
    expanded = doc_processor.retrieve_context_with_expansion(query)
    
    # Expansion should find same or more
    assert len(expanded) >= len(standard)
```

---

## Success Metrics

### Quantitative
- [ ] **Recall:** +15-25% more relevant results found
- [ ] **Latency:** <300ms additional overhead
- [ ] **Variant quality:** 80%+ variants are meaningful
- [ ] **Deduplication:** 95%+ accuracy

### Qualitative
- [ ] Handles vocabulary mismatches
- [ ] Works for technical vs colloquial terms
- [ ] Improves coverage without noise
- [ ] User satisfaction improved

---

## Performance Optimization

### Caching Expansions

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def expand_cached(query: str, max_variants: int) -> ExpandedQuery:
    """Cache query expansions."""
    return query_expander.expand(query, max_variants)
```

### Parallel Retrieval

```python
from concurrent.futures import ThreadPoolExecutor

def retrieve_parallel(variants):
    """Retrieve variants in parallel."""
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(retrieve_one, v): v 
            for v in variants
        }
        results = {}
        for future in futures:
            variant = futures[future]
            results[variant] = future.result()
        return results
```

---

## Rollback Plan

```python
# Disable in config
ENABLE_QUERY_EXPANSION = False

# Or revert code
git checkout main src/query_expansion.py src/rag.py src/app.py
```

---

## Next Steps

After Phase 1.2 completion:
1. ? Measure improvement metrics
2. ? Tune synonym dictionary for your domain
3. ? **Start Phase 1.3:** Conversation Memory

---

**Status:** Ready to implement  
**Estimated Time:** 1-2 days (7-9 hours)  
**Risk:** Low (additive feature, easy to disable)  
**Dependencies:** None

---

*Implementation Guide Version: 1.0*  
*See: RAG_ROADMAP_2025.md for context*
