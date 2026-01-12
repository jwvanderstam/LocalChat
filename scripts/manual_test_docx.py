"""
Test DOCX ingestion for Astrid Nientker CV
"""
import os
from src.rag import doc_processor
from pathlib import Path

# Find the document
doc_name = "Astrid Nientker_CV_NL_2025_12.docx"
upload_folder = "uploads"

# Check if file exists
file_path = os.path.join(upload_folder, doc_name)

if not os.path.exists(file_path):
    print(f"ERROR: File not found: {file_path}")
    print(f"Current directory: {os.getcwd()}")
    print(f"Files in uploads folder:")
    if os.path.exists(upload_folder):
        for f in os.listdir(upload_folder):
            print(f"  - {f}")
    else:
        print(f"  Upload folder doesn't exist")
    exit(1)

print(f"Testing DOCX ingestion for: {doc_name}")
print(f"File path: {file_path}")
print(f"File size: {os.path.getsize(file_path)} bytes")
print("=" * 60)

# Test 1: Load document
print("\n1. Testing document loading...")
success, content = doc_processor.load_docx_file(file_path)

if not success:
    print(f"   FAILED: {content}")
    exit(1)
else:
    print(f"   SUCCESS: Loaded {len(content)} characters")
    print(f"   First 200 chars: {content[:200]}")
    print(f"   Last 200 chars: {content[-200:]}")

# Test 2: Check content validity
print("\n2. Checking content validity...")
if not content or len(content.strip()) == 0:
    print("   ERROR: Document is empty")
    exit(1)
else:
    print(f"   Content length: {len(content)} characters")
    print(f"   Non-whitespace: {len(content.strip())} characters")

# Test 3: Test chunking
print("\n3. Testing chunking...")
chunks = doc_processor.chunk_text(content)
print(f"   Generated {len(chunks)} chunks")
if len(chunks) > 0:
    print(f"   First chunk ({len(chunks[0])} chars): {chunks[0][:100]}...")
    if len(chunks) > 1:
        print(f"   Last chunk ({len(chunks[-1])} chars): {chunks[-1][:100]}...")

# Test 4: Full ingestion test
print("\n4. Testing full ingestion...")

def progress_callback(msg):
    print(f"   {msg}")

success, message, doc_id = doc_processor.ingest_document(file_path, progress_callback)

if success:
    print(f"\n   SUCCESS: {message}")
    print(f"   Document ID: {doc_id}")
else:
    print(f"\n   FAILED: {message}")

print("\n" + "=" * 60)
print("Test complete")
