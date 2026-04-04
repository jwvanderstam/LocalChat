"""
Test the new PostgreSQL array format for vectors
"""
from src.db import db
from src.ollama_client import ollama_client

# Initialize
db.initialize()

# Test the conversion function
test_embedding = [1.5, 2.3, -0.5, 4.2, 0.0]
result = db._embedding_to_pg_array(test_embedding)
print(f"Test embedding: {test_embedding}")
print(f"PostgreSQL format: {result}")
print(f"Expected: {{1.5,2.3,-0.5,4.2,0.0}}")
print()

# Test with real embedding
embedding_model = ollama_client.get_embedding_model()
if embedding_model:
    success, embedding = ollama_client.generate_embedding(embedding_model, "test")
    if success:
        pg_format = db._embedding_to_pg_array(embedding)
        print(f"Real embedding dimension: {len(embedding)}")
        print(f"PostgreSQL format (first 100 chars): {pg_format[:100]}...")
        print(f"PostgreSQL format (last 20 chars): ...{pg_format[-20:]}")

db.close()
