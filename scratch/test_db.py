import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indexing import RAGIndexManager

manager = RAGIndexManager(db_path="tests/temp_rag_storage.db")

print("=== Вміст таблиці chunks ===")
conn = sqlite3.connect(manager.db_path)
cursor = conn.cursor()
cursor.execute("SELECT id, file_path, heading, content FROM chunks")
for row in cursor.fetchall():
    print(row)
    
print("\n=== Вміст таблиці fts_chunks ===")
cursor.execute("SELECT * FROM fts_chunks")
for row in cursor.fetchall():
    print(row)
    
print("\n=== Вміст таблиці entities ===")
cursor.execute("SELECT * FROM entities")
for row in cursor.fetchall():
    print(row)

print("\n=== Вміст таблиці relationships ===")
cursor.execute("SELECT * FROM relationships")
for row in cursor.fetchall():
    print(row)

conn.close()

print("\n=== Тест пошуку ===")
query = "Хто є актуальним керівником проекту Alpha?"
print("Vector search results:")
print(manager.search_vector(query, limit=3))
print("\nBM25 search results:")
print(manager.search_bm25(query, limit=3))
print("\nHybrid RRF search results:")
print(manager.hybrid_search_rrf(query, limit=3))
