import os
import unittest
import shutil
import sqlite3
from unittest.mock import MagicMock
from formatter import KnowledgeFormatter

class TestKnowledgeFormatter(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_rag_storage.db"
        self.test_vault = "test_obsidian_vault"
        self.test_raw_dir = "test_raw_inputs"
        
        # Створюємо тимчасові папки
        os.makedirs(self.test_vault, exist_ok=True)
        os.makedirs(self.test_raw_dir, exist_ok=True)
        
        # Ініціалізуємо тестову БД
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, file_path TEXT, heading TEXT, content TEXT, vector BLOB)")
        cursor.execute("INSERT OR REPLACE INTO entities (name, type) VALUES ('Apple Silicon', 'hardware')")
        cursor.execute("INSERT OR REPLACE INTO entities (name, type) VALUES ('RAG', 'technology')")
        cursor.execute("INSERT OR REPLACE INTO chunks (file_path, heading, content) VALUES ('note1.md', 'Вступ до RAG', 'Зміст RAG')")
        conn.commit()
        conn.close()
        
        # Створюємо існуючий файл в обсідіані
        with open(os.path.join(self.test_vault, "Існуюча Нотатка.md"), "w", encoding="utf-8") as f:
            f.write("# Існуюча Нотатка\nДеякий текст.")

    def tearDown(self):
        # Видаляємо тимчасові файли та папки
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        for folder in [self.test_vault, self.test_raw_dir]:
            if os.path.exists(folder):
                shutil.rmtree(folder)

    def test_load_existing_concepts(self):
        formatter = KnowledgeFormatter(db_path=self.test_db)
        concepts = formatter.load_existing_concepts(vault_dir=self.test_vault)
        
        # Перевіряємо, що зчитано сутності з бази даних та назви файлів з Vault
        self.assertIn("Apple Silicon", concepts)
        self.assertIn("RAG", concepts)
        self.assertIn("Вступ до RAG", concepts)
        self.assertIn("Існуюча Нотатка", concepts)

    def test_split_raw_text(self):
        formatter = KnowledgeFormatter(db_path=self.test_db)
        long_text = "Абзац 1\n\n" * 1000  # Дуже довгий текст
        parts = formatter.split_raw_text(long_text, max_chars=1000)
        
        self.assertTrue(len(parts) > 1)
        for part in parts:
            self.assertTrue(len(part) <= 1000)

    def test_process_raw_data(self):
        # Створюємо сирий текстовий файл
        raw_file = os.path.join(self.test_raw_dir, "raw_note.txt")
        raw_content = "Текст про RAG систему на базі Apple Silicon."
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write(raw_content)
            
        formatter = KnowledgeFormatter(db_path=self.test_db)
        
        # Мокаємо метод LLM, щоб не запускати реальний інференс під час тестів
        mocked_md = """---
tags: [test, hardware]
date: 2026-06-27
status: active
type: concept
---
## Тестова Нотатка
Детальний аналіз [[RAG]] на [[Apple Silicon]]."""
        formatter.llm_manager.generate_structured_note = MagicMock(return_value=mocked_md)
        
        # Запускаємо процес форматування
        success = formatter.process_raw_data(
            input_path=raw_file,
            vault_dir=self.test_vault,
            auto_ingest=False
        )
        
        self.assertTrue(success)
        
        # Перевіряємо створення файлу в обсідіані
        expected_md_file = os.path.join(self.test_vault, "raw_note.md")
        self.assertTrue(os.path.exists(expected_md_file))
        
        # Перевіряємо зміст файлу
        with open(expected_md_file, "r", encoding="utf-8") as f:
            saved_content = f.read()
        self.assertIn("tags: [test, hardware]", saved_content)
        self.assertIn("[[RAG]]", saved_content)
        self.assertIn("[[Apple Silicon]]", saved_content)
        
        # Перевіряємо, що сирий файл було перенесено в архів
        archive_file = os.path.join(self.test_raw_dir, ".archive", "raw_note.txt")
        self.assertTrue(os.path.exists(archive_file))
        self.assertFalse(os.path.exists(raw_file))

if __name__ == "__main__":
    unittest.main()
