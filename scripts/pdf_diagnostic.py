"""
PDF Table Extraction Diagnostic Tool

This script helps diagnose why tables in your PDF might not be extracting properly.
It tests the actual extraction process and shows detailed information.

Usage:
    python pdf_diagnostic.py <path_to_your_pdf>
"""

import sys
import os

def diagnose_pdf(pdf_path):
    """Diagnose a PDF file for table extraction issues."""
    
    print("=" * 80)
    print(f"PDF TABLE EXTRACTION DIAGNOSTIC")
    print("=" * 80)
    print(f"\nPDF File: {pdf_path}\n")
    
    # Check if file exists
    if not os.path.exists(pdf_path):
        print(f"? ERROR: File not found: {pdf_path}")
        return
    
    file_size = os.path.getsize(pdf_path)
    print(f"? File exists: {file_size:,} bytes\n")
    
    # Test 1: Try with pdfplumber
    print("-" * 80)
    print("TEST 1: pdfplumber extraction (RECOMMENDED)")
    print("-" * 80)
    
    try:
        import pdfplumber
        print(f"? pdfplumber available (version {pdfplumber.__version__})")
        
        with pdfplumber.open(pdf_path) as pdf:
            num_pages = len(pdf.pages)
            print(f"? PDF opened successfully: {num_pages} page(s)\n")
            
            total_text_length = 0
            total_tables = 0
            
            for page_num, page in enumerate(pdf.pages):
                print(f"\n?? Page {page_num + 1}:")
                print("-" * 40)
                
                # Extract text
                page_text = page.extract_text()
                if page_text:
                    text_length = len(page_text)
                    total_text_length += text_length
                    print(f"   Text: {text_length} characters")
                    # Show first 100 chars
                    preview = page_text[:100].replace('\n', ' ')
                    print(f"   Preview: {preview}...")
                else:
                    print(f"   Text: None (empty page)")
                
                # Extract tables
                tables = page.extract_tables()
                if tables:
                    print(f"   ? Tables found: {len(tables)}")
                    total_tables += len(tables)
                    
                    for table_idx, table in enumerate(tables):
                        print(f"\n   ?? Table {table_idx + 1}:")
                        print(f"      Rows: {len(table)}")
                        if table:
                            print(f"      Columns: {len(table[0]) if table[0] else 0}")
                            
                            # Show first few rows
                            print(f"      Sample data:")
                            for row_idx, row in enumerate(table[:3]):
                                row_text = " | ".join([str(cell) if cell else "" for cell in row])
                                print(f"         Row {row_idx + 1}: {row_text[:80]}")
                            if len(table) > 3:
                                print(f"         ... ({len(table) - 3} more rows)")
                else:
                    print(f"   Tables: None")
            
            print("\n" + "=" * 80)
            print(f"SUMMARY:")
            print(f"  Total pages: {num_pages}")
            print(f"  Total text: {total_text_length:,} characters")
            print(f"  Total tables: {total_tables}")
            
            if total_tables > 0:
                print(f"\n??? TABLES DETECTED! Extraction should work!")
            else:
                print(f"\n?? NO TABLES DETECTED")
                print(f"   Possible reasons:")
                print(f"   1. PDF has no actual tables")
                print(f"   2. Tables are images (scanned)")
                print(f"   3. Tables use non-standard formatting")
                
    except ImportError:
        print("? pdfplumber not installed")
        print("   Install with: pip install pdfplumber==0.11.0")
    except Exception as e:
        print(f"? Error with pdfplumber: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Try with PyPDF2
    print("\n" + "-" * 80)
    print("TEST 2: PyPDF2 extraction (FALLBACK)")
    print("-" * 80)
    
    try:
        import PyPDF2
        print(f"? PyPDF2 available")
        
        with open(pdf_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            num_pages = len(pdf_reader.pages)
            print(f"? PDF opened: {num_pages} page(s)\n")
            
            total_text = ""
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    total_text += page_text
                    print(f"?? Page {page_num + 1}: {len(page_text)} characters")
            
            print(f"\nTotal extracted: {len(total_text):,} characters")
            if total_text:
                preview = total_text[:200].replace('\n', ' ')
                print(f"Preview: {preview}...")
            else:
                print("?? No text extracted with PyPDF2")
                
    except ImportError:
        print("? PyPDF2 not installed")
    except Exception as e:
        print(f"? Error with PyPDF2: {e}")
    
    # Test 3: Try through RAG module
    print("\n" + "-" * 80)
    print("TEST 3: LocalChat RAG module extraction")
    print("-" * 80)
    
    try:
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()
        
        print("? DocumentProcessor loaded")
        success, content = processor.load_pdf_file(pdf_path)
        
        if success:
            print(f"? Extraction successful!")
            print(f"   Content length: {len(content):,} characters")
            
            # Check for table markers
            table_count = content.count("[Table")
            if table_count > 0:
                print(f"   ? Table markers found: {table_count}")
            else:
                print(f"   ?? No table markers found")
            
            # Check for pipe separators
            pipe_count = content.count(" | ")
            if pipe_count > 0:
                print(f"   ? Pipe separators found: {pipe_count}")
            else:
                print(f"   ?? No pipe separators found")
            
            # Show sample
            print(f"\n   Sample content:")
            print("   " + "-" * 60)
            lines = content.split('\n')[:20]
            for line in lines:
                print(f"   {line[:70]}")
            print("   " + "-" * 60)
        else:
            print(f"? Extraction failed: {content}")
    except Exception as e:
        print(f"? Error with RAG module: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_diagnostic.py <path_to_pdf>")
        print("\nExample:")
        print("   python pdf_diagnostic.py my_document.pdf")
        print("   python pdf_diagnostic.py C:\\Documents\\report.pdf")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    diagnose_pdf(pdf_path)
