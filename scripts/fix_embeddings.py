"""
Fix script to clear database and prepare for re-upload.
The embeddings are currently stored as strings instead of vectors.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db

print("=" * 70)
print("DATABASE FIX SCRIPT")
print("=" * 70)

print("\nThis script will:")
print("1. Clear all existing documents and chunks")
print("2. Prepare database for re-upload with correct vector format")
print()

response = input("Are you sure you want to CLEAR ALL DOCUMENTS? (yes/no): ")

if response.lower() != 'yes':
    print("Aborted.")
    sys.exit(0)

print("\nClearing database...")

# Initialize database
success, msg = db.initialize()
if not success:
    print(f"Error: {msg}")
    sys.exit(1)

# Check current state
doc_count = db.get_document_count()
chunk_count = db.get_chunk_count()
print(f"Current state: {doc_count} documents, {chunk_count} chunks")

# Delete all
db.delete_all_documents()

# Verify
doc_count = db.get_document_count()
chunk_count = db.get_chunk_count()
print(f"After clearing: {doc_count} documents, {chunk_count} chunks")

print("\n? Database cleared successfully!")
print("\nNext steps:")
print("1. Restart your application: python app.py")
print("2. Go to http://localhost:5000/documents")
print("3. Re-upload your documents")
print("4. The embeddings will now be stored correctly")
print("5. Test retrieval should work after re-upload")

print("\n" + "=" * 70)
