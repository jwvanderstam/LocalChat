# -*- coding: utf-8 -*-

"""
Performance Batch Processor
===========================

Optimized batch processing for embedding generation with parallel execution.

Author: LocalChat Team
Created: January 2025
"""

from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class BatchEmbeddingProcessor:
    """
    Optimized batch processor for generating embeddings in parallel.
    
    Features:
    - Parallel embedding generation
    - Configurable batch size (default: 64)
    - Progress tracking
    - Error handling with partial success
    """
    
    def __init__(
        self,
        ollama_client,
        batch_size: int = 64,
        max_workers: int = 8
    ):
        """
        Initialize batch processor.
        
        Args:
            ollama_client: Ollama client instance
            batch_size: Number of texts per batch
            max_workers: Number of parallel workers
        """
        self.ollama_client = ollama_client
        self.batch_size = batch_size
        self.max_workers = max_workers
        
        logger.info(f"BatchEmbeddingProcessor initialized (batch_size={batch_size}, workers={max_workers})")
    
    def process_batch(
        self,
        texts: List[str],
        model: str
    ) -> List[Optional[List[float]]]:
        """
        Process a batch of texts to generate embeddings in parallel.
        
        Args:
            texts: List of text strings
            model: Embedding model name
        
        Returns:
            List of embeddings (None for failed items)
        """
        start_time = time.time()
        total = len(texts)
        
        logger.info(f"Processing {total} embeddings in batches of {self.batch_size}")
        
        results: List[Optional[List[float]]] = [None] * total
        processed = 0
        failed = 0
        
        # Process in batches
        for batch_start in range(0, total, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total)
            batch_texts = texts[batch_start:batch_end]
            
            logger.debug(f"Batch {batch_start//self.batch_size + 1}: Processing texts {batch_start+1}-{batch_end}")
            
            # Process batch in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._generate_single,
                        text,
                        model
                    ): idx for idx, text in enumerate(batch_texts, start=batch_start)
                }
                
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        embedding = future.result()
                        if embedding is not None:
                            results[idx] = embedding
                            processed += 1
                        else:
                            failed += 1
                    except Exception as e:
                        logger.error(f"Error processing text {idx}: {e}")
                        failed += 1
            
            # Progress update
            progress = (batch_end / total) * 100
            logger.info(f"Progress: {progress:.1f}% ({batch_end}/{total})")
        
        elapsed = time.time() - start_time
        rate = total / elapsed if elapsed > 0 else 0
        
        logger.info(f"Completed: {processed} successful, {failed} failed in {elapsed:.2f}s ({rate:.1f} emb/s)")
        
        return results
    
    def _generate_single(
        self,
        text: str,
        model: str
    ) -> Optional[List[float]]:
        """Generate embedding for single text."""
        try:
            success, embedding = self.ollama_client.generate_embedding(model, text)
            return embedding if success else None
        except Exception as e:
            logger.debug(f"Embedding generation failed: {e}")
            return None
