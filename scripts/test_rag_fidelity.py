#!/usr/bin/env python3
"""
RAG Fidelity Test Script
========================

Tests retrieval accuracy and measures exact-match fidelity.
Goal: 90%+ exact text matching from source documents.

Usage:
    python scripts/test_rag_fidelity.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag import DocumentProcessor
from src.db import db
from src.utils.logging_config import setup_logging, get_logger
from typing import List, Tuple
import difflib

setup_logging()
logger = get_logger(__name__)


class FidelityTester:
    """Tests RAG fidelity with exact-match scoring."""
    
    def __init__(self):
        self.processor = DocumentProcessor()
        self.test_queries = [
            # Query, Expected keywords (must appear exactly)
            ("eisen voor cloud hosting", ["eisen", "cloud", "hosting"]),
            ("service level agreements", ["service", "level"]),
            ("technisch applicatiebeheer", ["technisch", "applicatiebeheer"]),
            ("backup procedures", ["backup"]),
            ("disaster recovery", ["disaster", "recovery"]),
        ]
    
    def calculate_word_match_ratio(self, retrieved_text: str, expected_words: List[str]) -> float:
        """
        Calculate what percentage of expected words appear EXACTLY in retrieved text.
        
        Args:
            retrieved_text: Text retrieved from RAG
            expected_words: List of words that MUST appear exactly
            
        Returns:
            Float 0.0-1.0 representing match ratio
        """
        retrieved_lower = retrieved_text.lower()
        matched = sum(1 for word in expected_words if word.lower() in retrieved_lower)
        return matched / len(expected_words) if expected_words else 0.0
    
    def check_for_invented_words(self, retrieved_text: str) -> List[str]:
        """
        Check for common invented/garbled words.
        
        Returns:
            List of suspicious words found
        """
        suspicious_patterns = [
            "eieren",  # Should be "eisen"
            "overzichtskijk",  # Should be "overzicht"
            "Appliacatien",  # Should be "Applicatie" or "Applicaties"
        ]
        
        found = []
        for pattern in suspicious_patterns:
            if pattern.lower() in retrieved_text.lower():
                found.append(pattern)
        
        return found
    
    def test_single_query(self, query: str, expected_words: List[str]) -> Dict[str, Any]:
        """
        Test a single query and measure fidelity.
        
        Returns:
            Dict with test results
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing query: {query}")
        logger.info(f"Expected words: {expected_words}")
        
        try:
            # Retrieve context
            results = self.processor.retrieve_context(query, top_k=5)
            
            if not results:
                logger.warning("No results retrieved!")
                return {
                    'query': query,
                    'success': False,
                    'error': 'No results',
                    'fidelity': 0.0
                }
            
            # Extract text from results
            retrieved_texts = [chunk_text for chunk_text, _, _, _, _ in results]
            combined_text = " ".join(retrieved_texts)
            
            # Calculate metrics
            word_match_ratio = self.calculate_word_match_ratio(combined_text, expected_words)
            invented_words = self.check_for_invented_words(combined_text)
            
            # Log results
            logger.info(f"Retrieved {len(results)} chunks")
            logger.info(f"Word match ratio: {word_match_ratio:.2%}")
            
            if invented_words:
                logger.error(f"? Found invented words: {invented_words}")
            else:
                logger.info("? No invented words detected")
            
            # Show sample
            logger.info(f"Sample text (first 200 chars): {combined_text[:200]}...")
            
            return {
                'query': query,
                'success': True,
                'fidelity': word_match_ratio,
                'chunks_retrieved': len(results),
                'invented_words': invented_words,
                'sample_text': combined_text[:500]
            }
            
        except Exception as e:
            logger.error(f"Error testing query: {e}", exc_info=True)
            return {
                'query': query,
                'success': False,
                'error': str(e),
                'fidelity': 0.0
            }
    
    def run_full_test(self) -> Dict[str, Any]:
        """
        Run full fidelity test suite.
        
        Returns:
            Dict with overall results
        """
        logger.info("="*60)
        logger.info("RAG FIDELITY TEST - Goal: 90%+ Exact Match")
        logger.info("="*60)
        
        results = []
        for query, expected_words in self.test_queries:
            result = self.test_single_query(query, expected_words)
            results.append(result)
        
        # Calculate overall stats
        successful_tests = [r for r in results if r['success']]
        if not successful_tests:
            logger.error("? No successful tests!")
            return {'overall_fidelity': 0.0, 'tests': results}
        
        avg_fidelity = sum(r['fidelity'] for r in successful_tests) / len(successful_tests)
        total_invented = sum(len(r.get('invented_words', [])) for r in results)
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("SUMMARY")
        logger.info("="*60)
        logger.info(f"Tests run: {len(results)}")
        logger.info(f"Successful: {len(successful_tests)}")
        logger.info(f"Average fidelity: {avg_fidelity:.2%}")
        logger.info(f"Total invented words: {total_invented}")
        
        if avg_fidelity >= 0.90:
            logger.info("? GOAL ACHIEVED: 90%+ fidelity!")
        else:
            logger.warning(f"??  Below goal: {avg_fidelity:.2%} < 90%")
        
        return {
            'overall_fidelity': avg_fidelity,
            'tests': results,
            'goal_met': avg_fidelity >= 0.90
        }


def main():
    """Run fidelity tests."""
    tester = FidelityTester()
    results = tester.run_full_test()
    
    # Exit code based on success
    sys.exit(0 if results['goal_met'] else 1)


if __name__ == '__main__':
    main()
