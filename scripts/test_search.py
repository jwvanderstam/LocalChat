"""
Test database search directly
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

    # Test the search
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # First, check what's in the table
            cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
            count = cursor.fetchone()[0]
            print(f"Chunks with embeddings: {count}")

            # Try the actual search query
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

            try:
                cursor.execute("""
                    SELECT
                        dc.chunk_text,
                        d.filename,
                        dc.chunk_index,
                        1 - (dc.embedding <=> %s::vector) as similarity
                    FROM document_chunks dc
                    JOIN documents d ON dc.document_id = d.id
                    ORDER BY dc.embedding <=> %s::vector
                    LIMIT 3
                """, (embedding_str, embedding_str))

                results = cursor.fetchall()
                print(f"\nSearch returned {len(results)} results:")
                for i, (text, filename, idx, sim) in enumerate(results):
                    print(f"{i+1}. {filename} chunk {idx}: similarity {sim:.4f}")
                    print(f"   Text: {text[:100]}...")

            except Exception as e:
                print(f"Search error: {e}")
                import traceback
                traceback.print_exc()

db.close()
