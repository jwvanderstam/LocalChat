#!/usr/bin/env python3
"""Add metadata column to document_chunks table."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.utils.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

def migrate():
    logger.info("Adding metadata column...")
    
    # Initialize database
    db.initialize()
    
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            # Add metadata column
            cursor.execute("""
                ALTER TABLE document_chunks 
                ADD COLUMN IF NOT EXISTS metadata JSONB 
                DEFAULT '{}'::jsonb;
            """)
            
            # Create GIN index for metadata queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS document_chunks_metadata_idx 
                ON document_chunks USING GIN (metadata);
            """)
            
            conn.commit()
    
    logger.info("Migration complete!")

if __name__ == '__main__':
    migrate()