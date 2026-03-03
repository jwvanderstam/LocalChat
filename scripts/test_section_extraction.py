#!/usr/bin/env python3
"""Quick test for section title extraction."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.rag import doc_processor

# Test cases
test_cases = [
    # (input, expected_output)
    ("Introduction:\n\nThis is content...", "Introduction"),
    ("Data Storage\n\nSome text here", "Data Storage"),
    ("1. Introduction\n\nContent", None),  # Should skip numbered
    ("a very long title that goes on and on for more than 100 characters which should be rejected", None),
    ("", None),  # Empty
    ("Regular text without title\ncontinued here", None),
]

print("Testing section title extraction...")
print("=" * 60)

passed = 0
failed = 0

for text, expected in test_cases:
    result = doc_processor._extract_section_title(text)
    status = "?" if result == expected else "?"
    
    if result == expected:
        passed += 1
    else:
        failed += 1
    
    print(f"{status} Input: {repr(text[:50])}")
    print(f"  Expected: {expected}")
    print(f"  Got: {result}")
    print()

print("=" * 60)
print(f"Results: {passed} passed, {failed} failed")

if failed == 0:
    print("? All tests passed!")
    sys.exit(0)
else:
    print("? Some tests failed")
    sys.exit(1)
