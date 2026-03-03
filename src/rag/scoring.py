"""
BM25 Scoring for Hybrid Search
===============================

Implements BM25 algorithm for keyword-based retrieval,
used in combination with semantic search for hybrid retrieval.
"""

import re
import math
from collections import Counter
from typing import List, Dict

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class BM25Scorer:
    """
    BM25 scoring for keyword-based retrieval.
    
    Implements the BM25 algorithm for traditional information retrieval,
    used in combination with semantic search for hybrid retrieval.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """
        Initialize BM25 scorer.
        
        Args:
            k1: Term frequency saturation parameter (default: 1.5)
            b: Length normalization parameter (default: 0.75)
        """
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_freqs: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_len: List[int] = []
        self._initialized = False
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization - lowercase and split on non-alphanumeric."""
        return re.findall(r'\w+', text.lower())
    
    def fit(self, corpus: List[str]) -> None:
        """
        Fit BM25 on a corpus of documents.
        
        Args:
            corpus: List of document texts
        """
        self.corpus_size = len(corpus)
        if self.corpus_size == 0:
            return
        
        nd: Dict[str, int] = {}  # word -> number of documents containing word
        
        for document in corpus:
            tokens = self._tokenize(document)
            self.doc_len.append(len(tokens))
            
            # Count unique words in document
            unique_tokens = set(tokens)
            for token in unique_tokens:
                nd[token] = nd.get(token, 0) + 1
        
        self.avgdl = sum(self.doc_len) / self.corpus_size
        self.doc_freqs = nd
        
        # Calculate IDF
        for word, freq in nd.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)
        
        self._initialized = True
        logger.debug(f"BM25 fitted on {self.corpus_size} documents, {len(self.idf)} unique terms")
    
    def score(self, query: str, document: str, doc_idx: int = 0) -> float:
        """
        Calculate BM25 score for a query-document pair.
        
        Args:
            query: Query text
            document: Document text
            doc_idx: Document index (for length normalization)
        
        Returns:
            BM25 score (higher is more relevant)
        """
        if not self._initialized:
            return 0.0
        
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(document)
        doc_len = len(doc_tokens)
        
        if doc_len == 0:
            return 0.0
        
        # Term frequency in document
        tf = Counter(doc_tokens)
        
        score = 0.0
        for token in query_tokens:
            if token not in self.idf:
                continue
            
            freq = tf.get(token, 0)
            idf = self.idf[token]
            
            # BM25 formula
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score += idf * (numerator / denominator)
        
        return score
