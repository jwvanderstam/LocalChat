"""
Debug vector search
"""
from src.db import db
from src.ollama_client import ollama_client

# Initialize
db.initialize()

# Get an embedding
embedding_model = ollama_client.get_embedding_model()
success, query_embedding = ollama_client.generate_embedding(embedding_model, "test")

if success:
    print(f"Generated embedding with {len(query_embedding)} dimensions")
    
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Check dimensions of stored embeddings
            cursor.execute("SELECT array_length(embedding::real[], 1) FROM document_chunks LIMIT 1")
            stored_dim = cursor.fetchone()
            print(f"Stored embedding dimension: {stored_dim}")
            
            # Try simple search without join
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            try:
                print("\nTesting simple vector search...")
                cursor.execute("""
                    SELECT 
                        chunk_text,
                        document_id,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM document_chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT 3
                """, (embedding_str, embedding_str))
                
                results = cursor.fetchall()
                print(f"Simple search returned {len(results)} results")
                for text, doc_id, sim in results:
                    print(f"  Doc {doc_id}: similarity {sim:.4f}, text: {text[:50]}...")
                    
            except Exception as e:
                print(f"ERROR: {e}")
                import traceback
                traceback.print_exc()

db.close()
