"""
Debug vector similarity search.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.ollama_client import ollama_client

print("=" * 70)
print("DEBUG VECTOR SEARCH")
print("=" * 70)

# Initialize
db.initialize()

# Generate query embedding
embed_model = ollama_client.get_embedding_model()
success, query_emb = ollama_client.generate_embedding(embed_model, "test query")

if not success:
    print("Failed to generate embedding")
    sys.exit(1)

print(f"\n? Query embedding: {len(query_emb)} dimensions")

with db.get_connection() as conn:
    with conn.cursor() as cursor:
        # Convert to format
        emb_str = db._embedding_to_pg_array(query_emb)
        
        print("\n1. TESTING BASIC SELECT:")
        print("-" * 40)
        cursor.execute("""
            SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL
        """)
        count = cursor.fetchone()[0]
        print(f"Chunks with embeddings: {count}")
        
        print("\n2. TESTING SIMILARITY CALCULATION:")
        print("-" * 40)
        cursor.execute("""
            SELECT 
                id,
                chunk_text,
                (embedding <=> %s::vector) as distance,
                1 - (embedding <=> %s::vector) as similarity
            FROM document_chunks
            WHERE embedding IS NOT NULL
            LIMIT 3
        """, (emb_str, emb_str))
        
        results = cursor.fetchall()
        print(f"Got {len(results)} results")
        
        for chunk_id, text, distance, similarity in results:
            print(f"\n  Chunk {chunk_id}:")
            print(f"    Distance: {distance}")
            print(f"    Similarity: {similarity}")
            print(f"    Text: {text[:60]}...")
        
        print("\n3. TESTING ORDER BY:")
        print("-" * 40)
        cursor.execute("""
            SELECT 
                id,
                1 - (embedding <=> %s::vector) as similarity
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 5
        """, (emb_str, emb_str))
        
        results = cursor.fetchall()
        print(f"Ordered results: {len(results)}")
        
        for chunk_id, similarity in results:
            print(f"  Chunk {chunk_id}: similarity {similarity:.4f}")
        
        print("\n4. TESTING FULL QUERY (like db.search_similar_chunks):")
        print("-" * 40)
        cursor.execute("""
            SELECT 
                dc.chunk_text,
                d.filename,
                dc.chunk_index,
                1 - (dc.embedding <=> %s::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> %s::vector
            LIMIT 5
        """, (emb_str, emb_str))
        
        results = cursor.fetchall()
        print(f"Full query results: {len(results)}")
        
        if results:
            for text, filename, idx, similarity in results[:3]:
                print(f"\n  {filename} chunk {idx}:")
                print(f"    Similarity: {similarity:.4f}")
                print(f"    Text: {text[:60]}...")
        else:
            print("\n  ? No results!")
            
            # Debug: Check if JOIN is the issue
            print("\n5. DEBUGGING JOIN:")
            print("-" * 40)
            
            cursor.execute("SELECT COUNT(*) FROM documents")
            doc_count = cursor.fetchone()[0]
            print(f"  Documents table: {doc_count} rows")
            
            cursor.execute("SELECT COUNT(*) FROM document_chunks")
            chunk_count = cursor.fetchone()[0]
            print(f"  Chunks table: {chunk_count} rows")
            
            cursor.execute("""
                SELECT COUNT(*) 
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
            """)
            joined_count = cursor.fetchone()[0]
            print(f"  Successful joins: {joined_count} rows")
            
            if joined_count == 0:
                print("\n  ? JOIN is failing - no chunks linked to documents!")
                print("    This means document_id foreign keys are broken")
            elif joined_count < chunk_count:
                print(f"\n  ??  Some chunks not joined: {chunk_count - joined_count} orphaned")

print("\n" + "=" * 70)
