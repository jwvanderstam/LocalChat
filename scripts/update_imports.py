"""
Import Update Script
====================

Automatically updates imports in Python files after project restructuring.
Converts old flat imports to new src/ structure imports.

Usage:
    python update_imports.py --dry-run    # Preview changes
    python update_imports.py --execute    # Apply changes
    python update_imports.py --verify     # Check for remaining old imports

Author: LocalChat Team
Date: 2024-12-27
"""

import os
import re
from pathlib import Path
from typing import List, Tuple, Dict

class ImportUpdater:
    """Updates imports in Python files."""
    
    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir).resolve()
        self.changes: Dict[Path, List[Tuple[str, str]]] = {}
        
        # Define import mappings: old -> new
        self.import_mappings = {
            # Direct imports
            r'^import config$': 'from src import config',
            r'^import db$': 'from src import db',
            r'^import rag$': 'from src import rag',
            r'^import ollama_client$': 'from src import ollama_client',
            r'^import exceptions$': 'from src import exceptions',
            r'^import models$': 'from src import models',
            
            # From imports
            r'^from config import (.+)$': r'from src.config import \1',
            r'^from db import (.+)$': r'from src.db import \1',
            r'^from rag import (.+)$': r'from src.rag import \1',
            r'^from ollama_client import (.+)$': r'from src.ollama_client import \1',
            r'^from exceptions import (.+)$': r'from src.exceptions import \1',
            r'^from models import (.+)$': r'from src.models import \1',
            
            # Utils imports
            r'^from utils\.logging_config import (.+)$': r'from src.utils.logging_config import \1',
            r'^from utils\.sanitization import (.+)$': r'from src.utils.sanitization import \1',
            r'^from utils import (.+)$': r'from src.utils import \1',
            r'^import utils\.(.+)$': r'import src.utils.\1',
        }
    
    def scan_files(self) -> List[Path]:
        """Find all Python files that need updating."""
        python_files = []
        
        # Scan tests directory
        tests_dir = self.root / "tests"
        if tests_dir.exists():
            for py_file in tests_dir.rglob("*.py"):
                if py_file.name != "__init__.py":
                    python_files.append(py_file)
        
        # Scan src directory (for relative imports within src)
        src_dir = self.root / "src"
        if src_dir.exists():
            for py_file in src_dir.rglob("*.py"):
                if py_file.name != "__init__.py":
                    python_files.append(py_file)
        
        # Scan scripts directory
        scripts_dir = self.root / "scripts"
        if scripts_dir.exists():
            for py_file in scripts_dir.rglob("*.py"):
                python_files.append(py_file)
        
        # Scan root directory
        for py_file in self.root.glob("*.py"):
            if py_file.name not in ["restructure_project.py", "update_imports.py"]:
                python_files.append(py_file)
        
        return sorted(python_files)
    
    def analyze_file(self, file_path: Path) -> List[Tuple[str, str, int]]:
        """
        Analyze a file and identify import lines that need updating.
        
        Returns:
            List of (old_line, new_line, line_number) tuples
        """
        changes = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                
                # Skip comments and empty lines
                if not stripped or stripped.startswith('#'):
                    continue
                
                # Check each import pattern
                for old_pattern, new_template in self.import_mappings.items():
                    match = re.match(old_pattern, stripped)
                    if match:
                        # Generate new import line
                        if '\\1' in new_template:
                            # Has capture group
                            new_line = re.sub(old_pattern, new_template, stripped)
                        else:
                            # No capture group
                            new_line = new_template
                        
                        if new_line != stripped:
                            # Preserve indentation
                            indent = len(line) - len(line.lstrip())
                            new_line_with_indent = ' ' * indent + new_line + '\n'
                            changes.append((line, new_line_with_indent, line_num))
                            break
        
        except Exception as e:
            print(f"  ??  Error analyzing {file_path}: {e}")
        
        return changes
    
    def plan_updates(self) -> None:
        """Scan all files and plan import updates."""
        print("=" * 80)
        print("SCANNING FOR IMPORT UPDATES")
        print("=" * 80)
        
        files = self.scan_files()
        print(f"\nFound {len(files)} Python files to check\n")
        
        files_with_changes = 0
        total_changes = 0
        
        for file_path in files:
            changes = self.analyze_file(file_path)
            
            if changes:
                files_with_changes += 1
                total_changes += len(changes)
                self.changes[file_path] = changes
                
                rel_path = file_path.relative_to(self.root)
                print(f"\n?? {rel_path}")
                print(f"   {len(changes)} import(s) to update:")
                
                for old_line, new_line, line_num in changes:
                    print(f"   Line {line_num}:")
                    print(f"     - {old_line.strip()}")
                    print(f"     + {new_line.strip()}")
        
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Files needing updates: {files_with_changes}")
        print(f"Total import changes: {total_changes}")
        
        if total_changes == 0:
            print("\n? No import updates needed!")
        else:
            print(f"\n??  {total_changes} imports need updating")
    
    def execute_updates(self, dry_run: bool = True) -> None:
        """Execute the planned import updates."""
        if not self.changes:
            print("\n? No changes to apply!")
            return
        
        if dry_run:
            print("\n" + "=" * 80)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 80)
            print("\nRun with --execute to apply changes")
            return
        
        print("\n" + "=" * 80)
        print("APPLYING IMPORT UPDATES")
        print("=" * 80)
        
        files_updated = 0
        total_updates = 0
        
        for file_path, changes in self.changes.items():
            try:
                # Read file
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Apply changes
                new_content = content
                for old_line, new_line, _ in changes:
                    new_content = new_content.replace(old_line, new_line, 1)
                
                # Write back
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                files_updated += 1
                total_updates += len(changes)
                
                rel_path = file_path.relative_to(self.root)
                print(f"  ? Updated: {rel_path} ({len(changes)} imports)")
            
            except Exception as e:
                print(f"  ? Failed to update {file_path}: {e}")
        
        print("\n" + "=" * 80)
        print(f"? Updated {total_updates} imports in {files_updated} files")
        print("=" * 80)
    
    def verify_updates(self) -> bool:
        """Verify that no old-style imports remain."""
        print("=" * 80)
        print("VERIFYING IMPORT UPDATES")
        print("=" * 80)
        
        files = self.scan_files()
        remaining_issues = []
        
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    
                    # Check for old-style imports
                    old_patterns = [
                        r'^import (config|db|rag|ollama_client|exceptions|models)$',
                        r'^from (config|db|rag|ollama_client|exceptions|models) import',
                        r'^from utils\.',
                        r'^import utils\.',
                    ]
                    
                    for pattern in old_patterns:
                        if re.match(pattern, stripped):
                            rel_path = file_path.relative_to(self.root)
                            remaining_issues.append((rel_path, line_num, stripped))
            
            except Exception as e:
                print(f"  ??  Error checking {file_path}: {e}")
        
        if remaining_issues:
            print(f"\n? Found {len(remaining_issues)} old-style imports:\n")
            for file_path, line_num, line in remaining_issues:
                print(f"  {file_path}:{line_num}")
                print(f"    {line}")
            print("\n" + "=" * 80)
            return False
        else:
            print("\n? All imports updated successfully!")
            print("=" * 80)
            return True
    
    def update_src_internal_imports(self) -> None:
        """Update imports within src/ to use relative imports."""
        print("\n" + "=" * 80)
        print("UPDATING SRC/ INTERNAL IMPORTS TO RELATIVE")
        print("=" * 80)
        
        src_dir = self.root / "src"
        if not src_dir.exists():
            print("  ??  src/ directory not found")
            return
        
        # Patterns for src internal imports
        internal_mappings = {
            r'^from src import (.+)$': r'from . import \1',
            r'^from src\.(.+) import (.+)$': r'from .\1 import \2',
            r'^import src\.(.+)$': r'from . import \1',
        }
        
        files_updated = 0
        
        for py_file in src_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                changes = []
                
                for old_pattern, new_template in internal_mappings.items():
                    matches = re.finditer(old_pattern, new_content, re.MULTILINE)
                    for match in matches:
                        old_line = match.group(0)
                        new_line = re.sub(old_pattern, new_template, old_line)
                        new_content = new_content.replace(old_line, new_line)
                        changes.append((old_line, new_line))
                
                if changes:
                    with open(py_file, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    
                    rel_path = py_file.relative_to(self.root)
                    print(f"  ? Updated: {rel_path} ({len(changes)} imports)")
                    files_updated += 1
            
            except Exception as e:
                print(f"  ? Failed to update {py_file}: {e}")
        
        if files_updated > 0:
            print(f"\n? Updated {files_updated} files to use relative imports")
        else:
            print("\n  No internal imports to update")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Update imports after restructuring")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    parser.add_argument("--execute", action="store_true", help="Apply changes")
    parser.add_argument("--verify", action="store_true", help="Verify no old imports remain")
    parser.add_argument("--src-relative", action="store_true", help="Update src/ to use relative imports")
    args = parser.parse_args()
    
    updater = ImportUpdater()
    
    if args.verify:
        updater.verify_updates()
    elif args.src_relative:
        updater.update_src_internal_imports()
    else:
        updater.plan_updates()
        
        if args.execute:
            if updater.changes:
                response = input("\n??  Apply import updates? (yes/no): ")
                if response.lower() == "yes":
                    updater.execute_updates(dry_run=False)
                    print("\n?? Now updating src/ internal imports...")
                    updater.update_src_internal_imports()
                    print("\n? Import updates complete!")
                    print("\nNext steps:")
                    print("1. Run: python update_imports.py --verify")
                    print("2. Run: pytest")
                    print("3. Run: python -m src.app")
                else:
                    print("Updates cancelled.")
            else:
                print("\n? No updates needed!")
        else:
            updater.execute_updates(dry_run=True)


if __name__ == "__main__":
    main()
