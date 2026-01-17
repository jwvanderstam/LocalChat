# -*- coding: utf-8 -*-

"""
Dependency Checker and Auto-Installer
======================================

Automatically checks and installs all required dependencies for LocalChat.

Author: LocalChat Team
Created: 2025-01-15
"""

import subprocess
import sys
import importlib
from typing import List, Tuple, Dict

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

# Required packages with their pip names
REQUIRED_PACKAGES = {
    # Core Flask packages
    'flask': 'Flask==3.0.0',
    'werkzeug': 'Werkzeug==3.0.1',
    
    # API Documentation
    'flasgger': 'flasgger==0.9.7.1',
    
    # Caching
    'redis': 'redis==5.0.1',
    
    # Security
    'flask_jwt_extended': 'Flask-JWT-Extended==4.7.1',
    'flask_limiter': 'Flask-Limiter==3.5.0',
    'flask_cors': 'Flask-CORS==4.0.0',
    
    # Database - PostgreSQL
    'psycopg': 'psycopg[binary]>=3.2.0',
    'psycopg_pool': 'psycopg-pool>=3.2.0',
    
    # Validation
    'pydantic': 'pydantic==2.12.5',
    'email_validator': 'email-validator==2.3.0',
    
    # Document Processing
    'PyPDF2': 'PyPDF2==3.0.1',
    'pdfplumber': 'pdfplumber==0.11.0',
    'docx': 'python-docx==1.1.0',
    
    # HTTP Requests
    'requests': 'requests==2.31.0',
    
    # Numerical processing
    'numpy': 'numpy>=1.26.0',
    
    # Optional utilities
    'multipart': 'python-multipart==0.0.6',
    'markdown': 'markdown==3.5.1',
    
    # Development
    'dotenv': 'python-dotenv==1.0.0',
    
    # Testing (optional but recommended)
    'pytest': 'pytest==7.4.3',
    'pytest_cov': 'pytest-cov==7.0.0',
    'pytest_mock': 'pytest-mock==3.15.1',
    'faker': 'faker==39.0.0',
    'responses': 'responses==0.25.8',
    'freezegun': 'freezegun==1.5.5',
    'coverage': 'coverage==7.13.0',
}


def print_header():
    """Print fancy header."""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}  LocalChat Dependency Checker & Auto-Installer{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")


def check_package(package_name: str) -> bool:
    """
    Check if a package is installed.
    
    Args:
        package_name: Name of the package to check
    
    Returns:
        True if installed, False otherwise
    """
    try:
        importlib.import_module(package_name)
        return True
    except ImportError:
        return False


def install_package(pip_name: str) -> Tuple[bool, str]:
    """
    Install a package using pip.
    
    Args:
        pip_name: Package name with version for pip install
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--quiet', pip_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        return True, f"Successfully installed {pip_name}"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return False, f"Failed to install {pip_name}: {error_msg}"


def check_and_install_dependencies(auto_install: bool = True) -> Dict[str, str]:
    """
    Check all dependencies and optionally install missing ones.
    
    Args:
        auto_install: If True, automatically install missing packages
    
    Returns:
        Dictionary with status of each package
    """
    print_header()
    
    results = {}
    missing_packages = []
    installed_packages = []
    failed_packages = []
    
    print(f"{YELLOW}?? Checking dependencies...{RESET}\n")
    
    # Check all packages
    for package_name, pip_name in REQUIRED_PACKAGES.items():
        is_installed = check_package(package_name)
        
        if is_installed:
            print(f"  {GREEN}?{RESET} {package_name:<25} {GREEN}Installed{RESET}")
            results[package_name] = 'installed'
            installed_packages.append(package_name)
        else:
            print(f"  {RED}?{RESET} {package_name:<25} {RED}Missing{RESET}")
            results[package_name] = 'missing'
            missing_packages.append((package_name, pip_name))
    
    # Summary
    print(f"\n{BLUE}{'?' * 70}{RESET}")
    print(f"Total packages: {len(REQUIRED_PACKAGES)}")
    print(f"{GREEN}? Installed: {len(installed_packages)}{RESET}")
    print(f"{RED}? Missing: {len(missing_packages)}{RESET}")
    print(f"{BLUE}{'?' * 70}{RESET}\n")
    
    # Auto-install missing packages
    if missing_packages and auto_install:
        print(f"{YELLOW}?? Installing missing packages...{RESET}\n")
        
        for package_name, pip_name in missing_packages:
            print(f"  Installing {package_name}...", end=' ')
            success, message = install_package(pip_name)
            
            if success:
                print(f"{GREEN}? Done{RESET}")
                results[package_name] = 'installed'
            else:
                print(f"{RED}? Failed{RESET}")
                failed_packages.append(package_name)
                results[package_name] = 'failed'
                print(f"    {RED}{message}{RESET}")
        
        print(f"\n{BLUE}{'?' * 70}{RESET}")
        
        if failed_packages:
            print(f"{RED}??  Failed to install: {len(failed_packages)} packages{RESET}")
            for pkg in failed_packages:
                print(f"  - {pkg}")
        else:
            print(f"{GREEN}? All packages installed successfully!{RESET}")
        
        print(f"{BLUE}{'?' * 70}{RESET}\n")
    
    elif missing_packages and not auto_install:
        print(f"{YELLOW}??  Missing packages detected. Run with auto_install=True to install.{RESET}\n")
        print("To install manually, run:")
        print(f"  pip install {' '.join(pip_name for _, pip_name in missing_packages)}\n")
    
    return results


def verify_critical_imports():
    """
    Verify that critical imports work after installation.
    
    Returns:
        True if all critical imports work, False otherwise
    """
    print(f"{YELLOW}?? Verifying critical imports...{RESET}\n")
    
    critical_imports = [
        ('flask', 'Flask'),
        ('psycopg', 'PostgreSQL'),
        ('pydantic', 'Pydantic'),
        ('requests', 'Requests'),
        ('numpy', 'NumPy'),
    ]
    
    all_good = True
    
    for module, display_name in critical_imports:
        try:
            importlib.import_module(module)
            print(f"  {GREEN}?{RESET} {display_name:<20} {GREEN}OK{RESET}")
        except ImportError as e:
            print(f"  {RED}?{RESET} {display_name:<20} {RED}FAILED{RESET}")
            print(f"    Error: {str(e)}")
            all_good = False
    
    print(f"\n{BLUE}{'?' * 70}{RESET}")
    
    if all_good:
        print(f"{GREEN}? All critical imports verified!{RESET}")
    else:
        print(f"{RED}??  Some critical imports failed. Please check errors above.{RESET}")
    
    print(f"{BLUE}{'?' * 70}{RESET}\n")
    
    return all_good


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Check and install LocalChat dependencies'
    )
    parser.add_argument(
        '--no-install',
        action='store_true',
        help='Only check dependencies, do not install'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify imports after installation'
    )
    
    args = parser.parse_args()
    
    # Check and install
    results = check_and_install_dependencies(auto_install=not args.no_install)
    
    # Verify if requested
    if args.verify or not args.no_install:
        verify_critical_imports()
    
    # Exit with appropriate code
    missing = sum(1 for status in results.values() if status in ['missing', 'failed'])
    
    if missing > 0:
        print(f"\n{RED}??  {missing} package(s) could not be installed.{RESET}")
        print(f"{YELLOW}Please install them manually using pip.{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}?? All dependencies satisfied!{RESET}")
        print(f"{GREEN}LocalChat is ready to run!{RESET}\n")
        sys.exit(0)


if __name__ == '__main__':
    main()
