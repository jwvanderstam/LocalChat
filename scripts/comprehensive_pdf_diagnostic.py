# -*- coding: utf-8 -*-
"""
Comprehensive PDF Diagnostic Tool - Enhanced Version

Diagnoses PDF extraction issues including:
- Text extraction completeness
- Table detection accuracy
- Page-by-page analysis
- Extraction method comparison
- Quality assessment

Usage:
    python scripts/comprehensive_pdf_diagnostic.py <path_to_pdf>
"""

import sys
import os

def diagnose_pdf_comprehensive(pdf_path):
    """Comprehensive PDF diagnostics with detailed analysis."""
    
    print("=" * 100)
    print(f"COMPREHENSIVE PDF EXTRACTION DIAGNOSTIC")
    print("=" * 100)
    print(f"\nPDF File: {pdf_path}\n")
    
    # Check file exists
    if not os.path.exists(pdf_path):
        print(f"ERROR: File not found: {pdf_path}")
        return
    
    file_size = os.path.getsize(pdf_path)
    print(f"File exists: {file_size:,} bytes ({file_size/1024:.1f} KB)\n")
    
    # Test 1: pdfplumber (RECOMMENDED)
    print("=" * 100)
    print("TEST 1: PDFPLUMBER EXTRACTION (RECOMMENDED FOR TABLES)")
    print("=" * 100)
    
    pdfplumber_text = ""
    pdfplumber_tables = []
    pdfplumber_success = False
    
    try:
        import pdfplumber
        print(f"pdfplumber version: {pdfplumber.__version__}")
        
        with pdfplumber.open(pdf_path) as pdf:
            num_pages = len(pdf.pages)
            print(f"PDF opened: {num_pages} pages\n")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"\n{'='*60}")
                print(f"PAGE {page_num} of {num_pages}")
                print(f"{'='*60}")
                
                # Extract text
                try:
                    page_text = page.extract_text()
                    if page_text:
                        pdfplumber_text += page_text + "\n"
                        print(f"Text extracted: {len(page_text):,} characters")
                        # Show preview
                        preview = page_text[:200].replace('\n', ' ')
                        print(f"  Preview: {preview}...")
                    else:
                        print(f"No text extracted from this page")
                except Exception as e:
                    print(f"Text extraction error: {e}")
                
                # Extract tables
                try:
                    tables = page.extract_tables()
                    if tables:
                        print(f"\nTABLES FOUND: {len(tables)} table(s)")
                        for table_idx, table in enumerate(tables, 1):
                            pdfplumber_tables.append((page_num, table_idx, table))
                            
                            if not table:
                                print(f"   Table {table_idx}: Empty")
                                continue
                            
                            rows = len(table)
                            cols = len(table[0]) if table and table[0] else 0
                            print(f"\n   Table {table_idx}:")
                            print(f"      Dimensions: {rows} rows x {cols} columns")
                            
                            # Show sample data
                            print(f"      Sample data (first 3 rows):")
                            for row_idx, row in enumerate(table[:3], 1):
                                row_text = " | ".join([str(cell)[:30] if cell else "[empty]" for cell in row])
                                print(f"         {row_idx}. {row_text}")
                            
                            if rows > 3:
                                print(f"         ... ({rows - 3} more rows)")
                            
                            # Count non-empty cells
                            non_empty = sum(1 for row in table for cell in row if cell and str(cell).strip())
                            total_cells = rows * cols
                            fill_rate = (non_empty / total_cells * 100) if total_cells > 0 else 0
                            print(f"      Fill rate: {non_empty}/{total_cells} cells ({fill_rate:.1f}%)")
                    else:
                        print(f"  No tables detected on this page")
                except Exception as e:
                    print(f"Table extraction error: {e}")
        
        pdfplumber_success = True
        
        print(f"\n{'='*100}")
        print(f"PDFPLUMBER SUMMARY")
        print(f"{'='*100}")
        print(f"Total pages processed: {num_pages}")
        print(f"Total text extracted: {len(pdfplumber_text):,} characters")
        print(f"Total tables found: {len(pdfplumber_tables)}")
        
        if pdfplumber_tables:
            print(f"\nTABLE DETECTION SUCCESSFUL!")
            print(f"   Tables by page:")
            from collections import Counter
            page_counts = Counter(page for page, _, _ in pdfplumber_tables)
            for page, count in sorted(page_counts.items()):
                print(f"      Page {page}: {count} table(s)")
        else:
            print(f"\nNO TABLES DETECTED")
            print(f"   Possible reasons:")
            print(f"   1. PDF has no tables")
            print(f"   2. Tables are images (scanned document)")
            print(f"   3. Tables use non-standard formatting")
        
        # Quality assessment
        print(f"\nQuality Assessment:")
        if len(pdfplumber_text) < 100:
            print(f"   POOR: Very little text extracted ({len(pdfplumber_text)} chars)")
        elif len(pdfplumber_text) < 1000:
            print(f"   FAIR: Limited text extracted ({len(pdfplumber_text):,} chars)")
        elif len(pdfplumber_text) < 10000:
            print(f"   GOOD: Moderate text extracted ({len(pdfplumber_text):,} chars)")
        else:
            print(f"   EXCELLENT: Substantial text extracted ({len(pdfplumber_text):,} chars)")
        
    except ImportError:
        print("pdfplumber not installed")
        print("   Install: pip install pdfplumber==0.11.0")
    except Exception as e:
        print(f"pdfplumber error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: PyPDF2 (FALLBACK)
    print(f"\n{'='*100}")
    print("TEST 2: PyPDF2 EXTRACTION (FALLBACK METHOD)")
    print("=" * 100)
    
    pypdf2_text = ""
    
    try:
        import PyPDF2
        print(f"PyPDF2 available")
        
        with open(pdf_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            num_pages = len(pdf_reader.pages)
            print(f"PDF opened: {num_pages} pages\n")
            
            for page_num, page in enumerate(pdf_reader.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        pypdf2_text += page_text + "\n"
                        print(f"   Page {page_num}: {len(page_text):,} characters")
                    else:
                        print(f"   Page {page_num}: No text")
                except Exception as e:
                    print(f"   Page {page_num}: Error: {e}")
        
        print(f"\nPyPDF2 Summary:")
        print(f"   Total extracted: {len(pypdf2_text):,} characters")
        
        if pypdf2_text:
            preview = pypdf2_text[:200].replace('\n', ' ')
            print(f"   Preview: {preview}...")
        
    except ImportError:
        print("PyPDF2 not installed")
    except Exception as e:
        print(f"PyPDF2 error: {e}")
    
    # Comparison
    if pdfplumber_success and pypdf2_text:
        print(f"\n{'='*100}")
        print("COMPARISON")
        print("=" * 100)
        print(f"pdfplumber: {len(pdfplumber_text):,} characters")
        print(f"PyPDF2:     {len(pypdf2_text):,} characters")
        
        diff = len(pdfplumber_text) - len(pypdf2_text)
        if abs(diff) < 100:
            print(f"Difference: ~{abs(diff)} characters (Similar)")
        else:
            print(f"Difference: {diff:+,} characters")
            if diff > 0:
                print(f"   pdfplumber extracted MORE text (better)")
            else:
                print(f"   PyPDF2 extracted more text (unusual)")
    
    # Test 3: LocalChat RAG module
    print(f"\n{'='*100}")
    print("TEST 3: LOCALCHAT RAG MODULE")
    print("=" * 100)
    
    try:
        # Add parent directory to path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        from src.rag import DocumentProcessor
        processor = DocumentProcessor()
        
        print("DocumentProcessor loaded")
        success, content = processor.load_pdf_file(pdf_path)
        
        if success:
            print(f"Extraction successful!")
            print(f"   Content length: {len(content):,} characters")
            
            # Check for table markers
            table_count = content.count("[Table")
            if table_count > 0:
                print(f"   Table markers found: {table_count}")
            else:
                print(f"   No table markers found")
            
            # Check for pipe separators
            pipe_count = content.count(" | ")
            if pipe_count > 0:
                print(f"   Pipe separators found: {pipe_count}")
            else:
                print(f"   No pipe separators found")
            
            # Show sample
            print(f"\n   Sample content (first 20 lines):")
            print("   " + "-" * 90)
            lines = content.split('\n')[:20]
            for line in lines:
                print(f"   {line[:87]}")
            if len(content.split('\n')) > 20:
                print(f"   ... ({len(content.split('\n')) - 20} more lines)")
            print("   " + "-" * 90)
            
            # Compare with pdfplumber
            if pdfplumber_success:
                rag_length = len(content)
                plumber_length = len(pdfplumber_text)
                diff = abs(rag_length - plumber_length)
                
                print(f"\n   Comparison with pdfplumber:")
                print(f"      RAG module:  {rag_length:,} chars")
                print(f"      pdfplumber:  {plumber_length:,} chars")
                if diff < 100:
                    print(f"      Nearly identical (diff: {diff} chars)")
                elif rag_length < plumber_length * 0.5:
                    print(f"      RAG extracted MUCH LESS than expected")
                elif rag_length > plumber_length * 0.9:
                    print(f"      RAG extracted most of the content")
                else:
                    print(f"      RAG extracted less content (investigating needed)")
        else:
            print(f"Extraction failed: {content}")
    except Exception as e:
        print(f"RAG module error: {e}")
        import traceback
        traceback.print_exc()
    
    # Final diagnosis
    print(f"\n{'='*100}")
    print("FINAL DIAGNOSIS")
    print("=" * 100)
    
    if pdfplumber_success:
        total_chars = len(pdfplumber_text)
        total_tables = len(pdfplumber_tables)
        
        print(f"\nPDF is readable with pdfplumber")
        print(f"   - Text content: {total_chars:,} characters")
        print(f"   - Tables found: {total_tables}")
        
        if total_chars < 1000:
            print(f"\nWARNING: Limited text extracted")
            print(f"   Possible causes:")
            print(f"   1. PDF has little content")
            print(f"   2. PDF is mostly images")
            print(f"   3. PDF uses complex fonts/encoding")
            print(f"\n   Recommendation: Check if PDF is text-based or scanned")
        
        if total_tables == 0:
            print(f"\nNO TABLES DETECTED")
            print(f"   If you expect tables:")
            print(f"   1. Check if tables are images (scanned)")
            print(f"   2. Verify table structure in PDF")
            print(f"   3. Tables might use non-standard formatting")
        elif total_tables < 3:
            print(f"\nFew tables detected ({total_tables})")
            print(f"   If you expect more:")
            print(f"   1. Some tables might be images")
            print(f"   2. Tables might be formatted as aligned text")
        else:
            print(f"\nMultiple tables detected ({total_tables})")
            print(f"   Table extraction should work well!")
    else:
        print(f"\npdfplumber extraction failed or not available")
        print(f"   Recommendation: Install pdfplumber")
        print(f"   Command: pip install pdfplumber==0.11.0")
    
    print(f"\n{'='*100}")
    print("DIAGNOSTIC COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python comprehensive_pdf_diagnostic.py <path_to_pdf>")
        print("\nExample:")
        print("   python scripts/comprehensive_pdf_diagnostic.py document.pdf")
        print("   python scripts/comprehensive_pdf_diagnostic.py C:\\Documents\\report.pdf")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    diagnose_pdf_comprehensive(pdf_path)
