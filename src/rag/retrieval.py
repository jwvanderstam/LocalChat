"""
Retrieval & Context Formatting
===============================

Handles query processing, hybrid search (semantic + BM25), re-ranking,
diversity filtering, and context formatting for LLM prompts.
"""

import re
import time
from collections import defaultdict
from typing import List, Tuple, Optional, Dict, Any, Set

from .. import config
from ..db import db
from ..ollama_client import ollama_client
from ..utils.logging_config import get_logger
from .scoring import BM25Scorer
from .cache import embedding_cache

logger = get_logger(__name__)

# Pre-built at import time — avoids recreating this dict on every query
_CONTRACTIONS: dict = {
    "what's": "what is", "what're": "what are", "where's": "where is",
    "when's": "when is", "who's": "who is", "how's": "how is",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "won't": "will not", "wouldn't": "would not", "shouldn't": "should not",
    "can't": "cannot", "couldn't": "could not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "i'm": "i am", "you're": "you are", "he's": "he is", "she's": "she is",
    "it's": "it is", "we're": "we are", "they're": "they are",
    "i've": "i have", "you've": "you have", "we've": "we have",
    "they've": "they have", "i'll": "i will", "you'll": "you will",
    "we'll": "we will", "they'll": "they will",
}
try:
    from ..monitoring import timed, counted
except ImportError:
    def timed(_metric_name):  # noqa: E306
        return lambda func: func
    def counted(_metric_name, _labels=None):  # noqa: E306
        return lambda func: func


class RetrievalMixin:
    """
    Mixin providing retrieval, re-ranking, and context formatting
    methods for DocumentProcessor.
    """
    
    def _preprocess_query(self, query: str) -> str:
        """
        Preprocess and clean query for better retrieval.
        
        Args:
            query: Raw user query
        
        Returns:
            Cleaned and normalized query string
        """
        # Remove extra whitespace
        query = ' '.join(query.split())
        
        # Convert to lowercase for processing
        query_lower = query.lower()
        
        # Expand common contractions for better matching
        for contraction, expansion in _CONTRACTIONS.items():
            query_lower = query_lower.replace(contraction, expansion)
        
        # Remove special characters but keep important punctuation
        query_lower = re.sub(r'[^\w\s\-\?\.\!\,]', ' ', query_lower)
        
        # Normalize multiple spaces
        query_lower = ' '.join(query_lower.split())
        
        logger.debug(f"Preprocessed query: '{query}' -> '{query_lower}'")
        return query_lower
    
    def _expand_query(self, query: str) -> List[str]:
        """
        Expand query with related terms for better coverage.
        
        Args:
            query: Preprocessed query
        
        Returns:
            List of query variations (original + expansions)
        """
        if not config.QUERY_EXPANSION_ENABLED:
            return [query]
        
        queries = [query]
        
        # Common domain-specific expansions
        expansions = {
            'revenue': ['income', 'earnings', 'sales'],
            'profit': ['earnings', 'net income', 'margin'],
            'cost': ['expense', 'expenditure', 'spending'],
            'customer': ['client', 'buyer', 'user'],
            'product': ['item', 'offering', 'solution'],
            'price': ['cost', 'rate', 'fee'],
            'increase': ['grow', 'rise', 'expand'],
            'decrease': ['decline', 'reduce', 'drop'],
            'total': ['sum', 'aggregate', 'combined'],
            'average': ['mean', 'typical', 'standard'],
        }
        
        query_words = query.lower().split()
        added_expansions = 0
        
        for word in query_words:
            if word in expansions and added_expansions < config.MAX_QUERY_EXPANSIONS:
                for synonym in expansions[word][:1]:  # Add first synonym only
                    expanded = query.replace(word, synonym)
                    if expanded != query and expanded not in queries:
                        queries.append(expanded)
                        added_expansions += 1
                        logger.debug(f"Expanded query with synonym: {expanded}")
        
        return queries
    
    def _apply_hybrid_scoring(
        self,
        all_results: dict,
        query_clean: str,
        use_hybrid_search: bool,
    ) -> None:
        """Apply BM25 scores and blend them with semantic scores (in-place)."""
        if not (use_hybrid_search and len(all_results) > 1):
            logger.debug("[RAG] Skipped hybrid scoring (BM25 disabled or insufficient results)")
            return
        bm25_scores = self._compute_bm25_scores(query_clean, all_results)
        semantic_weight = config.SIMILARITY_WEIGHT
        bm25_weight = config.BM25_WEIGHT + config.KEYWORD_WEIGHT
        for chunk_id, data in all_results.items():
            bm25_norm = bm25_scores.get(chunk_id, 0.0)
            data['bm25_score'] = bm25_norm
            data['combined_score'] = semantic_weight * data['semantic_score'] + bm25_weight * bm25_norm
        logger.debug("[RAG] Applied hybrid BM25 scoring")

    def _deduplicate_results(self, sorted_results: list) -> list:
        """Remove exact duplicates and adjacent chunks (within 2 positions)."""
        seen: Dict[str, set] = {}  # filename -> set of seen chunk indices
        deduped: list = []
        for r in sorted_results:
            fname, cidx = r['filename'], r['chunk_index']
            indices = seen.setdefault(fname, set())
            # O(1): intersect with a fixed-size 5-element window set
            if not (indices & {cidx - 2, cidx - 1, cidx, cidx + 1, cidx + 2}):
                indices.add(cidx)
                deduped.append(r)
        return deduped

    @timed('rag.retrieve_context')
    @counted('rag.retrieval_requests')
    def retrieve_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
        file_type_filter: Optional[str] = None,
        use_hybrid_search: bool = True,
        expand_context: bool = True
    ) -> List[Tuple[str, str, int, float, Dict[str, Any]]]:
        """
        Retrieve relevant context for a query with OPTIMIZED hybrid search.
        
        Args:
            query: User's question
            top_k: Number of chunks to retrieve (default from config)
            min_similarity: Minimum similarity threshold (0.0-1.0)
            file_type_filter: Filter by file extension (e.g., '.pdf', '.docx')
            use_hybrid_search: Enable BM25 + semantic hybrid search
            expand_context: Enable context window expansion
        
        Returns:
            List of (chunk_text, filename, chunk_index, similarity, metadata) tuples, sorted by relevance
            metadata dict contains page_number, section_title when available
        """
        start_time = time.time()
        
        top_k = top_k or config.TOP_K_RESULTS
        min_similarity = min_similarity if min_similarity is not None else config.MIN_SIMILARITY_THRESHOLD
        
        logger.info(f"[RAG] Retrieve context - query: {query[:80]}...")
        logger.debug(f"[RAG] Parameters: top_k={top_k}, min_sim={min_similarity}, hybrid={use_hybrid_search}")
        
        # Step 1: Query preprocessing
        query_clean = self._preprocess_query(query)

        # Check query cache before expensive retrieval
        _app_query_cache = None
        try:
            from flask import current_app as _cur_app
            _app_query_cache = getattr(_cur_app._get_current_object(), 'query_cache', None)
        except RuntimeError:
            pass
        if _app_query_cache is not None:
            _cached_result = _app_query_cache.get(query_clean, top_k, min_similarity, use_hybrid_search)
            if _cached_result is not None:
                logger.info("[RAG] Query cache hit")
                return _cached_result

        # Step 3: Get embedding model
        embedding_model = ollama_client.get_embedding_model()
        if not embedding_model:
            logger.error("[RAG] No embedding model available")
            return []
        
        # Step 4: Generate query embedding (with caching)
        query_embedding = self._get_cached_embedding(query_clean, embedding_model)
        if not query_embedding:
            logger.error("[RAG] Failed to generate query embedding")
            return []
        
        embedding_time = time.time()
        logger.debug(f"[RAG] Embedding generated in {embedding_time - start_time:.3f}s")
        
        # Step 5: Semantic search (primary signal)
        semantic_results = db.search_similar_chunks(
            query_embedding, 
            top_k=top_k * 2,  # Get more for re-ranking
            file_type_filter=file_type_filter
        )
        
        search_time = time.time()
        logger.debug(f"[RAG] Semantic search returned {len(semantic_results)} results in {search_time - embedding_time:.3f}s")
        
        if not semantic_results:
            logger.warning("[RAG] No semantic search results")
            return []
        
        # Step 6: Hybrid search - combine with BM25 (if enabled)
        all_results: Dict[str, Dict[str, Any]] = {}
        for chunk_text, filename, chunk_index, similarity, metadata in semantic_results:
            chunk_id = f"{filename}:{chunk_index}"
            all_results[chunk_id] = {
                'chunk_text': chunk_text, 'filename': filename,
                'chunk_index': chunk_index, 'semantic_score': similarity,
                'bm25_score': 0.0, 'combined_score': similarity,
                'metadata': metadata or {}
            }
        logger.debug(f"[RAG] Collected {len(all_results)} results for hybrid scoring")

        self._apply_hybrid_scoring(all_results, query_clean, use_hybrid_search)
        
        # Step 7: Filter by similarity threshold
        filtered_results = {
            k: v for k, v in all_results.items() 
            if v['semantic_score'] >= min_similarity
        }
        
        if not filtered_results:
            logger.warning(f"[RAG] No chunks passed similarity threshold {min_similarity}")
            if all_results:
                best = max(all_results.values(), key=lambda x: x['semantic_score'])
                logger.warning(f"[RAG] Best similarity was {best['semantic_score']:.3f}")
            return []
        
        logger.info(f"[RAG] {len(filtered_results)} chunks passed threshold (from {len(all_results)})")
        
        # Step 8: Diversity filtering
        if config.ENABLE_DIVERSITY_FILTER:
            filtered_results = self._apply_diversity_filter_dict(filtered_results)
            logger.debug(f"[RAG] After diversity filter: {len(filtered_results)} chunks")
        
        # Step 9: Multi-signal re-ranking
        if config.RERANK_RESULTS and len(filtered_results) > 1:
            filtered_results = self._rerank_with_signals(query_clean, filtered_results)
            logger.debug("[RAG] Applied multi-signal re-ranking")
        
        # Sort by combined score AND document position to maintain reading order
        sorted_results = sorted(
            filtered_results.values(),
            key=lambda x: (x['combined_score'], -(x['chunk_index'])),
            reverse=True
        )
        
        # Get results and remove exact duplicates + adjacent chunks
        final_top_k = getattr(config, 'RERANK_TOP_K', 8)
        final_results = sorted_results[:final_top_k]
        deduped_results = self._deduplicate_results(final_results)
        logger.debug(f"[RAG] Deduplicated + adjacent filter: {len(final_results)} -> {len(deduped_results)} chunks")
        
        # Sort final results by filename and chunk_index to maintain reading order
        deduped_results = sorted(deduped_results, key=lambda x: (x['filename'], x['chunk_index']))
        
        # Convert to output format with metadata
        output = [
            (r['chunk_text'], r['filename'], r['chunk_index'], r['semantic_score'], r.get('metadata', {}))
            for r in deduped_results
        ]
        
        total_time = time.time() - start_time
        logger.info(f"[RAG] Retrieved {len(output)} chunks in {total_time:.3f}s")
        
        # Populate query cache for future identical requests
        if _app_query_cache is not None and output:
            _app_query_cache.set(query_clean, top_k, min_similarity, use_hybrid_search, output)

        return output
    
    def _get_cached_embedding(self, text: str, model: str) -> Optional[List[float]]:
        """
        Get embedding with caching support.
        
        Args:
            text: Text to embed
            model: Embedding model name
        
        Returns:
            Embedding vector or None on failure
        """
        # Prefer app-level cache (tracked by admin dashboard)
        _app_emb_cache = None
        try:
            from flask import current_app as _cur_app
            _app_emb_cache = getattr(_cur_app._get_current_object(), 'embedding_cache', None)
        except RuntimeError:
            pass

        if _app_emb_cache is not None:
            cached = _app_emb_cache.get(text, model)
            if cached is not None:
                logger.debug("[RAG] Embedding cache hit")
                return cached
            success, emb = ollama_client.generate_embedding(model, text)
            if success and emb:
                _app_emb_cache.set(text, model, emb)
                return emb
            return None

        # Fallback to module-level LRU cache (no Flask context)
        cached = embedding_cache.get(text, model)
        if cached is not None:
            logger.debug("[RAG] Embedding cache hit")
            return cached
        success, emb = ollama_client.generate_embedding(model, text)
        if success and emb:
            embedding_cache.put(text, model, emb)
            return emb
        return None
    
    def _compute_simple_bm25(self, query: str, document: str) -> float:
        """
        Compute a simple normalized BM25 score for a single query-document pair.

        Args:
            query: Query text
            document: Document text to score against

        Returns:
            Normalized BM25 score in range [0, 1]
        """
        if not document or not query:
            return 0.0
        scorer = BM25Scorer()
        scorer.fit([document])
        raw_score = scorer.score(query, document, 0)
        return raw_score / (raw_score + 1.0) if raw_score > 0 else 0.0

    def _compute_bm25_scores(
        self, 
        query: str, 
        results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Compute normalized BM25 scores for result chunks.
        
        Args:
            query: Query text
            results: Dictionary of chunk_id -> result data
        
        Returns:
            Dictionary of chunk_id -> normalized BM25 score
        """
        if not results:
            return {}
        
        # Create mini-corpus from results
        corpus = [data['chunk_text'] for data in results.values()]
        chunk_ids = list(results.keys())
        
        # Fit BM25 on this corpus
        scorer = BM25Scorer()
        scorer.fit(corpus)
        
        # Score each document
        scores = {}
        for i, (chunk_id, data) in enumerate(results.items()):
            score = scorer.score(query, data['chunk_text'], i)
            scores[chunk_id] = score
        logger.debug("[BM25] Scored %d chunks", len(scores))
        
        # Normalize scores to [0, 1]
        max_score = max(scores.values()) if scores else 0.0
        min_score = min(scores.values()) if scores else 0.0
        avg_score = sum(scores.values())/len(scores) if scores else 0.0
        non_zero_count = sum(1 for s in scores.values() if s > 0)
        
        logger.debug(f"[BM25] Raw scores: min={min_score:.3f}, max={max_score:.3f}, avg={avg_score:.3f}")
        logger.debug(f"[BM25] Non-zero scores: {non_zero_count}/{len(scores)}")
        
        if scores:
            score_range = max_score - min_score
            
            if score_range > 0:
                scores = {k: (v - min_score) / score_range for k, v in scores.items()}
                logger.debug(f"[BM25] Normalized {len(scores)} scores (range was {score_range:.3f})")
            elif max_score > 0:
                scores = {k: 0.5 for k in scores}
                logger.debug(f"[BM25] All scores equal ({max_score:.3f}), using 0.5 for all")
            else:
                scores = {k: 0.0 for k in scores}
                logger.info("[BM25] No keyword matches found (query terms not in documents)")
                logger.info("[BM25] Falling back to semantic similarity only - this is expected for abstract/conceptual queries")
        
        return scores
    
    def _apply_diversity_filter_dict(
        self, 
        results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Remove near-duplicate chunks to increase diversity.
        
        Args:
            results: Dictionary of chunk_id -> result data
        
        Returns:
            Filtered dictionary with duplicates removed
        """
        if len(results) <= 1:
            return results
        
        # Sort by combined score
        sorted_items = sorted(
            results.items(),
            key=lambda x: x[1]['combined_score'],
            reverse=True
        )
        
        diverse_results: Dict[str, Dict[str, Any]] = {}
        selected_words: List[Set[str]] = []
        
        for chunk_id, data in sorted_items:
            chunk_words = set(data['chunk_text'].lower().split())
            
            # Check similarity with already selected chunks
            is_diverse = True
            for selected in selected_words:
                if len(chunk_words) > 0 and len(selected) > 0:
                    jaccard = len(chunk_words & selected) / len(chunk_words | selected)
                    if jaccard > config.DIVERSITY_THRESHOLD:
                        is_diverse = False
                        break
            
            if is_diverse:
                diverse_results[chunk_id] = data
                selected_words.append(chunk_words)
        
        return diverse_results
    
    def _rerank_with_signals(
        self, 
        query: str, 
        results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Re-rank results using multiple relevance signals.
        
        Args:
            query: Query text
            results: Dictionary of chunk_id -> result data
        
        Returns:
            Re-ranked results dictionary
        """
        if not results:
            return results
        
        query_terms = set(query.lower().split())
        
        for chunk_id, data in results.items():
            chunk_text = data['chunk_text']
            chunk_words = set(chunk_text.lower().split())
            
            # Signal 1: Base combined score (already calculated)
            score = data['combined_score']
            
            # Signal 2: Query term coverage bonus
            if query_terms:
                term_coverage = len(query_terms & chunk_words) / len(query_terms)
                score += term_coverage * 0.05  # Up to 5% bonus
            
            # Signal 3: Position bonus (early chunks often have key info)
            chunk_index = data['chunk_index']
            position_bonus = max(0, 0.03 - (chunk_index * 0.002))  # Decay
            score += position_bonus
            
            # Signal 4: Length preference (prefer 200-800 chars)
            chunk_len = len(chunk_text)
            if 200 <= chunk_len <= 800:
                score += 0.02  # Ideal length bonus
            elif chunk_len < 100:
                score -= 0.02  # Too short penalty
            
            data['combined_score'] = score
        
        return results
    
    def _expand_context_windows(
        self,
        results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Expand context by including adjacent chunks.

        NOTE: Not yet implemented — returns results unchanged.
        Intended future behaviour: fetch window_size chunks before/after
        each result using db.get_adjacent_chunks() and merge the text.

        Args:
            results: Dictionary of chunk_id -> result data

        Returns:
            Results unchanged (pending implementation)
        """
        return results
    
    def test_retrieval(self, query: str, top_k: Optional[int] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Test RAG retrieval system with a query.
        
        Args:
            query: Test query string
            top_k: Number of results to retrieve (default from config)
        
        Returns:
            Tuple of (success: bool, results: List[Dict])
        """
        try:
            logger.info(f"Testing retrieval with query: {query[:100]}...")
            
            results = self.retrieve_context(query, top_k=top_k)
            
            if not results:
                logger.warning("No results retrieved")
                return True, []
            
            formatted_results = []
            for chunk_text, filename, chunk_index, similarity, metadata in results:
                result_dict = {
                    'filename': filename,
                    'chunk_index': chunk_index,
                    'similarity': round(similarity, 4),
                    'preview': chunk_text[:200] + '...' if len(chunk_text) > 200 else chunk_text,
                    'length': len(chunk_text)
                }
                
                if metadata.get('page_number'):
                    result_dict['page_number'] = metadata['page_number']
                if metadata.get('section_title'):
                    result_dict['section_title'] = metadata['section_title']
                
                formatted_results.append(result_dict)
            
            logger.info(f"Retrieved {len(formatted_results)} results")
            return True, formatted_results
            
        except Exception as e:
            error_msg = f"Error testing retrieval: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, []
    
    def format_context_for_llm(
        self,
        results: List[Tuple[str, str, int, float, Dict[str, Any]]],
        max_length: int = 30000
    ) -> str:
        """
        Format retrieved context with rich presentation for LLM prompts.
        
        Args:
            results: List of (chunk_text, filename, chunk_index, similarity, metadata) tuples
            max_length: Maximum context length in characters (default: 30000)
        
        Returns:
            Formatted context string ready for LLM prompt
        """
        if not results:
            return ""
        
        logger.debug(f"Formatting {len(results)} chunks for LLM (max length: {max_length})")

        doc_chunks = defaultdict(list)
        for chunk_text, filename, chunk_index, similarity, metadata in results:
            doc_chunks[filename].append((chunk_text, chunk_index, similarity, metadata))

        formatted_parts = []
        current_length = 0
        chunks_included = 0

        for doc_num, (filename, chunks) in enumerate(doc_chunks.items(), 1):
            doc_header = f"\n[Source: {filename}]\n\n"
            if current_length + len(doc_header) > max_length:
                break
            formatted_parts.append(doc_header)
            current_length += len(doc_header)

            for chunk_text, chunk_index, similarity, metadata in chunks:
                formatted_chunk = self._format_single_chunk(chunk_text, metadata)
                if current_length + len(formatted_chunk) > max_length:
                    logger.info(f"Context size limit reached: {chunks_included} chunks from {doc_num} docs")
                    break
                formatted_parts.append(formatted_chunk)
                current_length += len(formatted_chunk)
                chunks_included += 1

        final_context = "".join(formatted_parts)
        logger.info(f"Formatted context: {len(final_context):,} chars from {chunks_included} chunks across {len(doc_chunks)} documents")
        return final_context

    def _format_single_chunk(self, chunk_text: str, metadata: dict) -> str:
        """Build a formatted passage block with citation header."""
        citation_parts = []
        if metadata.get('page_number'):
            citation_parts.append(f"p. {metadata['page_number']}")
        if metadata.get('section_title'):
            section = metadata['section_title']
            citation_parts.append(section[:47] + "..." if len(section) > 50 else section)
        citation = f" ({', '.join(citation_parts)})" if citation_parts else ""
        return f"[Passage{citation}]\n" + self._format_chunk_text_rich(chunk_text) + "\n\n"
    
    def _format_chunk_text_rich(self, chunk_text: str) -> str:
        """
        Clean and format chunk text for rich professional presentation.
        
        Args:
            chunk_text: Raw text chunk
        
        Returns:
            Richly formatted text chunk
        """
        text = chunk_text.strip()
        
        # Check if this is a table (has | separators and multiple lines)
        if '|' in text and text.count('\n') > 1:
            return self._format_table_markdown_clean(text)
        
        # For regular text, enhance formatting for readability
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n\n+', '\n\n', text)
        
        # Add some structure: detect lists and enhance
        lines = text.split('\n')
        formatted_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(('- ', '* ', '\u2022 ', '1.', '2.', '3.', '4.', '5.')):
                formatted_lines.append(f"  {stripped}")
            elif len(stripped) < 50 and stripped.endswith(':'):
                formatted_lines.append(f"\n**{stripped}**")
            else:
                formatted_lines.append(line)
        
        text = '\n'.join(formatted_lines)
        
        return text
    
    def _format_table_markdown_clean(self, table_text: str) -> str:
        """
        Format table text as clean markdown.
        
        Args:
            table_text: Text containing table with pipe separators
        
        Returns:
            Clean markdown formatted table
        """
        lines = table_text.strip().split('\n')
        if not lines:
            return table_text
        
        formatted_lines = []
        for line in lines:
            line = line.strip()
            if line:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
