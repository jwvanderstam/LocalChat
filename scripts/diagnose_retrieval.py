"""
Diagnostic script for retrieval issues.
Checks database, embeddings, and retrieval pipeline.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.ollama_client import ollama_client
from src.rag import doc_processor

print("=" * 70)
print("RETRIEVAL DIAGNOSTIC TOOL")
print("=" * 70)

# 1. Database check
print("\n1. DATABASE STATUS:")
print("-" * 40)
success, msg = db.initialize()
print(f"Connection: {msg}")
doc_count = db.get_document_count()
chunk_count = db.get_chunk_count()
print(f"Documents: {doc_count}")
print(f"Chunks: {chunk_count}")

# 2. Check chunks have embeddings
print("\n2. EMBEDDING CHECK:")
print("-" * 40)
if chunk_count > 0:
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Check how many chunks have embeddings
            cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
            embedded_count = cursor.fetchone()[0]
            print(f"Chunks with embeddings: {embedded_count}/{chunk_count}")
            
            if embedded_count > 0:
                # Get a sample embedding
                cursor.execute("SELECT embedding, chunk_text FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1")
                result = cursor.fetchone()
                if result:
                    embedding, text = result
                    print(f"\nSample chunk: {text[:80]}...")
                    print(f"Embedding type: {type(embedding)}")
                    print(f"Embedding dimensions: {len(embedding) if embedding else 0}")
                    
                    # Check if it's a pgvector type
                    if hasattr(embedding, '__iter__'):
                        print(f"First 5 values: {list(embedding)[:5]}")
            else:
                print("\n??  WARNING: No chunks have embeddings!")
                print("   This is why retrieval returns 0 results.")
                print("   Solution: Re-upload documents to generate embeddings.")
else:
    print("\n??  WARNING: No chunks in database!")
    print("   Upload documents first.")
    sys.exit(0)

# 3. Check embedding model
print("\n3. EMBEDDING MODEL CHECK:")
print("-" * 40)
embed_model = ollama_client.get_embedding_model()
print(f"Model: {embed_model}")

if embed_model:
    # Test embedding generation
    test_text = "test query"
    success, test_embedding = ollama_client.generate_embedding(embed_model, test_text)
    
    if success:
        print(f"? Test embedding generated")
        print(f"  Dimensions: {len(test_embedding)}")
        print(f"  First 5 values: {test_embedding[:5]}")
    else:
        print(f"? Failed to generate test embedding")
        sys.exit(1)
else:
    print("? No embedding model available")
    sys.exit(1)

# 4. Test direct database search
print("\n4. DIRECT VECTOR SEARCH TEST:")
print("-" * 40)
if embedded_count > 0:
    # Generate an embedding for a simple query
    query = "What is this about?"
    print(f"Query: '{query}'")
    
    success, query_emb = ollama_client.generate_embedding(embed_model, query)
    
    if success:
        print(f"? Query embedding generated ({len(query_emb)} dims)")
        
        # Search database directly
        results = db.search_similar_chunks(query_emb, top_k=10)
        print(f"\n  Database returned: {len(results)} results")
        
        if results:
            print("\n  Top 3 results:")
            for i, (text, filename, idx, similarity) in enumerate(results[:3], 1):
                print(f"  {i}. {filename} chunk {idx}")
                print(f"     Similarity: {similarity:.4f}")
                print(f"     Text: {text[:60]}...")
        else:
            print("\n  ??  No results from database search!")
            print("  Possible causes:")
            print("  1. Embeddings were generated with different model")
            print("  2. Embedding dimensions don't match")
            print("  3. Database index issue")
    else:
        print(f"? Failed to generate query embedding")

# 5. Test RAG retrieval
print("\n5. RAG RETRIEVAL TEST:")
print("-" * 40)
results = doc_processor.retrieve_context(query, top_k=10, min_similarity=0.0)
print(f"Results (no threshold): {len(results)}")

if results:
    print("\nTop 3 results:")
    for i, (text, filename, idx, similarity) in enumerate(results[:3], 1):
        print(f"{i}. {filename} chunk {idx}: {similarity:.4f}")
else:
    print("??  No results from RAG retrieval")

# 6. Recommendations
print("\n6. RECOMMENDATIONS:")
print("-" * 40)

if embedded_count == 0:
    print("? CRITICAL: No embeddings in database")
    print("   Solution: Re-upload documents to generate embeddings")
    print("   Steps:")
    print("   1. Go to /documents page")
    print("   2. Upload your documents")
    print("   3. Wait for processing")
    print("   4. Run this diagnostic again")
elif len(results) == 0:
    print("? ISSUE: Embeddings exist but retrieval returns nothing")
    print("   Possible solutions:")
    print("   1. Check if embedding model matches ingestion model")
    print("   2. Try lowering MIN_SIMILARITY_THRESHOLD to 0.0")
    print("   3. Re-index documents with current model")
else:
    print("? Retrieval is working!")
    print(f"  Found {len(results)} results")
    if results[0][3] < 0.3:
        print("  ??  Low similarity scores detected")
        print("     Consider lowering MIN_SIMILARITY_THRESHOLD")

print("\n" + "=" * 70)
