"""
Project Restructuring Script
============================

This script helps migrate LocalChat to the new professional directory structure.

Usage:
    python restructure_project.py --dry-run    # Preview changes
    python restructure_project.py --execute    # Execute migration
    python restructure_project.py --verify     # Verify after migration

Author: LocalChat Team
Date: 2024-12-27
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Dict

class ProjectRestructurer:
    """Handles project restructuring operations."""
    
    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir).resolve()
        self.moves: List[Tuple[Path, Path]] = []
        self.creates: List[Path] = []
        
    def plan_migration(self) -> None:
        """Plan all file moves and directory creations."""
        print("=" * 80)
        print("PLANNING PROJECT RESTRUCTURING")
        print("=" * 80)
        
        # Phase 1: Create new directories
        print("\n?? Phase 1: Creating new directory structure...")
        self._plan_directories()
        
        # Phase 2: Move source code
        print("\n?? Phase 2: Planning source code moves...")
        self._plan_source_moves()
        
        # Phase 3: Organize tests
        print("\n?? Phase 3: Planning test organization...")
        self._plan_test_moves()
        
        # Phase 4: Organize documentation
        print("\n?? Phase 4: Planning documentation organization...")
        self._plan_doc_moves()
        
        # Phase 5: Organize scripts
        print("\n??? Phase 5: Planning script organization...")
        self._plan_script_moves()
        
        print("\n" + "=" * 80)
        print(f"PLAN SUMMARY")
        print("=" * 80)
        print(f"Directories to create: {len(self.creates)}")
        print(f"Files to move: {len(self.moves)}")
        
    def _plan_directories(self) -> None:
        """Plan directory creation."""
        dirs = [
            "src",
            "src/utils",
            "docs",
            "docs/testing",
            "docs/features",
            "docs/changelog",
            "docs/api",
            "scripts",
            "scripts/deployment",
            "tests/unit",
            "tests/integration",
            "tests/fixtures",
            "tests/utils",
            "static/css",
            "static/js",
            "static/images",
            ".github/workflows",
            "logs",
            "uploads"
        ]
        
        for d in dirs:
            path = self.root / d
            if not path.exists():
                self.creates.append(path)
                print(f"  + Create: {d}/")
    
    def _plan_source_moves(self) -> None:
        """Plan source code moves."""
        source_files = [
            ("app.py", "src/app.py"),
            ("config.py", "src/config.py"),
            ("db.py", "src/db.py"),
            ("rag.py", "src/rag.py"),
            ("ollama_client.py", "src/ollama_client.py"),
            ("exceptions.py", "src/exceptions.py"),
            ("models.py", "src/models.py"),
        ]
        
        for src, dst in source_files:
            src_path = self.root / src
            dst_path = self.root / dst
            if src_path.exists() and not dst_path.exists():
                self.moves.append((src_path, dst_path))
                print(f"  ? Move: {src} ? {dst}")
        
        # Move utils
        utils_files = [
            ("utils/logging_config.py", "src/utils/logging_config.py"),
            ("utils/sanitization.py", "src/utils/sanitization.py"),
        ]
        
        for src, dst in utils_files:
            src_path = self.root / src
            dst_path = self.root / dst
            if src_path.exists() and not dst_path.exists():
                self.moves.append((src_path, dst_path))
                print(f"  ? Move: {src} ? {dst}")
    
    def _plan_test_moves(self) -> None:
        """Plan test file moves."""
        # Move unit tests
        test_files = [
            "test_config.py",
            "test_db.py",
            "test_rag.py",
            "test_ollama_client.py",
            "test_exceptions.py",
            "test_models.py",
            "test_sanitization.py",
            "test_logging.py",
            "test_pdf_tables.py"
        ]
        
        tests_dir = self.root / "tests"
        if tests_dir.exists():
            for test_file in test_files:
                src_path = tests_dir / test_file
                dst_path = self.root / "tests" / "unit" / test_file
                if src_path.exists() and not dst_path.exists():
                    self.moves.append((src_path, dst_path))
                    print(f"  ? Move: tests/{test_file} ? tests/unit/{test_file}")
    
    def _plan_doc_moves(self) -> None:
        """Plan documentation moves."""
        doc_mapping = {
            # Testing docs
            "MONTH3_IMPLEMENTATION_PLAN.md": "docs/testing/IMPLEMENTATION_PLAN.md",
            "MONTH3_KICKOFF.md": "docs/testing/KICKOFF.md",
            "MONTH3_SETUP_COMPLETE.md": "docs/testing/SETUP_COMPLETE.md",
            "MONTH3_WEEK1_PROGRESS_REPORT.md": "docs/testing/WEEK1_REPORT.md",
            "MONTH3_WEEK2_PROGRESS_REPORT.md": "docs/testing/WEEK2_REPORT.md",
            "MONTH3_PROGRESS_SUMMARY.md": "docs/testing/PROGRESS_SUMMARY.md",
            "MONTH3_IMPLEMENTATION_COMPLETE.md": "docs/testing/COMPLETE.md",
            "MONTH3_COMPLETION_REPORT.md": "docs/testing/COMPLETION_REPORT.md",
            "MONTH3_TABLES_SUMMARY.md": "docs/testing/TABLES_SUMMARY.md",
            
            # Feature docs
            "RAG_FIX_SUMMARY.md": "docs/features/RAG_FIX.md",
            "RAG_OPTIMIZATION_GUIDE.md": "docs/features/RAG_OPTIMIZATION.md",
            "RAG_IMPROVEMENTS_IMPLEMENTED.md": "docs/features/RAG_IMPROVEMENTS.md",
            "RAG_QUALITY_IMPROVEMENTS.md": "docs/features/RAG_QUALITY.md",
            "RAG_HALLUCINATION_FIX.md": "docs/features/RAG_HALLUCINATION_FIX.md",
            "RAG_HALLUCINATION_FIXED.md": "docs/features/RAG_HALLUCINATION_FIXED.md",
            
            "PDF_TABLE_EXTRACTION_FIX.md": "docs/features/PDF_TABLE_EXTRACTION.md",
            "PDF_TABLE_FIX_QUICKGUIDE.md": "docs/features/PDF_TABLE_QUICKGUIDE.md",
            "PDF_TABLE_INGESTION_SUMMARY.md": "docs/features/PDF_TABLE_SUMMARY.md",
            "PDF_TABLE_TROUBLESHOOTING.md": "docs/features/PDF_TABLE_TROUBLESHOOTING.md",
            "PDF_TABLE_SUCCESS_GUIDE.md": "docs/features/PDF_TABLE_SUCCESS.md",
            
            "DUPLICATE_PREVENTION_REPORT.md": "docs/features/DUPLICATE_PREVENTION.md",
            
            # Main docs
            "COMPLETE_SETUP_SUMMARY.md": "docs/SETUP_GUIDE.md",
            "CODE_QUALITY_GUIDE.md": "docs/DEVELOPMENT.md",
            "README_NEW.md": "docs/README.md",
        }
        
        for src, dst in doc_mapping.items():
            src_path = self.root / src
            dst_path = self.root / dst
            if src_path.exists() and not dst_path.exists():
                self.moves.append((src_path, dst_path))
                print(f"  ? Move: {src} ? {dst}")
    
    def _plan_script_moves(self) -> None:
        """Plan script file moves."""
        scripts = [
            ("pdf_diagnostic.py", "scripts/pdf_diagnostic.py"),
            ("test_pdf_table_extraction.py", "scripts/test_pdf_extraction.py"),
            ("check_data.py", "scripts/check_data.py"),
        ]
        
        for src, dst in scripts:
            src_path = self.root / src
            dst_path = self.root / dst
            if src_path.exists() and not dst_path.exists():
                self.moves.append((src_path, dst_path))
                print(f"  ? Move: {src} ? {dst}")
    
    def execute_migration(self, dry_run: bool = True) -> None:
        """Execute the planned migration."""
        if dry_run:
            print("\n" + "=" * 80)
            print("DRY RUN MODE - No changes will be made")
            print("=" * 80)
            print("\nRun with --execute to actually perform migration")
            return
        
        print("\n" + "=" * 80)
        print("EXECUTING MIGRATION")
        print("=" * 80)
        
        # Create directories
        print("\n?? Creating directories...")
        for path in self.creates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                print(f"  ? Created: {path.relative_to(self.root)}")
            except Exception as e:
                print(f"  ? Failed to create {path}: {e}")
        
        # Create __init__.py files
        print("\n?? Creating __init__.py files...")
        init_dirs = [
            "src",
            "src/utils",
            "tests",
            "tests/unit",
            "tests/integration",
            "tests/utils",
        ]
        for d in init_dirs:
            init_file = self.root / d / "__init__.py"
            if not init_file.exists():
                init_file.touch()
                print(f"  ? Created: {init_file.relative_to(self.root)}")
        
        # Move files
        print("\n?? Moving files...")
        for src, dst in self.moves:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                print(f"  ? Moved: {src.relative_to(self.root)} ? {dst.relative_to(self.root)}")
            except Exception as e:
                print(f"  ? Failed to move {src}: {e}")
        
        print("\n? Migration completed!")
        print("\n??  IMPORTANT: You must now update imports in all Python files!")
        print("See RESTRUCTURING_GUIDE.md for details.")
    
    def verify_migration(self) -> None:
        """Verify the migration was successful."""
        print("=" * 80)
        print("VERIFYING MIGRATION")
        print("=" * 80)
        
        errors = []
        
        # Check critical directories exist
        print("\n?? Checking directories...")
        required_dirs = ["src", "docs", "scripts", "tests/unit"]
        for d in required_dirs:
            path = self.root / d
            if path.exists():
                print(f"  ? {d}")
            else:
                errors.append(f"Missing directory: {d}")
                print(f"  ? {d}")
        
        # Check critical files moved
        print("\n?? Checking source files...")
        required_files = ["src/app.py", "src/config.py", "src/db.py", "src/rag.py"]
        for f in required_files:
            path = self.root / f
            if path.exists():
                print(f"  ? {f}")
            else:
                errors.append(f"Missing file: {f}")
                print(f"  ? {f}")
        
        # Summary
        print("\n" + "=" * 80)
        if errors:
            print("? VERIFICATION FAILED")
            print("\nErrors found:")
            for error in errors:
                print(f"  - {error}")
        else:
            print("? VERIFICATION PASSED")
            print("\nMigration successful! Next steps:")
            print("1. Update imports in Python files")
            print("2. Update pytest.ini and .coveragerc")
            print("3. Run tests to verify")
            print("4. Update README.md")
        print("=" * 80)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Restructure LocalChat project")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--execute", action="store_true", help="Execute migration")
    parser.add_argument("--verify", action="store_true", help="Verify migration")
    args = parser.parse_args()
    
    restructurer = ProjectRestructurer()
    
    if args.verify:
        restructurer.verify_migration()
    else:
        restructurer.plan_migration()
        
        if args.execute:
            response = input("\n??  This will move files. Continue? (yes/no): ")
            if response.lower() == "yes":
                restructurer.execute_migration(dry_run=False)
            else:
                print("Migration cancelled.")
        else:
            restructurer.execute_migration(dry_run=True)


if __name__ == "__main__":
    main()
