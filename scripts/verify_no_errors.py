"""
Error Message Verification Script
==================================

Checks for any error messages, warnings, or issues in the codebase.
Run this to verify that all known issues have been addressed.

Usage:
    python scripts/verify_no_errors.py
"""

import sys
import warnings
from pathlib import Path

def test_imports():
    """Test that all modules import without errors."""
    print("\n" + "=" * 60)
    print("Testing Module Imports")
    print("=" * 60)
    
    modules = [
        'src',
        'src.config',
        'src.db',
        'src.exceptions',
        'src.ollama_client',
        'src.utils.logging_config',
    ]
    
    all_passed = True
    
    for module_name in modules:
        try:
            __import__(module_name)
            print(f"  OK   {module_name}")
        except Exception as e:
            print(f"  FAIL {module_name}: {e}")
            all_passed = False
    
    return all_passed


def test_syntax():
    """Test Python syntax for all source files."""
    print("\n" + "=" * 60)
    print("Testing Python Syntax")
    print("=" * 60)
    
    src_dir = Path(__file__).parent.parent / 'src'
    py_files = list(src_dir.rglob('*.py'))
    
    all_passed = True
    errors = []
    
    for py_file in py_files:
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                compile(f.read(), py_file, 'exec')
            print(f"  OK   {py_file.relative_to(src_dir.parent)}")
        except SyntaxError as e:
            print(f"  FAIL {py_file.relative_to(src_dir.parent)}: {e}")
            errors.append((py_file, e))
            all_passed = False
    
    return all_passed, errors


def test_warnings():
    """Test for unwanted warnings."""
    print("\n" + "=" * 60)
    print("Testing Warning Suppressions")
    print("=" * 60)
    
    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # Import modules that might generate warnings
        try:
            import src
            import src.db
            import src.config
        except Exception as e:
            print(f"  FAIL Import error: {e}")
            return False
        
        # Check for specific warnings we want to suppress
        pydf2_warnings = [warning for warning in w 
                         if 'PyPDF2' in str(warning.message) or 'deprecated' in str(warning.message).lower()]
        
        if pydf2_warnings:
            print(f"  WARN Found {len(pydf2_warnings)} PyPDF2 warnings (should be suppressed)")
            for warning in pydf2_warnings:
                print(f"       {warning.message}")
            return False
        else:
            print("  OK   No PyPDF2 deprecation warnings")
    
    return True


def test_configuration():
    """Test configuration loading."""
    print("\n" + "=" * 60)
    print("Testing Configuration")
    print("=" * 60)
    
    try:
        import os
        
        # Check required environment variables
        required_vars = ['PG_PASSWORD']
        missing = []
        
        for var in required_vars:
            if var not in os.environ:
                missing.append(var)
        
        if missing:
            print(f"  WARN Missing environment variables: {', '.join(missing)}")
            print("       These should be set in .env file")
        else:
            print("  OK   All required environment variables are set")
        
        # Try to import config
        from src import config
        print(f"  OK   Configuration loaded successfully")
        print(f"       Database: {config.PG_HOST}:{config.PG_PORT}/{config.PG_DB}")
        print(f"       Ollama: {config.OLLAMA_BASE_URL}")
        
        return True
        
    except Exception as e:
        print(f"  FAIL Configuration error: {e}")
        return False


def main():
    """Run all verification tests."""
    print("\n" + "=" * 60)
    print("LocalChat - Error Verification Script")
    print("=" * 60)
    
    results = {
        'imports': test_imports(),
        'syntax': test_syntax()[0],
        'warnings': test_warnings(),
        'config': test_configuration(),
    }
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "OK  " if passed else "FAIL"
        print(f"  {symbol} {test_name.capitalize()}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("Result: ALL CHECKS PASSED")
        print("=" * 60)
        print("\nThe codebase is clean with no errors!")
        print("All known warnings have been properly suppressed.")
        return 0
    else:
        print("Result: SOME CHECKS FAILED")
        print("=" * 60)
        print("\nPlease review the failures above.")
        print("Run 'python scripts/suppress_warnings.py' to fix warning issues.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
