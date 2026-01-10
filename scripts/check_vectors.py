"""
Check vector storage in database.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.ollama_client import ollama_client

print("=" * 70)
print("VECTOR STORAGE CHECK")
print("=" * 70)

# Initialize
db.initialize()

print("\n1. CHECKING CHUNKS IN DATABASE:")
print("-" * 40)

with db.get_connection() as conn:
    with conn.cursor() as cursor:
        # Total chunks
        cursor.execute("SELECT COUNT(*) FROM document_chunks")
        total = cursor.fetchone()[0]
        print(f"Total chunks: {total}")
        
        # Chunks with embeddings
        cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
        with_embeddings = cursor.fetchone()[0]
        print(f"Chunks with embeddings: {with_embeddings}")
        
        if with_embeddings > 0:
            # Get a sample
            cursor.execute("""
                SELECT 
                    id,
                    chunk_text,
                    embedding,
                    pg_typeof(embedding) as emb_type
                FROM document_chunks 
                WHERE embedding IS NOT NULL 
                LIMIT 1
            """)
            result = cursor.fetchone()
            
            if result:
                chunk_id, text, embedding, emb_type = result
                print(f"\nSample chunk ID: {chunk_id}")
                print(f"Text preview: {text[:60]}...")
                print(f"Embedding PostgreSQL type: {emb_type}")
                print(f"Embedding Python type: {type(embedding)}")
                
                # Check if it's actually a vector
                if emb_type == 'vector':
                    print("? Embeddings are stored as proper vectors!")
                    
                    # Try to convert to list
                    if hasattr(embedding, '__iter__'):
                        emb_list = list(embedding)
                        print(f"? Embedding dimensions: {len(emb_list)}")
                        print(f"? First 5 values: {emb_list[:5]}")
                    else:
                        print(f"? Cannot iterate over embedding")
                else:
                    print(f"? WARNING: Embeddings stored as '{emb_type}', not 'vector'!")

print("\n2. TESTING VECTOR SEARCH:")
print("-" * 40)

# Generate test query embedding
embed_model = ollama_client.get_embedding_model()
print(f"Embedding model: {embed_model}")

success, query_emb = ollama_client.generate_embedding(embed_model, "test query")
if success:
    print(f"? Generated query embedding: {len(query_emb)} dimensions")
    
    # Try direct SQL search
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Convert to pgvector format
            emb_str = db._embedding_to_pg_array(query_emb)
            print(f"\nQuery embedding format: {emb_str[:100]}...")
            
            # Try search
            print("\nExecuting vector similarity search...")
            try:
                cursor.execute("""
                    SELECT 
                        chunk_text,
                        1 - (embedding <=> %s::vector) as similarity,
                        pg_typeof(embedding) as emb_type
                    FROM document_chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT 5
                """, (emb_str, emb_str))
                
                results = cursor.fetchall()
                print(f"? Search returned {len(results)} results")
                
                if results:
                    for i, (text, sim, emb_type) in enumerate(results[:3], 1):
                        print(f"\n  Result {i}:")
                        print(f"    Similarity: {sim:.4f}")
                        print(f"    Type: {emb_type}")
                        print(f"    Text: {text[:60]}...")
                else:
                    print("\n? No results from search!")
                    print("  This might indicate:")
                    print("  1. All similarity scores are 0 or NaN")
                    print("  2. Embedding dimension mismatch")
                    print("  3. Corrupt vector data")
                    
            except Exception as e:
                print(f"? Search failed with error: {e}")
                import traceback
                traceback.print_exc()
else:
    print("? Failed to generate query embedding")

print("\n3. CHECKING FOR NULLS OR INVALID VECTORS:")
print("-" * 40)

with db.get_connection() as conn:
    with conn.cursor() as cursor:
        # Check for NULL embeddings
        cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL")
        null_count = cursor.fetchone()[0]
        print(f"Chunks with NULL embedding: {null_count}")
        
        # Check embedding dimensions
        cursor.execute("""
            SELECT 
                id,
                array_length(embedding::real[], 1) as dims
            FROM document_chunks 
            WHERE embedding IS NOT NULL
            LIMIT 5
        """)
        
        print("\nSample embedding dimensions:")
        for chunk_id, dims in cursor.fetchall():
            status = "?" if dims == 768 else "?"
            print(f"  Chunk {chunk_id}: {dims} dimensions {status}")

print("\n" + "=" * 70)
print("DIAGNOSIS COMPLETE")
print("=" * 70)
