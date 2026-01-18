# -*- coding: utf-8 -*-
"""
Encoding Fix Script
===================
Fixes encoding issues in Python source files by converting them to UTF-8.
Specifically handles Windows-1252 characters that should be UTF-8.
"""

import os
import sys
from pathlib import Path

def fix_file_encoding(file_path):
    """Fix encoding issues in a single file."""
    try:
        # Try reading with different encodings
        content = None
        original_encoding = None
        
        # Try UTF-8 first
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                original_encoding = 'utf-8'
        except UnicodeDecodeError:
            # Try Windows-1252 (cp1252)
            try:
                with open(file_path, 'r', encoding='cp1252') as f:
                    content = f.read()
                    original_encoding = 'cp1252'
            except UnicodeDecodeError:
                # Try latin-1 as last resort
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                    original_encoding = 'latin-1'
        
        if content is None:
            return False, "Could not read file"
        
        # Replace common problematic characters
        replacements = {
            '\x91': "'",  # Left single quote
            '\x92': "'",  # Right single quote
            '\x93': '"',  # Left double quote
            '\x94': '"',  # Right double quote
            '\x96': '-',  # En dash (replaced with hyphen)
            '\x97': '-',  # Em dash (replaced with hyphen)
            '\x85': '...',  # Ellipsis (replaced with three dots)
        }
        
        modified = False
        for old_char, new_char in replacements.items():
            if old_char in content:
                content = content.replace(old_char, new_char)
                modified = True
        
        # Write back as UTF-8
        if modified or original_encoding != 'utf-8':
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(content)
            return True, f"Fixed ({original_encoding} ? UTF-8)"
        
        return False, "Already UTF-8"
        
    except Exception as e:
        return False, f"Error: {str(e)}"


def main():
    """Scan and fix all Python files in the solution."""
    root_dir = Path(__file__).parent
    
    print("=" * 70)
    print("Encoding Fix Script - Converting files to UTF-8")
    print("=" * 70)
    print()
    
    # Find all Python files
    python_files = []
    for pattern in ['**/*.py']:
        python_files.extend(root_dir.glob(pattern))
    
    # Exclude virtual environment and cache directories
    exclude_patterns = ['venv', '.venv', 'env', '__pycache__', '.git', 'build', 'dist']
    python_files = [
        f for f in python_files 
        if not any(pattern in str(f) for pattern in exclude_patterns)
    ]
    
    print(f"Found {len(python_files)} Python files to check\n")
    
    fixed_count = 0
    error_count = 0
    
    for file_path in sorted(python_files):
        rel_path = file_path.relative_to(root_dir)
        success, message = fix_file_encoding(file_path)
        
        if success:
            print(f"? {rel_path}: {message}")
            fixed_count += 1
        elif "Error" in message:
            print(f"? {rel_path}: {message}")
            error_count += 1
    
    print()
    print("=" * 70)
    print(f"Summary: {fixed_count} files fixed, {error_count} errors")
    print("=" * 70)
    
    return 0 if error_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
