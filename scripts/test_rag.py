"""
Test script to verify RAG functionality
"""
from src.db import db
from src.ollama_client import ollama_client
from src.rag import doc_processor

print("=" * 60)
print("RAG SYSTEM TEST")
print("=" * 60)

# 1. Test database connection
print("\n1. Testing database connection...")
success, message = db.initialize()
print(f"   Result: {message}")

if success:
    doc_count = db.get_document_count()
    chunk_count = db.get_chunk_count()
    print(f"   Documents: {doc_count}")
    print(f"   Chunks: {chunk_count}")
else:
    print("   ERROR: Database not available")
    exit(1)

# 2. Test Ollama connection
print("\n2. Testing Ollama connection...")
success, message = ollama_client.check_connection()
print(f"   Result: {message}")

if success:
    embedding_model = ollama_client.get_embedding_model()
    print(f"   Embedding model: {embedding_model}")
else:
    print("   ERROR: Ollama not available")
    exit(1)

# 3. Test embedding generation
print("\n3. Testing embedding generation...")
test_text = "This is a test sentence for embedding."
success, embedding = ollama_client.generate_embedding(embedding_model, test_text)
if success:
    print(f"   Generated embedding with dimension: {len(embedding)}")
    print(f"   First 5 values: {embedding[:5]}")
else:
    print("   ERROR: Failed to generate embedding")
    exit(1)

# 4. Test document retrieval
print("\n4. Testing document retrieval...")
if chunk_count > 0:
    test_query = "What is this document about?"
    print(f"   Query: {test_query}")

    results = doc_processor.retrieve_context(test_query, top_k=3)
    print(f"   Retrieved {len(results)} chunks")

    if results:
        for i, (chunk_text, filename, chunk_index, similarity) in enumerate(results):
            print(f"\n   Result {i+1}:")
            print(f"   - File: {filename}")
            print(f"   - Chunk: {chunk_index}")
            print(f"   - Similarity: {similarity:.4f}")
            print(f"   - Text preview: {chunk_text[:100]}...")
    else:
        print("   ERROR: No results returned from retrieval")
else:
    print("   Skipped: No documents in database")

# 5. Test complete RAG pipeline
print("\n5. Testing complete RAG pipeline with test_retrieval...")
if chunk_count > 0:
    success, results = doc_processor.test_retrieval("test query")
    if success:
        print(f"   Success! Retrieved {len(results)} results")
        for i, result in enumerate(results):
            print(f"   Result {i+1}: {result['filename']} (similarity: {result['similarity']:.4f})")
    else:
        print(f"   ERROR: {results}")
else:
    print("   Skipped: No documents in database")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)

# Clean up
db.close()
