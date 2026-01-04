# ?? WEEK 2 IMPLEMENTATION PLAN - Testing & Performance

## ?? OVERVIEW

**Week**: 2 of 4  
**Focus**: Testing Coverage & Performance Optimization  
**Duration**: 5-7 days  
**Status**: ?? Ready to Start

---

## ? WEEK 1 RECAP (COMPLETED)

### What We Did:
1. ? Added security dependencies (JWT, Rate Limiting, CORS)
2. ? Created environment configuration system (.env)
3. ? Built security module (src/security.py)
4. ? Created comprehensive security guide

### Security Grade: C+ ? B+ (85/100)

---

## ?? WEEK 2 GOALS

### Primary Objectives:
1. **Increase test coverage**: 23% ? 60%+
2. **Test core modules**: db.py, ollama_client.py, rag.py
3. **Add integration tests**: Full pipeline testing
4. **Implement caching**: Redis for embeddings & queries
5. **Optimize database**: Connection pool, indexes
6. **Measure performance**: Before/after metrics

### Target Metrics:
- **Tests**: 217 ? 350+ (add 133 tests)
- **Coverage**: 23.14% ? 60%+
- **Response Time**: 2-5s ? <1s (with caching)
- **Throughput**: 10 req/min ? 100+ req/min

---

## ?? DETAILED IMPLEMENTATION PLAN

### Day 1-2: Database Module Tests (test_db.py)

**Target**: 40+ tests, 90%+ coverage on db.py

#### Test Categories:

**1. Initialization Tests** (8 tests)
- `test_database_init_creates_instance` ?
- `test_initialize_creates_database` ?
- `test_initialize_enables_pgvector` ?
- `test_initialize_creates_tables` ?
- `test_initialize_handles_connection_error` ?
- `test_initialize_with_existing_database` 
- `test_initialize_connection_pool_config`
- `test_initialize_sets_connected_flag`

**2. Connection Management Tests** (7 tests)
- `test_get_connection_without_pool` ?
- `test_get_connection_returns_connection` ?
- `test_get_connection_commits_on_success` ?
- `test_get_connection_rolls_back_on_error` ?
- `test_close_when_not_connected` ?
- `test_close_closes_pool` ?
- `test_connection_pool_exhaustion`

**3. Document CRUD Tests** (10 tests)
- `test_document_exists_returns_false_when_not_found` ?
- `test_document_exists_returns_true_when_found` ?
- `test_insert_document_returns_id` ?
- `test_insert_document_with_metadata` 
- `test_insert_document_duplicate_filename`
- `test_get_all_documents_returns_list` ?
- `test_get_all_documents_empty_database`
- `test_get_document_count_returns_int` ?
- `test_delete_all_documents_clears_tables` ?
- `test_delete_document_by_id`

**4. Chunk Operations Tests** (8 tests)
- `test_insert_chunks_batch_inserts_all` ?
- `test_insert_chunks_batch_empty_list`
- `test_insert_chunks_batch_large_batch`
- `test_insert_single_chunk`
- `test_get_chunk_count_returns_int` ?
- `test_get_chunks_by_document_id`
- `test_delete_chunks_by_document_id`
- `test_update_chunk_embedding`

**5. Vector Search Tests** (10 tests)
- `test_search_similar_chunks_returns_results` ?
- `test_search_similar_chunks_with_file_filter` ?
- `test_search_similar_chunks_respects_top_k` ?
- `test_search_similar_chunks_handles_empty_results` ?
- `test_search_similar_chunks_invalid_embedding_dimension`
- `test_search_similar_chunks_similarity_threshold`
- `test_search_similar_chunks_ordering`
- `test_search_similar_chunks_null_embedding`
- `test_search_similar_chunks_cosine_distance`
- `test_search_similar_chunks_performance`

**6. Error Handling Tests** (7 tests)
- `test_document_exists_handles_db_error` ?
- `test_insert_document_handles_constraint_violation` ?
- `test_search_handles_connection_lost`
- `test_operations_when_not_connected`
- `test_transaction_rollback_on_error`
- `test_concurrent_access_handling`
- `test_query_timeout_handling`

**Total**: 50+ comprehensive tests

---

### Day 3: Ollama Client Tests (test_ollama_client.py)

**Target**: 30+ tests, 90%+ coverage on ollama_client.py

#### Test Categories:

**1. Connection Tests** (5 tests)
- `test_check_connection_success`
- `test_check_connection_failure`
- `test_check_connection_timeout`
- `test_check_connection_invalid_url`
- `test_connection_retry_logic`

**2. Model Operations** (8 tests)
- `test_list_models_success`
- `test_list_models_empty`
- `test_list_models_connection_error`
- `test_get_first_available_model`
- `test_get_embedding_model`
- `test_pull_model_success`
- `test_delete_model_success`
- `test_test_model_success`

**3. Chat Generation** (6 tests)
- `test_generate_chat_response_streaming`
- `test_generate_chat_response_non_streaming`
- `test_generate_chat_response_with_history`
- `test_generate_chat_response_empty_message`
- `test_generate_chat_response_timeout`
- `test_generate_chat_response_model_not_found`

**4. Embedding Generation** (6 tests)
- `test_generate_embedding_success`
- `test_generate_embedding_failure`
- `test_generate_embedding_wrong_model`
- `test_generate_embedding_empty_text`
- `test_generate_embedding_long_text`
- `test_generate_embedding_dimensions`

**5. Error Handling** (5 tests)
- `test_http_error_handling`
- `test_json_parse_error`
- `test_network_timeout`
- `test_connection_refused`
- `test_invalid_response_format`

**Total**: 30+ tests

---

### Day 4-5: RAG Module Tests (test_rag.py)

**Target**: 35+ tests, 85%+ coverage on rag.py

#### Test Categories:

**1. Document Loading** (6 tests)
- `test_load_pdf_success`
- `test_load_txt_success`
- `test_load_docx_success`
- `test_load_md_success`
- `test_load_unsupported_format`
- `test_load_corrupted_file`

**2. Text Chunking** (10 tests)
- `test_chunk_text_basic`
- `test_chunk_text_with_overlap`
- `test_chunk_text_custom_size`
- `test_chunk_text_empty_input`
- `test_chunk_text_single_char`
- `test_chunk_text_preserves_sentences`
- `test_chunk_text_handles_unicode`
- `test_chunk_text_respects_separators`
- `test_chunk_text_large_document`
- `test_chunk_text_with_tables`

**3. Embedding Generation** (5 tests)
- `test_generate_embeddings_for_chunks`
- `test_generate_embeddings_batch`
- `test_generate_embeddings_caching`
- `test_generate_embeddings_error_recovery`
- `test_generate_embeddings_dimensions`

**4. Context Retrieval** (8 tests)
- `test_retrieve_context_success`
- `test_retrieve_context_no_results`
- `test_retrieve_context_with_filter`
- `test_retrieve_context_reranking`
- `test_retrieve_context_top_k`
- `test_retrieve_context_min_similarity`
- `test_retrieve_context_query_preprocessing`
- `test_retrieve_context_empty_database`

**5. Document Ingestion** (6 tests)
- `test_ingest_document_full_pipeline`
- `test_ingest_document_duplicate`
- `test_ingest_document_large_file`
- `test_ingest_document_with_progress`
- `test_ingest_document_cleanup_on_error`
- `test_ingest_multiple_documents`

**Total**: 35+ tests

---

### Day 6: Integration Tests

**Target**: 20+ tests, full pipeline coverage

#### Test Categories:

**1. Ingestion Pipeline** (5 tests)
```python
tests/integration/test_ingestion_pipeline.py
```
- `test_full_pdf_ingestion_workflow`
- `test_batch_document_ingestion`
- `test_ingestion_with_different_formats`
- `test_ingestion_error_recovery`
- `test_ingestion_duplicate_handling`

**2. RAG Retrieval Pipeline** (5 tests)
```python
tests/integration/test_rag_pipeline.py
```
- `test_query_to_results_pipeline`
- `test_retrieval_with_multiple_documents`
- `test_retrieval_quality_metrics`
- `test_retrieval_with_filters`
- `test_retrieval_performance`

**3. API Endpoints** (10 tests)
```python
tests/integration/test_api_endpoints.py
```
- `test_chat_endpoint_with_rag`
- `test_chat_endpoint_without_rag`
- `test_document_upload_endpoint`
- `test_document_list_endpoint`
- `test_document_clear_endpoint`
- `test_model_operations_endpoints`
- `test_status_endpoint`
- `test_authentication_flow`
- `test_rate_limiting`
- `test_error_responses`

**Total**: 20+ integration tests

---

### Day 7: Performance & Caching

#### 1. Add Redis Caching

**Create**: `src/cache.py`
```python
"""
Caching module using Redis for performance optimization.
"""
from typing import Optional, Any, List
import json
import hashlib
from redis import Redis
from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)

class CacheManager:
    def __init__(self):
        if config.REDIS_ENABLED:
            self.redis = Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                password=config.REDIS_PASSWORD,
                decode_responses=True
            )
            logger.info("Redis cache enabled")
        else:
            self.redis = None
            logger.info("Redis cache disabled")
    
    def cache_embedding(self, text: str, embedding: List[float], ttl: int = 3600):
        """Cache embedding for text."""
        if not self.redis:
            return
        
        key = f"emb:{hashlib.md5(text.encode()).hexdigest()}"
        self.redis.setex(key, ttl, json.dumps(embedding))
    
    def get_cached_embedding(self, text: str) -> Optional[List[float]]:
        """Get cached embedding for text."""
        if not self.redis:
            return None
        
        key = f"emb:{hashlib.md5(text.encode()).hexdigest()}"
        cached = self.redis.get(key)
        return json.loads(cached) if cached else None
    
    def cache_retrieval_results(self, query: str, results: List, ttl: int = 300):
        """Cache retrieval results."""
        if not self.redis:
            return
        
        key = f"ret:{hashlib.md5(query.encode()).hexdigest()}"
        self.redis.setex(key, ttl, json.dumps(results))
    
    def get_cached_retrieval(self, query: str) -> Optional[List]:
        """Get cached retrieval results."""
        if not self.redis:
            return None
        
        key = f"ret:{hashlib.md5(query.encode()).hexdigest()}"
        cached = self.redis.get(key)
        return json.loads(cached) if cached else None
    
    def invalidate_all(self):
        """Clear all cached data."""
        if self.redis:
            self.redis.flushdb()
            logger.info("Cache cleared")

# Global cache instance
cache = CacheManager()
```

#### 2. Database Performance Optimizations

**Add to config.py**:
```python
# Increase connection pool
DB_POOL_MIN_CONN = 5  # Was 2
DB_POOL_MAX_CONN = 50  # Was 10
```

**Add indexes** (in db.py initialization):
```sql
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
    ON document_chunks USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_documents_filename 
    ON documents(filename);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id 
    ON document_chunks(document_id);
```

#### 3. Performance Testing

**Create**: `tests/performance/test_benchmarks.py`
```python
import pytest
import time
from src.db import db
from src.ollama_client import ollama_client
from src.rag import doc_processor

def test_database_query_performance():
    """Test database query response time."""
    start = time.time()
    results = db.search_similar_chunks([0.5] * 768, top_k=10)
    duration = time.time() - start
    
    assert duration < 0.1, f"Query too slow: {duration}s"

def test_embedding_generation_performance():
    """Test embedding generation speed."""
    start = time.time()
    success, embedding = ollama_client.generate_embedding(
        "nomic-embed-text", 
        "test query"
    )
    duration = time.time() - start
    
    assert duration < 2.0, f"Embedding too slow: {duration}s"

def test_retrieval_pipeline_performance():
    """Test full retrieval pipeline."""
    start = time.time()
    results = doc_processor.retrieve_context("test query")
    duration = time.time() - start
    
    assert duration < 3.0, f"Retrieval too slow: {duration}s"
```

---

## ?? SUCCESS METRICS

### Testing Metrics:
```
Current:
- Tests: 217 (210 passing)
- Coverage: 23.14%
- Tested modules: 6/9

Target:
- Tests: 350+ (95%+ passing)
- Coverage: 60%+
- Tested modules: 9/9 ?
```

### Performance Metrics:
```
Current:
- Query response: 2-5 seconds
- Embedding generation: 1-3 seconds
- RAG retrieval: 3-7 seconds
- Throughput: ~10 req/min

Target:
- Query response: <0.5 seconds (with cache)
- Embedding generation: <1 second (cached)
- RAG retrieval: <1.5 seconds (optimized)
- Throughput: 100+ req/min
```

---

## ??? IMPLEMENTATION COMMANDS

### Run Tests:
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific module
pytest tests/test_db.py -v

# Run integration tests
pytest tests/integration/ -v

# Run performance tests
pytest tests/performance/ -v

# Generate coverage report
pytest --cov=src --cov-report=term-missing
```

### Check Coverage:
```bash
# View HTML coverage report
start htmlcov/index.html

# Check specific module
pytest --cov=src.db tests/test_db.py --cov-report=term
```

---

## ? COMPLETION CHECKLIST

### Testing:
- [ ] Database tests written (40+ tests)
- [ ] Ollama client tests written (30+ tests)
- [ ] RAG module tests written (35+ tests)
- [ ] Integration tests written (20+ tests)
- [ ] All tests passing (95%+)
- [ ] Coverage >= 60%

### Performance:
- [ ] Redis caching implemented
- [ ] Cache manager created
- [ ] Database optimized (indexes, pool)
- [ ] Performance benchmarks created
- [ ] Response times improved (<1s)
- [ ] Throughput increased (100+ req/min)

### Documentation:
- [ ] Testing guide created
- [ ] Performance guide created
- [ ] Week 2 report written
- [ ] Metrics documented

---

## ?? EXPECTED OUTCOMES

### After Week 2:
```
? Test coverage: 60%+
? 350+ comprehensive tests
? All core modules tested
? Integration tests complete
? Redis caching active
? Database optimized
? Response time: <1s
? Throughput: 100+ req/min
? Production-ready performance
```

### Code Quality Grade:
- **Before Week 2**: B+ (85/100)
- **After Week 2**: **A- (92/100)**

---

## ?? RESOURCES

### Testing:
- pytest documentation
- pytest-cov documentation
- unittest.mock guide
- Testing best practices

### Performance:
- Redis documentation
- PostgreSQL performance tuning
- Database indexing strategies
- Caching strategies

---

**Status**: ?? **READY TO START**  
**Duration**: 5-7 days  
**Effort**: 20-30 hours  
**Impact**: **HIGH** - Production-ready testing & performance

