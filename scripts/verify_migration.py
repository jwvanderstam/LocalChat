#!/usr/bin/env python3
"""Verify migration."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db import db
from src.utils.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

db.initialize()

with db.get_connection() as conn:
    with conn.cursor() as cur:
        # Check column
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'document_chunks' 
            AND column_name = 'metadata'
        """)
        col = cur.fetchone()
        if col:
            logger.info(f"? Column exists: {col[0]} ({col[1]})")
        else:
            logger.error("? Column not found")
        
        # Check index
        cur.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'document_chunks' 
            AND indexname = 'document_chunks_metadata_idx'
        """)
        idx = cur.fetchone()
        if idx:
            logger.info(f"? Index exists: {idx[0]}")
        else:
            logger.error("? Index not found")

logger.info("? Verification complete!")
