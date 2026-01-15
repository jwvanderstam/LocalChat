#!/usr/bin/env python3
"""
Surgical MONTH2_ENABLED Removal - Final Push
=============================================

Removes specific MONTH2_ENABLED patterns from app.py line by line.
"""

from pathlib import Path
import re

def main():
    app_py = Path("src/app.py")
    
    # Read file
    with open(app_py, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    print(f"Original: {len(lines)} lines")
    
    # Track what we're removing
    to_remove = []
    
    # 1. Remove error handler block (lines 236-369)
    # Find start: "# ERROR HANDLERS - MONTH 2"
    # Find end: "# WEB ROUTES" (first occurrence)
    in_error_block = False
    error_block_start = None
    error_block_end = None
    
    for i, line in enumerate(lines):
        if "# ERROR HANDLERS - MONTH 2" in line:
            error_block_start = i
            in_error_block = True
        elif in_error_block and "# WEB ROUTES" in line:
            error_block_end = i
            break
    
    if error_block_start and error_block_end:
        print(f"Removing error handler block: lines {error_block_start}-{error_block_end}")
        # Keep the comment but replace the block
        replacement = [
            "# ============================================================================\n",
            "# ERROR HANDLERS\n",
            "# ============================================================================\n",
            "# Error handlers registered via src/routes/error_handlers.py (app_factory pattern)\n",
            "\n"
        ]
        lines = lines[:error_block_start] + replacement + lines[error_block_end:]
    
    # 2. Remove remaining MONTH2_ENABLED conditionals
    new_lines = []
    skip_until = -1
    
    for i, line in enumerate(lines):
        if i < skip_until:
            continue
            
        # Pattern: if MONTH2_ENABLED: (followed by simple assignment)
        if "if MONTH2_ENABLED:" in line and i < len(lines) - 1:
            # Check next lines for the pattern
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            
            # If next line is indented code, keep it but unindent
            if next_line.strip() and next_line.startswith("        "):
                # Skip the if line, keep the content unindented
                new_lines.append(next_line[4:])  # Remove 4 spaces
                skip_until = i + 2
                continue
        
        # Pattern: if MONTH2_ENABLED and isinstance(...)
        if "if MONTH2_ENABLED and isinstance" in line:
            # Replace with just isinstance check
            new_line = line.replace("if MONTH2_ENABLED and isinstance", "if isinstance")
            new_lines.append(new_line)
            continue
        
        new_lines.append(line)
    
    # Write result
    with open(app_py, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"Result: {len(new_lines)} lines")
    print(f"Removed: {len(lines) - len(new_lines)} lines")
    
    # Check remaining MONTH2
    content = ''.join(new_lines)
    remaining = content.count('MONTH2_ENABLED')
    print(f"Remaining MONTH2_ENABLED: {remaining}")
    
    return remaining

if __name__ == "__main__":
    count = main()
    if count == 0:
        print("? All MONTH2_ENABLED removed!")
    else:
        print(f"??  Still {count} occurrences remaining")
    exit(0 if count == 0 else 1)
