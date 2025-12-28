from src.db import db

db.initialize()

with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT id, LEFT(chunk_text, 30), embedding IS NOT NULL FROM document_chunks")
    rows = cursor.fetchall()
    for r in rows:
        print(r)
    conn.commit()

db.close()
