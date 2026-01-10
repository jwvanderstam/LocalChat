-- PostgreSQL Database Setup for LocalChat RAG Application
-- Run this script to set up the database and pgvector extension

-- Connect to PostgreSQL as superuser (e.g., postgres)
-- psql -U postgres

-- Create the database (if it doesn't exist)
-- Note: The application will attempt to create this automatically
CREATE DATABASE rag_db;

-- Connect to the new database
\c rag_db

-- Create the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create documents table
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    content TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create document_chunks table with vector embeddings
-- The embedding dimension is 768 (standard for many embedding models)
-- Adjust if your model uses a different dimension
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for vector similarity search using IVFFlat
-- This provides fast approximate nearest neighbor search
-- Lists parameter controls the number of clusters (tune based on data size)
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx 
ON document_chunks USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Optional: Create additional indexes for faster queries
CREATE INDEX IF NOT EXISTS documents_created_at_idx ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx ON document_chunks(document_id);

-- Grant necessary permissions
-- Replace 'your_user' with your PostgreSQL username if different
GRANT ALL PRIVILEGES ON DATABASE rag_db TO postgres;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Display created tables
\dt

-- Display pgvector extension
\dx vector

-- Show some basic stats
SELECT 
    'documents' as table_name, 
    COUNT(*) as row_count 
FROM documents
UNION ALL
SELECT 
    'document_chunks' as table_name, 
    COUNT(*) as row_count 
FROM document_chunks;

-- Done!
-- The database is now ready for the LocalChat application
