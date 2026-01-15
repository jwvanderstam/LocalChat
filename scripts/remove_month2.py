#!/usr/bin/env python3
"""
Automated MONTH2_ENABLED Removal Script
========================================

Removes all MONTH2_ENABLED conditionals from app.py in one go.
This is an aggressive but safe approach with backup.
"""

import re
import shutil
from pathlib import Path

def main():
    app_py = Path("src/app.py")
    
    # Create backup
    backup = Path("src/app.py.backup")
    shutil.copy(app_py, backup)
    print(f"? Backup created: {backup}")
    
    # Read file
    with open(app_py, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_lines = content.count('\n')
    
    # Pattern 1: Remove error handler block (lines 236-369)
    # Just remove the entire conditional wrapper
    content = re.sub(
        r'# ERROR HANDLERS - MONTH 2 \(OPTIONAL\)\n# =+\n\nif MONTH2_ENABLED:\n',
        '# ERROR HANDLERS\n# ' + '='*76 + '\n\n',
        content,
        flags=re.MULTILINE
    )
    
    # Remove the else clause at end of error handlers
    content = re.sub(
        r'\n    logger\.info\("? Month 2 error handlers registered"\)\nelse:\n    logger\.info\("??  Using basic error handlers \(Month 1 mode\)"\)',
        '\nlogger.info("? Error handlers registered")',
        content
    )
    
    # Fix indentation of error handler functions (unindent by 4 spaces)
    lines = content.split('\n')
    new_lines = []
    in_handler_section = False
    
    for i, line in enumerate(lines):
        # Detect start of error handler section
        if '# ERROR HANDLERS' in line and i < 250:
            in_handler_section = True
            new_lines.append(line)
            continue
        
        # Detect end of error handler section
        if '# WEB ROUTES' in line and i < 400:
            in_handler_section = False
            new_lines.append(line)
            continue
        
        # Unindent handlers
        if in_handler_section and line.startswith('    '):
            new_lines.append(line[4:])  # Remove 4 spaces
        else:
            new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    # Pattern 2: Simplify exception handlers
    # Replace: if MONTH2_ENABLED and isinstance(...): with just if isinstance(...):
    content = re.sub(
        r'if MONTH2_ENABLED and isinstance\(e, \(PydanticValidationError, exceptions\.LocalChatException\)\):',
        r'if isinstance(e, (PydanticValidationError, exceptions.LocalChatException)):',
        content
    )
    
    # Pattern 3: Remove validation conditionals in routes
    # This is the pattern: if MONTH2_ENABLED: request_data = ... else: basic validation
    
    # For chat route
    content = re.sub(
        r'if MONTH2_ENABLED:\s+request_data = ChatRequest\(\*\*data\)\s+message = sanitize_query\(request_data\.message\)\s+else:\s+# Month 1: Basic validation.*?(?=\n\n)',
        'request_data = ChatRequest(**data)\n        message = sanitize_query(request_data.message)',
        content,
        flags=re.DOTALL
    )
    
    # For retrieve route
    content = re.sub(
        r'if MONTH2_ENABLED:\s+request_data = RetrievalRequest\(\*\*data\)\s+query = sanitize_query\(request_data\.query\)\s+else:\s+# Month 1: Basic validation.*?(?=\n\n)',
        'request_data = RetrievalRequest(**data)\n        query = sanitize_query(request_data.query)',
        content,
        flags=re.DOTALL
    )
    
    # Pattern 4: Remove error raising conditionals
    content = re.sub(
        r'if MONTH2_ENABLED:\s+raise exceptions\.(\w+)\((.*?)\)\s+else:\s+return jsonify\(\{.*?\}\), \d+',
        r'raise exceptions.\1(\2)',
        content,
        flags=re.DOTALL
    )
    
    # Write file
    with open(app_py, 'w', encoding='utf-8') as f:
        f.write(content)
    
    new_lines = content.count('\n')
    print(f"? Processed {app_py}")
    print(f"   Lines: {original_lines} ? {new_lines} ({original_lines - new_lines} removed)")
    
    # Check for remaining MONTH2
    remaining = content.count('MONTH2_ENABLED')
    print(f"   Remaining MONTH2_ENABLED: {remaining}")
    
    if remaining > 0:
        print("??  Some MONTH2_ENABLED patterns remain - manual review needed")
    else:
        print("? All MONTH2_ENABLED patterns removed!")
    
    return remaining == 0

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
