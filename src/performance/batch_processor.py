
"""
Performance Batch Processor
===========================

Optimized batch processing for embedding generation with parallel execution.

"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class BatchEmbeddingProcessor:
    """Generates embeddings by fanning out sub-batches to Ollama in parallel."""

    def __init__(
        self,
        ollama_client,
        batch_size: int = 64,
        max_workers: int = 8,
    ) -> None:
        """Initialise with an OllamaClient and optional batch tunables."""
        self.ollama_client = ollama_client
        self.batch_size = batch_size
        self.max_workers = max_workers

        logger.info(
            f"BatchEmbeddingProcessor initialized "
            f"(batch_size={batch_size}, concurrent_batches={config.EMBEDDING_CONCURRENT_BATCHES})"
        )

    def process_batch(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float] | None]:
        """Return one embedding per text; failed items are None."""
        start_time = time.time()
        total = len(texts)

        logger.info(
            f"Processing {total} embeddings in batches of {self.batch_size} "
            f"(concurrent={config.EMBEDDING_CONCURRENT_BATCHES})"
        )

        results: list[list[float] | None] = [None] * total
        sub_batches = [
            (start, min(start + self.batch_size, total))
            for start in range(0, total, self.batch_size)
        ]
        processed = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=config.EMBEDDING_CONCURRENT_BATCHES) as executor:
            future_to_range = {
                executor.submit(
                    self.ollama_client.generate_embeddings_batch,
                    model,
                    texts[start:end],
                ): (start, end)
                for start, end in sub_batches
            }

            for future in as_completed(future_to_range):
                start, end = future_to_range[future]
                try:
                    batch_embeddings = future.result()
                except Exception as exc:
                    logger.warning(f"Batch [{start}:{end}] failed: {exc}")
                    failed += end - start
                    continue

                for i, embedding in enumerate(batch_embeddings):
                    if embedding is not None:
                        results[start + i] = embedding
                        processed += 1
                    else:
                        failed += 1

                logger.info(f"Progress: {(end / total) * 100:.1f}% ({end}/{total})")

        elapsed = time.time() - start_time
        rate = total / elapsed if elapsed > 0 else 0
        logger.info(f"Completed: {processed} successful, {failed} failed in {elapsed:.2f}s ({rate:.1f} emb/s)")

        return results

    def _generate_single(
        self,
        text: str,
        model: str,
    ) -> list[float] | None:
        """Generate embedding for single text."""
        try:
            success, embedding = self.ollama_client.generate_embedding(model, text)
            return embedding if success else None
        except Exception as e:
            logger.debug(f"Embedding generation failed: {e}")
            return None
