"""
Quick test to verify pdfplumber table extraction is working.
"""

import os
import sys
import tempfile

# Test 1: Check if pdfplumber is installed
print("=" * 60)
print("TEST 1: Checking pdfplumber installation")
print("=" * 60)

try:
    import pdfplumber
    print(f"? pdfplumber installed: version {pdfplumber.__version__}")
except ImportError as e:
    print(f"? pdfplumber NOT installed: {e}")
    print("\nInstall with: pip install pdfplumber==0.11.0")
    sys.exit(1)

# Test 2: Check if rag.py can import it
print("\n" + "=" * 60)
print("TEST 2: Checking if rag.py can use pdfplumber")
print("=" * 60)

from src.rag import DocumentProcessor

processor = DocumentProcessor()

# Create a simple test to see what happens
print("\n? DocumentProcessor created successfully")

# Test 3: Check the load_pdf_file method
print("\n" + "=" * 60)
print("TEST 3: Testing PDF table extraction with real PDF")
print("=" * 60)

# Create a test PDF with pdfplumber (ironically)
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    # Create a simple PDF with a table
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
        test_pdf = f.name
        doc = SimpleDocTemplate(f.name, pagesize=letter)

        # Create table data
        data = [
            ['Name', 'Age', 'City'],
            ['Alice', '28', 'New York'],
            ['Bob', '35', 'Boston'],
            ['Charlie', '42', 'Chicago']
        ]

        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        # Build PDF
        story = [table]
        doc.build(story)

    print(f"? Test PDF created: {test_pdf}")

    # Now test extraction
    print("\n?? Testing PDF extraction...")
    success, content = processor.load_pdf_file(test_pdf)

    if success:
        print("? PDF extraction successful!")
        print(f"\nExtracted content ({len(content)} characters):")
        print("-" * 60)
        print(content[:500])
        print("-" * 60)

        # Check if table markers are present
        if "[Table" in content:
            print("\n??? TABLE EXTRACTION WORKING! Found table markers!")
        else:
            print("\n?? Table extraction may not be working - no table markers found")
            print("This might be because the test PDF is too simple")

        # Check if pipe separators are present
        if " | " in content:
            print("? Pipe separators found - table structure preserved!")
        else:
            print("?? No pipe separators - table might not have structure")
    else:
        print(f"? PDF extraction failed: {content}")

    # Cleanup
    os.unlink(test_pdf)
    print("\n?? Cleaned up test PDF")

except ImportError:
    print("?? reportlab not installed - skipping PDF creation test")
    print("   (This is OK - just can't create test PDFs automatically)")
    print("\n?? To test manually:")
    print("   1. Create a PDF with a table using Word/Excel")
    print("   2. Upload it through the web interface")
    print("   3. Check console logs for 'Found X table(s)' messages")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("? pdfplumber is installed and importable")
print("? rag.py can create DocumentProcessor")
print("? PDF extraction code is in place")
print("\n?? Next step: Upload a real PDF with tables and check logs!")
print("=" * 60)
