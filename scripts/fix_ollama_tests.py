#!/usr/bin/env python3
"""
Fix Ollama test failures by updating to match current API.

Issues:
1. generate_chat_response no longer has 'context' parameter
2. Message format expectations may be outdated
3. Response format assertions may be brittle
"""

import re
from pathlib import Path

def fix_ollama_tests():
    """Fix test_ollama_client.py and test_ollama_complete.py"""
    
    # File 1: test_ollama_client.py
    file1 = Path("tests/unit/test_ollama_client.py")
    if file1.exists():
        content = file1.read_text(encoding='utf-8')
        
        # Remove context parameter from all generate_chat_response calls
        # Pattern: context="" or context="some text"
        content = re.sub(
            r',\s*context="[^"]*"',
            '',
            content
        )
        
        file1.write_text(content, encoding='utf-8')
        print(f"? Fixed {file1}")
    
    # File 2: test_ollama_complete.py  
    file2 = Path("tests/unit/test_ollama_complete.py")
    if file2.exists():
        content = file2.read_text(encoding='utf-8')
        
        # Remove context parameter
        content = re.sub(
            r',\s*context="[^"]*"',
            '',
            content
        )
        
        file2.write_text(content, encoding='utf-8')
        print(f"? Fixed {file2}")
    
    print("\n?? Test fixes applied!")
    print("Run: pytest tests/unit/test_ollama*.py -v")

if __name__ == "__main__":
    fix_ollama_tests()
