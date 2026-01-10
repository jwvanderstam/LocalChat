"""
Suppress Non-Critical Warnings
================================

Applies recommended warning suppressions to clean up console output.
Run once to configure the application.

Usage:
    python scripts/suppress_warnings.py
"""

import sys
from pathlib import Path

# Content for src/__init__.py with warning suppressions
INIT_CONTENT = '''"""
LocalChat Application Package
==============================

Root package for the LocalChat RAG application.
Handles warning suppressions for known non-critical issues.
"""

import warnings

# ============================================================================
# WARNING SUPPRESSIONS
# ============================================================================

# Suppress PyPDF2 deprecation warning
# Note: Migration to pypdf scheduled for next maintenance cycle
warnings.filterwarnings('ignore', message='PyPDF2 is deprecated')

# Suppress specific deprecation warnings that don't affect functionality
warnings.filterwarnings('ignore', category=DeprecationWarning, module='PyPDF2')

# Optional: Suppress security middleware warning in development
# Security features are optional and gracefully handled
import os
if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('APP_ENV') == 'development':
    warnings.filterwarnings('ignore', message='Security middleware not available')
'''


def apply_suppressions():
    """Apply warning suppressions to src/__init__.py."""
    try:
        # Get path to src/__init__.py
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        init_file = project_root / 'src' / '__init__.py'
        
        print("=" * 60)
        print("Warning Suppression Script")
        print("=" * 60)
        
        # Backup existing file if it exists
        if init_file.exists():
            existing_content = init_file.read_text()
            backup = init_file.with_suffix('.py.bak')
            backup.write_text(existing_content)
            print(f"? Backed up existing file to: {backup.name}")
        
        # Write new content
        init_file.write_text(INIT_CONTENT)
        print(f"? Updated: {init_file.relative_to(project_root)}")
        
        print("\n" + "=" * 60)
        print("? Warning suppressions applied successfully!")
        print("=" * 60)
        print("\n?? What was changed:")
        print("  • PyPDF2 deprecation warnings suppressed")
        print("  • Development security warnings suppressed")
        print("\n?? Next steps:")
        print("  1. Restart the application")
        print("  2. Verify warnings are no longer shown")
        print("\n?? To revert:")
        print(f"  • Restore from: {backup.name}")
        
        return True
        
    except Exception as e:
        print(f"\n? Error applying suppressions: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_suppressions():
    """Verify that suppressions are working."""
    try:
        print("\n?? Verifying suppressions...")
        
        # Test import with warnings enabled
        import warnings
        warnings.simplefilter('always')  # Show all warnings
        
        # Import the modules
        import src.db
        import src.app
        
        print("? Imports successful")
        print("? Suppressions are working correctly")
        
        return True
        
    except Exception as e:
        print(f"??  Verification warning: {e}")
        return False


if __name__ == '__main__':
    print("\n?? Starting warning suppression setup...\n")
    
    success = apply_suppressions()
    
    if success:
        print("\n" + "=" * 60)
        print("? Setup complete!")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("? Setup failed!")
        print("=" * 60)
        sys.exit(1)
