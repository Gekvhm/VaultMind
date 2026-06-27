import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("1. Importing modules...")
from ingestion import DocumentIngester
from indexing import RAGIndexManager
from inference import LLMInferenceManager

print("2. Initializing DB...")
db_path = "tests/temp_rag_storage.db"
manager = RAGIndexManager(db_path=db_path)
manager.init_db()
print("DB initialized successfully.")

print("3. Ingesting docs...")
ingester = DocumentIngester(chunk_size=500, chunk_overlap=100)
ingested = ingester.process_directory("tests/temp_docs")
print(f"Ingested data keys: {ingested.keys()}")
print(f"Chunks count: {len(ingested['chunks'])}")
print(f"Entities count: {len(ingested['entities'])}")
print(f"Relations count: {len(ingested['relations'])}")

print("4. Inserting ingested data...")
manager.insert_ingested_data(ingested)
print("Data inserted successfully.")
