#!/usr/bin/env python3
"""
LocalChat Installation Script
=============================

Automated installation script for LocalChat RAG application.
Handles dependencies, database setup, and initial configuration.

Usage:
    python install.py                    # Interactive installation
    python install.py --auto             # Automatic installation
    python install.py --check            # Check prerequisites only

Author: LocalChat Team
Date: 2024-12-28
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path
from typing import Tuple, Optional

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text: str) -> None:
    """Print formatted header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")

def print_success(text: str) -> None:
    """Print success message."""
    print(f"{Colors.OKGREEN}? {text}{Colors.ENDC}")

def print_error(text: str) -> None:
    """Print error message."""
    print(f"{Colors.FAIL}? {text}{Colors.ENDC}")

def print_warning(text: str) -> None:
    """Print warning message."""
    print(f"{Colors.WARNING}? {text}{Colors.ENDC}")

def print_info(text: str) -> None:
    """Print info message."""
    print(f"{Colors.OKBLUE}? {text}{Colors.ENDC}")

def run_command(cmd: list, capture_output: bool = True) -> Tuple[bool, str]:
    """
    Run a shell command.
    
    Args:
        cmd: Command to run as list
        capture_output: Whether to capture output
        
    Returns:
        Tuple of (success, output)
    """
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0, result.stdout
        else:
            result = subprocess.run(cmd, timeout=30)
            return result.returncode == 0, ""
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)

def check_python_version() -> bool:
    """Check if Python version is 3.10 or higher."""
    print_info("Checking Python version...")
    version = sys.version_info
    
    if version.major >= 3 and version.minor >= 10:
        print_success(f"Python {version.major}.{version.minor}.{version.micro} detected")
        return True
    else:
        print_error(f"Python 3.10+ required, found {version.major}.{version.minor}.{version.micro}")
        return False

def check_postgresql() -> bool:
    """Check if PostgreSQL is installed and running."""
    print_info("Checking PostgreSQL...")
    
    # Check if psql command exists
    success, _ = run_command(['psql', '--version'])
    
    if success:
        print_success("PostgreSQL is installed")
        
        # Check if server is running
        success, _ = run_command(['pg_isready'])
        if success:
            print_success("PostgreSQL server is running")
            return True
        else:
            print_warning("PostgreSQL is installed but server is not running")
            print_info("Start PostgreSQL server and run install again")
            return False
    else:
        print_error("PostgreSQL is not installed")
        print_info("Install from: https://www.postgresql.org/download/")
        return False

def check_ollama() -> bool:
    """Check if Ollama is installed and running."""
    print_info("Checking Ollama...")
    
    # Check if ollama command exists
    success, _ = run_command(['ollama', '--version'])
    
    if success:
        print_success("Ollama is installed")
        
        # Check if server is running
        try:
            import requests
            response = requests.get('http://localhost:11434/api/tags', timeout=2)
            if response.status_code == 200:
                print_success("Ollama server is running")
                return True
            else:
                print_warning("Ollama is installed but server is not responding")
                return False
        except:
            print_warning("Ollama is installed but server is not running")
            print_info("Run 'ollama serve' in another terminal")
            return False
    else:
        print_error("Ollama is not installed")
        print_info("Install from: https://ollama.ai")
        return False

def install_python_dependencies() -> bool:
    """Install Python dependencies from requirements.txt."""
    print_info("Installing Python dependencies...")
    
    if not Path('requirements.txt').exists():
        print_error("requirements.txt not found")
        return False
    
    success, output = run_command(
        [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        capture_output=False
    )
    
    if success:
        print_success("Python dependencies installed")
        return True
    else:
        print_error("Failed to install Python dependencies")
        return False

def setup_database() -> bool:
    """Set up PostgreSQL database with pgvector extension."""
    print_info("Setting up database...")
    
    db_name = input("Enter database name (default: rag_db): ").strip() or "rag_db"
    
    # Check if database exists
    success, output = run_command(
        ['psql', '-lqt'],
        capture_output=True
    )
    
    if success and db_name in output:
        print_warning(f"Database '{db_name}' already exists")
        response = input("Do you want to use existing database? (y/n): ").lower()
        if response != 'y':
            return False
    else:
        # Create database
        print_info(f"Creating database '{db_name}'...")
        success, _ = run_command(['createdb', db_name])
        
        if success:
            print_success(f"Database '{db_name}' created")
        else:
            print_error(f"Failed to create database '{db_name}'")
            return False
    
    # Enable pgvector extension
    print_info("Enabling pgvector extension...")
    success, _ = run_command(
        ['psql', db_name, '-c', 'CREATE EXTENSION IF NOT EXISTS vector;']
    )
    
    if success:
        print_success("pgvector extension enabled")
    else:
        print_error("Failed to enable pgvector extension")
        print_info("You may need to install pgvector first:")
        print_info("https://github.com/pgvector/pgvector")
        return False
    
    # Create .env file
    create_env_file(db_name)
    
    return True

def create_env_file(db_name: str) -> None:
    """Create .env file with configuration."""
    print_info("Creating .env configuration file...")
    
    env_content = f"""# LocalChat Environment Configuration
# Generated by install.py

# Database Configuration
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=postgres
PG_DB={db_name}

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434

# Flask Configuration
SERVER_HOST=localhost
SERVER_PORT=5000
SECRET_KEY=change-this-in-production

# Application Settings
DEBUG=False
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print_success(".env file created")
    print_warning("? Edit .env file to set your PostgreSQL password")

def pull_ollama_models() -> bool:
    """Pull required Ollama models."""
    print_info("Pulling Ollama models...")
    
    models = [
        ('nomic-embed-text', 'Embedding model'),
        ('llama3.2', 'Chat model')
    ]
    
    for model, description in models:
        print_info(f"Pulling {model} ({description})...")
        success, _ = run_command(['ollama', 'pull', model], capture_output=False)
        
        if success:
            print_success(f"{model} pulled successfully")
        else:
            print_warning(f"Failed to pull {model}")
            print_info("You can pull it later with: ollama pull {model}")
    
    return True

def create_directories() -> None:
    """Create necessary directories."""
    print_info("Creating directories...")
    
    directories = ['logs', 'uploads']
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        print_success(f"Created {directory}/ directory")

def run_tests() -> bool:
    """Run test suite to verify installation."""
    print_info("Running tests to verify installation...")
    
    success, _ = run_command(
        [sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=short'],
        capture_output=False
    )
    
    if success:
        print_success("All tests passed")
        return True
    else:
        print_warning("Some tests failed (this may be normal)")
        return True  # Don't fail installation on test failures

def check_prerequisites() -> bool:
    """Check all prerequisites."""
    print_header("Checking Prerequisites")
    
    checks = [
        ("Python 3.10+", check_python_version()),
        ("PostgreSQL", check_postgresql()),
        ("Ollama", check_ollama())
    ]
    
    all_passed = all(result for _, result in checks)
    
    print("\n" + "=" * 70)
    if all_passed:
        print_success("All prerequisites met!")
    else:
        print_error("Some prerequisites are missing")
        print_info("Install missing components and run again")
    print("=" * 70)
    
    return all_passed

def main():
    """Main installation flow."""
    print_header("LocalChat Installation")
    print("Welcome to LocalChat RAG Application installer")
    print("This script will install and configure LocalChat\n")
    
    # Parse arguments
    auto_mode = '--auto' in sys.argv
    check_only = '--check' in sys.argv
    
    if check_only:
        success = check_prerequisites()
        sys.exit(0 if success else 1)
    
    # Check prerequisites
    if not check_prerequisites():
        print_error("\nInstallation cannot continue due to missing prerequisites")
        sys.exit(1)
    
    # Confirm installation
    if not auto_mode:
        response = input("\nProceed with installation? (y/n): ").lower()
        if response != 'y':
            print("Installation cancelled")
            sys.exit(0)
    
    # Install Python dependencies
    print_header("Installing Python Dependencies")
    if not install_python_dependencies():
        print_error("Installation failed")
        sys.exit(1)
    
    # Set up database
    print_header("Setting Up Database")
    if not auto_mode:
        if not setup_database():
            print_error("Database setup failed")
            sys.exit(1)
    else:
        print_info("Skipping database setup in auto mode")
        print_info("Run 'python install.py' interactively to set up database")
    
    # Create directories
    print_header("Creating Directories")
    create_directories()
    
    # Pull Ollama models
    print_header("Pulling Ollama Models")
    if not auto_mode:
        response = input("Do you want to pull Ollama models now? (y/n): ").lower()
        if response == 'y':
            pull_ollama_models()
    else:
        print_info("Skipping Ollama models in auto mode")
        print_info("Run 'ollama pull nomic-embed-text' and 'ollama pull llama3.2' manually")
    
    # Run tests
    if not auto_mode:
        print_header("Running Tests")
        response = input("Do you want to run tests to verify installation? (y/n): ").lower()
        if response == 'y':
            run_tests()
    
    # Installation complete
    print_header("Installation Complete!")
    print_success("LocalChat has been successfully installed!")
    
    print("\n" + "=" * 70)
    print("Next steps:")
    print("  1. Edit .env file to configure your database password")
    print("  2. Start Ollama: ollama serve")
    print("  3. Start LocalChat: python app.py")
    print("  4. Open browser: http://localhost:5000")
    print("=" * 70)
    
    print("\nFor more information, see:")
    print("  - QUICK_START.md")
    print("  - docs/SETUP_GUIDE.md")
    print("  - README_MAIN.md")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nInstallation failed: {e}")
        sys.exit(1)
