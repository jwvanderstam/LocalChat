# -*- coding: utf-8 -*-
"""
Direct fix for api_routes.py encoding issue.
Run this script to fix the Windows-1252 character in api_routes.py
"""

import os
import sys

def fix_api_routes():
    """Fix the encoding issue in api_routes.py"""
    file_path = r'src\routes\api_routes.py'
    
    if not os.path.exists(file_path):
        print(f"ERROR: File not found: {file_path}")
        return False
    
    try:
        # Read the file with cp1252 encoding (Windows-1252)
        with open(file_path, 'r', encoding='cp1252') as f:
            content = f.read()
        
        print(f"? Read file successfully ({len(content)} characters)")
        
        # Replace the problematic Windows-1252 em-dash (byte 0x97) with UTF-8 em-dash
        replacements_made = 0
        
        # Replace byte 0x97 (em-dash in Windows-1252) with hyphen
        if '\x97' in content:
            content = content.replace('\x97', '-')
            replacements_made += 1
            print(f"? Replaced Windows-1252 em-dash (\\x97) with hyphen (-)")
        
        # Replace other common Windows-1252 characters
        replacements = {
            '\x91': "'",  # Left single quote
            '\x92': "'",  # Right single quote  
            '\x93': '"',  # Left double quote
            '\x94': '"',  # Right double quote
            '\x96': '-',  # En dash (replaced with hyphen)
            '\x85': '...',  # Ellipsis (replaced with three dots)
        }
        
        for old_char, new_char in replacements.items():
            if old_char in content:
                content = content.replace(old_char, new_char)
                replacements_made += 1
                print(f"? Replaced {repr(old_char)} with {repr(new_char)}")
        
        # Write back as UTF-8 with BOM to ensure Windows recognizes it
        with open(file_path, 'w', encoding='utf-8-sig', newline='\n') as f:
            f.write(content)
        
        print(f"\n? Successfully fixed {file_path}")
        print(f"  Total replacements: {replacements_made}")
        print(f"  Encoding: UTF-8 with BOM")
        return True
        
    except UnicodeDecodeError as e:
        print(f"ERROR: Could not decode file: {e}")
        print("Trying with latin-1 encoding...")
        
        try:
            # Fallback to latin-1 (ISO-8859-1)
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            
            # Same replacements - replace with hyphen
            content = content.replace('\x97', '-')
            
            with open(file_path, 'w', encoding='utf-8-sig', newline='\n') as f:
                f.write(content)
            
            print(f"? Fixed using latin-1 fallback")
            return True
            
        except Exception as e2:
            print(f"ERROR: Fallback also failed: {e2}")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("=" * 70)
    print("API Routes Encoding Fix")
    print("=" * 70)
    print()
    
    success = fix_api_routes()
    
    print()
    print("=" * 70)
    
    if success:
        print("? COMPLETE - Please restart your application")
        sys.exit(0)
    else:
        print("? FAILED - Manual intervention required")
        sys.exit(1)
