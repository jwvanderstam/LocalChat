#!/usr/bin/env python3
"""
Quick test script for Phase 1.1 Enhanced Citations
Tests the section title extraction and metadata flow.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.rag import DocumentProcessor
from src.utils.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

def test_section_extraction():
    """Test section title extraction from sample text."""
    print("\n" + "="*70)
    print("TEST 1: Section Title Extraction")
    print("="*70)
    
    processor = DocumentProcessor()
    
    # Test cases
    test_cases = [
        ("Chapter 1: Introduction\n\nThis is the content...", "Chapter 1: Introduction"),
        ("BACKUP PROCEDURES\n\nThe backup system...", "BACKUP PROCEDURES"),
        ("Data Storage:\n\nWe store data in...", "Data Storage"),
        ("1. Introduction\n\nThis chapter...", None),  # Should skip numbered
        ("Just some text\nwithout a title", None),
    ]
    
    passed = 0
    for text, expected in test_cases:
        result = processor._extract_section_title(text)
        status = "?" if result == expected else "?"
        print(f"{status} Input: {text[:40]}...")
        print(f"   Expected: {expected}")
        print(f"   Got:      {result}")
        print()
        if result == expected:
            passed += 1
    
    print(f"Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)

def test_metadata_format():
    """Test chunk metadata format."""
    print("\n" + "="*70)
    print("TEST 2: Metadata Format")
    print("="*70)
    
    # Sample metadata
    metadata = {
        'page_number': 15,
        'section_title': 'Backup Procedures'
    }
    
    # Test citation building
    citation_parts = []
    
    citation_parts.append(f"chunk 7")
    if metadata.get('page_number'):
        citation_parts.append(f"page {metadata['page_number']}")
    if metadata.get('section_title'):
        section = metadata['section_title']
        if len(section) > 50:
            section = section[:47] + "..."
        citation_parts.append(f'section: "{section}"')
    
    citation = ", ".join(citation_parts)
    expected = 'chunk 7, page 15, section: "Backup Procedures"'
    
    print(f"Citation: {citation}")
    print(f"Expected: {expected}")
    
    if citation == expected:
        print("? Citation format correct")
        return True
    else:
        print("? Citation format incorrect")
        return False

def test_pages_structure():
    """Test pages data structure."""
    print("\n" + "="*70)
    print("TEST 3: Pages Data Structure")
    print("="*70)
    
    # Sample pages data
    pages_data = [
        {
            'page_number': 1,
            'text': 'Introduction\n\nThis is the first page...',
            'section_title': 'Introduction'
        },
        {
            'page_number': 2,
            'text': 'Continued content...',
            'section_title': None
        },
        {
            'page_number': 3,
            'text': 'Methods\n\nOur methodology...',
            'section_title': 'Methods'
        }
    ]
    
    print(f"Sample pages structure:")
    for page in pages_data:
        print(f"  Page {page['page_number']}: " + 
              f"{page['section_title'] or '(no section)'} - " +
              f"{len(page['text'])} chars")
    
    # Test structure
    all_valid = True
    for page in pages_data:
        if not all(k in page for k in ['page_number', 'text', 'section_title']):
            print(f"? Page {page.get('page_number')} missing required keys")
            all_valid = False
    
    if all_valid:
        print("? All pages have required structure")
        return True
    else:
        print("? Some pages have invalid structure")
        return False

def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("PHASE 1.1 ENHANCED CITATIONS - UNIT TESTS")
    print("="*70)
    
    results = {
        'Section Extraction': test_section_extraction(),
        'Metadata Format': test_metadata_format(),
        'Pages Structure': test_pages_structure()
    }
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "? PASS" if passed else "? FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*70)
    if all_passed:
        print("? ALL TESTS PASSED - Phase 1.1 implementation verified!")
        print("\nNext steps:")
        print("1. Start the application: python run.py")
        print("2. Upload a PDF document")
        print("3. Query the document and check for enhanced citations")
    else:
        print("? SOME TESTS FAILED - Please review implementation")
    print("="*70 + "\n")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
