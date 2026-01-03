"""
Diagnostic script to test RAG retrieval and fix vector search issue.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.rag import doc_processor
from src.ollama_client import ollama_client

print("=" * 70)
print("RAG DIAGNOSTIC TEST")
print("=" * 70)

# 1. Check database
print("\n1. DATABASE CHECK:")
print("-" * 40)
success, msg = db.initialize()
print(f"   Database: {msg}")
print(f"   Documents: {db.get_document_count()}")
print(f"   Chunks: {db.get_chunk_count()}")

# 2. Check embedding model
print("\n2. EMBEDDING MODEL CHECK:")
print("-" * 40)
embed_model = ollama_client.get_embedding_model()
print(f"   Model: {embed_model}")

if embed_model:
    success, test_embedding = ollama_client.generate_embedding(embed_model, "test")
    if success:
        print(f"   Test embedding: {len(test_embedding)} dimensions")
        print(f"   Sample values: {test_embedding[:5]}")
    else:
        print(f"   ERROR: Could not generate test embedding")
        sys.exit(1)
else:
    print("   ERROR: No embedding model available")
    sys.exit(1)

# 3. Test database vector search directly
print("\n3. DIRECT DATABASE SEARCH:")
print("-" * 40)

# Get a sample chunk from database
with db.get_connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT chunk_text, embedding 
            FROM document_chunks 
            WHERE embedding IS NOT NULL 
            LIMIT 1
        """)
        result = cursor.fetchone()
        
        if result:
            sample_text, sample_embedding = result
            print(f"   Sample chunk text: {sample_text[:50]}...")
            print(f"   Sample embedding type: {type(sample_embedding)}")
            print(f"   Sample embedding length: {len(sample_embedding) if sample_embedding else 0}")
            
            # Try to search using this embedding
            if sample_embedding:
                # Convert to list if needed
                if hasattr(sample_embedding, 'tolist'):
                    search_emb = sample_embedding.tolist()
                else:
                    search_emb = list(sample_embedding)
                
                print(f"\n   Testing search with sample embedding...")
                results = db.search_similar_chunks(search_emb, top_k=5)
                print(f"   Search returned: {len(results)} results")
                
                if results:
                    for i, (text, filename, idx, sim) in enumerate(results[:3]):
                        print(f"   Result {i+1}: {filename} (similarity: {sim:.3f})")
                else:
                    print("   WARNING: Search returned no results!")
                    
                    # Debug: Check what's in the database
                    cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
                    count = cursor.fetchone()[0]
                    print(f"   Chunks with embeddings: {count}")
                    
                    # Try raw SQL search
                    print("\n   Trying raw SQL search...")
                    embedding_str = db._embedding_to_pg_array(search_emb)
                    print(f"   Embedding format: {embedding_str[:100]}...")
                    
                    cursor.execute("""
                        SELECT chunk_text, 1 - (embedding <=> %s::vector) as similarity
                        FROM document_chunks
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT 5
                    """, (embedding_str, embedding_str))
                    
                    raw_results = cursor.fetchall()
                    print(f"   Raw SQL returned: {len(raw_results)} results")
                    
                    if raw_results:
                        for i, (text, sim) in enumerate(raw_results[:3]):
                            print(f"   Raw result {i+1}: {text[:50]}... (similarity: {sim:.3f})")
        else:
            print("   ERROR: No chunks with embeddings found in database")

# 4. Test RAG retrieval
print("\n4. RAG RETRIEVAL TEST:")
print("-" * 40)
test_query = "What is this document about?"
print(f"   Query: {test_query}")

results = doc_processor.retrieve_context(test_query, top_k=5)
print(f"   Results: {len(results)}")

if results:
    for i, (text, filename, idx, sim) in enumerate(results[:3]):
        print(f"   {i+1}. {filename} chunk {idx}: {sim:.3f}")
        print(f"      {text[:80]}...")
else:
    print("   ERROR: No results from RAG retrieval")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
