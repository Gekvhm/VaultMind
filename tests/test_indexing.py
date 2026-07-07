"""Тести для модуля indexing.py — RAGIndexManager.

Покриття:
  - init_db: створення таблиць, ідемпотентність
  - insert_ingested_data: сутності, зв'язки, чанки (з мокнутими ембедінгами)
  - search_bm25: пошук за ключовим словом, порожній запит, відсутність збігів
  - get_query_entities: знаходження сутностей, регістронезалежність, фільтр коротких імен
  - hybrid_search_rrf: злиття RRF, графове підсилення
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Додаємо кореневу директорію проєкту до sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from indexing import RAGIndexManager


class TestRAGIndexManagerInitDB(unittest.TestCase):
    """Тести для методу init_db."""

    def setUp(self):
        """Створює тимчасову директорію та менеджер індексації."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_index.db")
        self.manager = RAGIndexManager(db_path=self.db_path)

    def tearDown(self):
        """Видаляє тимчасову директорію та всі файли."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_db_creates_tables(self):
        """Перевіряє, що init_db створює всі необхідні таблиці: chunks, fts_chunks, entities, relationships, chunk_entities."""
        self.manager.init_db()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Отримуємо список усіх таблиць
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected_tables = {"chunks", "fts_chunks", "entities", "relationships", "chunk_entities"}
        for table in expected_tables:
            self.assertIn(table, tables, f"Таблиця '{table}' не створена після init_db()")

    def test_init_db_idempotent(self):
        """Перевіряє, що повторний виклик init_db() не викликає помилок."""
        self.manager.init_db()
        # Другий виклик не повинен кидати виключень
        try:
            self.manager.init_db()
        except Exception as e:
            self.fail(f"Повторний виклик init_db() спричинив помилку: {e}")


class TestRAGIndexManagerInsert(unittest.TestCase):
    """Тести для методу insert_ingested_data з мокнутими ембедінгами."""

    def setUp(self):
        """Створює тимчасову БД, ініціалізує схему та мокає get_embedding."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_index.db")
        self.manager = RAGIndexManager(db_path=self.db_path)
        self.manager.init_db()
        # Мок ембедінгів: повертаємо нульовий вектор розмірністю 768
        self.manager.get_embedding = lambda text: np.zeros(768, dtype=np.float32)

    def tearDown(self):
        """Видаляє тимчасову директорію."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_ingestion_result(self, *, chunks=None, entities=None, relations=None):
        """Генерує структуру ingestion_result з дефолтними порожніми списками."""
        return {
            "chunks": chunks or [],
            "entities": entities or [],
            "relations": relations or [],
        }

    def test_insert_entities(self):
        """Перевіряє, що сутності коректно записуються в таблицю entities."""
        entities = [
            ("Apple Silicon", "Concept"),
            ("Zero Trust", "Concept"),
            ("RAG", "Technology"),
        ]
        ingestion = self._make_ingestion_result(entities=entities)
        self.manager.insert_ingested_data(ingestion)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, type FROM entities ORDER BY name")
        rows = cursor.fetchall()
        conn.close()

        self.assertEqual(len(rows), 3)
        names = {row[0] for row in rows}
        self.assertSetEqual(names, {"Apple Silicon", "Zero Trust", "RAG"})

        # Перевіряємо типи
        type_map = {row[0]: row[1] for row in rows}
        self.assertEqual(type_map["RAG"], "Technology")
        self.assertEqual(type_map["Apple Silicon"], "Concept")

    def test_insert_relations(self):
        """Перевіряє, що зв'язки між сутностями записуються в таблицю relationships."""
        entities = [("doc1.md", "Document"), ("Apple Silicon", "Concept"), ("RAG", "Technology")]
        relations = [
            ("doc1.md", "mentions", "Apple Silicon"),
            ("doc1.md", "links_to", "RAG"),
        ]
        ingestion = self._make_ingestion_result(entities=entities, relations=relations)
        self.manager.insert_ingested_data(ingestion)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT r.relation_type, src.name, tgt.name FROM relationships r "
                        "JOIN entities src ON r.source_id = src.id "
                        "JOIN entities tgt ON r.target_id = tgt.id "
                        "ORDER BY r.relation_type")
        rows = cursor.fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        relation_types = {row[0] for row in rows}
        self.assertIn("mentions", relation_types)
        self.assertIn("links_to", relation_types)

        # Перевіряємо зв'язок doc1.md → Apple Silicon
        mentions = [r for r in rows if r[0] == "mentions"]
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0][1], "doc1.md")
        self.assertEqual(mentions[0][2], "Apple Silicon")

    def test_insert_chunks(self):
        """Перевіряє запис чанків у таблиці chunks, fts_chunks та chunk_entities."""
        entities = [("Apple Silicon", "Concept"), ("RAG", "Technology")]
        chunks = [
            {
                "file_path": "doc1.md",
                "heading": "Intro",
                "content": "Apple Silicon забезпечує прискорення Metal GPU",
                "entities": [("Apple Silicon", "Concept")],
            },
            {
                "file_path": "doc2.md",
                "heading": "RAG Overview",
                "content": "RAG покращує якість відповідей LLM моделей",
                "entities": [("RAG", "Technology")],
            },
        ]
        ingestion = self._make_ingestion_result(entities=entities, chunks=chunks)
        self.manager.insert_ingested_data(ingestion)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Перевірка chunks
        cursor.execute("SELECT id, file_path, heading, content FROM chunks ORDER BY id")
        chunk_rows = cursor.fetchall()
        self.assertEqual(len(chunk_rows), 2)
        self.assertEqual(chunk_rows[0][1], "doc1.md")
        self.assertEqual(chunk_rows[1][1], "doc2.md")
        self.assertIn("Apple Silicon", chunk_rows[0][3])

        # Перевірка fts_chunks
        cursor.execute("SELECT chunk_id, content FROM fts_chunks ORDER BY chunk_id")
        fts_rows = cursor.fetchall()
        self.assertEqual(len(fts_rows), 2)
        self.assertEqual(fts_rows[0][0], chunk_rows[0][0])  # chunk_id збігається

        # Перевірка chunk_entities
        cursor.execute("SELECT chunk_id, entity_id FROM chunk_entities ORDER BY chunk_id")
        ce_rows = cursor.fetchall()
        self.assertEqual(len(ce_rows), 2)

        conn.close()

    def test_insert_chunks_vector_is_blob(self):
        """Перевіряє, що вектор ембедінгу зберігається як BLOB у chunks."""
        entities = [("Test", "Concept")]
        chunks = [
            {
                "file_path": "test.md",
                "heading": "Test",
                "content": "Тестовий контент для перевірки векторів",
                "entities": [("Test", "Concept")],
            }
        ]
        ingestion = self._make_ingestion_result(entities=entities, chunks=chunks)
        self.manager.insert_ingested_data(ingestion)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT vector FROM chunks LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row[0])
        # Десеріалізуємо BLOB назад у numpy масив
        vec = np.frombuffer(row[0], dtype=np.float32)
        self.assertEqual(vec.shape[0], 768)


class TestRAGIndexManagerSearchBM25(unittest.TestCase):
    """Тести для методу search_bm25."""

    def setUp(self):
        """Створює БД із тестовими чанками для пошуку."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_index.db")
        self.manager = RAGIndexManager(db_path=self.db_path)
        self.manager.init_db()
        self.manager.get_embedding = lambda text: np.zeros(768, dtype=np.float32)
        self._insert_test_data()

    def tearDown(self):
        """Видаляє тимчасову директорію."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_test_data(self):
        """Вставляє тестові дані для пошукових тестів."""
        ingestion_result = {
            "chunks": [
                {
                    "file_path": "doc1.md",
                    "heading": "Intro",
                    "content": "Apple Silicon забезпечує прискорення Metal GPU для машинного навчання",
                    "entities": [("Apple Silicon", "Concept")],
                },
                {
                    "file_path": "doc2.md",
                    "heading": "Security",
                    "content": "Zero Trust архітектура захищає мережеву інфраструктуру від атак",
                    "entities": [("Zero Trust", "Concept")],
                },
                {
                    "file_path": "doc3.md",
                    "heading": "RAG",
                    "content": "Retrieval Augmented Generation покращує якість відповідей LLM моделей",
                    "entities": [("RAG", "Technology")],
                },
            ],
            "entities": [
                ("Apple Silicon", "Concept"),
                ("Zero Trust", "Concept"),
                ("RAG", "Technology"),
                ("doc1.md", "Document"),
            ],
            "relations": [
                ("doc1.md", "mentions", "Apple Silicon"),
                ("doc1.md", "links_to", "RAG"),
            ],
        }
        self.manager.insert_ingested_data(ingestion_result)

    def test_bm25_finds_relevant(self):
        """Перевіряє, що BM25 пошук за ключовим словом повертає релевантний чанк першим."""
        results = self.manager.search_bm25("Metal GPU прискорення")
        self.assertTrue(len(results) > 0, "BM25 повинен повернути хоча б один результат")
        # Перший результат має містити згадку Metal GPU
        self.assertIn("Metal GPU", results[0]["content"])
        self.assertEqual(results[0]["file_path"], "doc1.md")

    def test_bm25_empty_query(self):
        """Перевіряє, що порожній або спецсимвольний запит повертає порожній список."""
        # Порожній запит
        results_empty = self.manager.search_bm25("")
        self.assertEqual(results_empty, [])

        # Запит зі спеціальними символами, що зводяться до порожнього рядка
        results_special = self.manager.search_bm25("!@#$%^&*()")
        self.assertEqual(results_special, [])

    def test_bm25_no_results(self):
        """Перевіряє, що запит без збігів у БД повертає порожній список."""
        results = self.manager.search_bm25("квантова телепортація гравітонів")
        self.assertEqual(results, [])

    def test_bm25_returns_correct_structure(self):
        """Перевіряє, що результати BM25 містять усі необхідні ключі."""
        results = self.manager.search_bm25("Retrieval Augmented Generation")
        self.assertTrue(len(results) > 0)

        required_keys = {"chunk_id", "content", "file_path", "heading", "score"}
        for result in results:
            self.assertTrue(
                required_keys.issubset(result.keys()),
                f"Результат BM25 не містить усіх ключів: {result.keys()}"
            )
            self.assertIsInstance(result["score"], float)
            self.assertGreater(result["score"], 0.0)


class TestRAGIndexManagerGetQueryEntities(unittest.TestCase):
    """Тести для методу get_query_entities."""

    def setUp(self):
        """Створює БД із тестовими сутностями."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_index.db")
        self.manager = RAGIndexManager(db_path=self.db_path)
        self.manager.init_db()
        self.manager.get_embedding = lambda text: np.zeros(768, dtype=np.float32)

        # Вставляємо сутності
        ingestion = {
            "chunks": [],
            "entities": [
                ("Apple Silicon", "Concept"),
                ("Zero Trust", "Concept"),
                ("RAG", "Technology"),
                ("AI", "Concept"),  # Коротка назва — 2 символи
            ],
            "relations": [],
        }
        self.manager.insert_ingested_data(ingestion)

    def tearDown(self):
        """Видаляє тимчасову директорію."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_query_entities_finds_match(self):
        """Перевіряє, що метод знаходить сутність за точним збігом у тексті запиту."""
        results = self.manager.get_query_entities("Розкажи про Apple Silicon та його переваги")
        names = [ent["name"] for ent in results]
        self.assertIn("Apple Silicon", names)

    def test_get_query_entities_case_insensitive(self):
        """Перевіряє, що пошук сутностей є регістронезалежним."""
        results = self.manager.get_query_entities("що таке apple silicon?")
        names = [ent["name"] for ent in results]
        self.assertIn("Apple Silicon", names)

        # Верхній регістр
        results_upper = self.manager.get_query_entities("APPLE SILICON для ML")
        names_upper = [ent["name"] for ent in results_upper]
        self.assertIn("Apple Silicon", names_upper)

    def test_get_query_entities_skips_short(self):
        """Перевіряє, що сутності з іменем ≤ 2 символи ігноруються."""
        # "AI" — 2 символи, не повинно матчитися
        results = self.manager.get_query_entities("AI — це технологія майбутнього")
        names = [ent["name"] for ent in results]
        self.assertNotIn("AI", names)

    def test_get_query_entities_multiple_matches(self):
        """Перевіряє, що метод знаходить кілька сутностей в одному запиті."""
        results = self.manager.get_query_entities("Apple Silicon та Zero Trust в RAG архітектурі")
        names = {ent["name"] for ent in results}
        self.assertIn("Apple Silicon", names)
        self.assertIn("Zero Trust", names)
        self.assertIn("RAG", names)

    def test_get_query_entities_returns_correct_structure(self):
        """Перевіряє, що кожний результат містить ключі id, name, type."""
        results = self.manager.get_query_entities("Apple Silicon")
        self.assertTrue(len(results) > 0)
        for ent in results:
            self.assertIn("id", ent)
            self.assertIn("name", ent)
            self.assertIn("type", ent)
            self.assertIsInstance(ent["id"], int)


class TestRAGIndexManagerHybridSearchRRF(unittest.TestCase):
    """Тести для методу hybrid_search_rrf з мокнутими підпошуками."""

    def setUp(self):
        """Створює БД, вставляє тестові дані, мокає search_vector і search_bm25."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_index.db")
        self.manager = RAGIndexManager(db_path=self.db_path)
        self.manager.init_db()
        self.manager.get_embedding = lambda text: np.zeros(768, dtype=np.float32)
        self._insert_test_data()

    def tearDown(self):
        """Видаляє тимчасову директорію."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_test_data(self):
        """Вставляє тестові дані для пошукових тестів."""
        ingestion_result = {
            "chunks": [
                {
                    "file_path": "doc1.md",
                    "heading": "Intro",
                    "content": "Apple Silicon забезпечує прискорення Metal GPU для машинного навчання",
                    "entities": [("Apple Silicon", "Concept")],
                },
                {
                    "file_path": "doc2.md",
                    "heading": "Security",
                    "content": "Zero Trust архітектура захищає мережеву інфраструктуру від атак",
                    "entities": [("Zero Trust", "Concept")],
                },
                {
                    "file_path": "doc3.md",
                    "heading": "RAG",
                    "content": "Retrieval Augmented Generation покращує якість відповідей LLM моделей",
                    "entities": [("RAG", "Technology")],
                },
            ],
            "entities": [
                ("Apple Silicon", "Concept"),
                ("Zero Trust", "Concept"),
                ("RAG", "Technology"),
                ("doc1.md", "Document"),
            ],
            "relations": [
                ("doc1.md", "mentions", "Apple Silicon"),
                ("doc1.md", "links_to", "RAG"),
            ],
        }
        self.manager.insert_ingested_data(ingestion_result)

    def _make_search_result(self, chunk_id, content, file_path, heading, score):
        """Створює структуру результату пошуку."""
        return {
            "chunk_id": chunk_id,
            "content": content,
            "file_path": file_path,
            "heading": heading,
            "score": score,
        }

    def test_rrf_combines_results(self):
        """Перевіряє, що RRF коректно об'єднує результати з векторного та BM25 пошуку."""
        # Мокаємо search_vector: повертає chunk 1 (rank 0) та chunk 3 (rank 1)
        mock_vector_results = [
            self._make_search_result(1, "Apple Silicon content", "doc1.md", "Intro", 0.9),
            self._make_search_result(3, "RAG content", "doc3.md", "RAG", 0.7),
        ]
        # Мокаємо search_bm25: повертає chunk 2 (rank 0) та chunk 1 (rank 1)
        mock_bm25_results = [
            self._make_search_result(2, "Zero Trust content", "doc2.md", "Security", 0.8),
            self._make_search_result(1, "Apple Silicon content", "doc1.md", "Intro", 0.6),
        ]

        self.manager.search_vector = MagicMock(return_value=mock_vector_results)
        self.manager.search_bm25 = MagicMock(return_value=mock_bm25_results)

        results = self.manager.hybrid_search_rrf("test query", limit=5, k=60)

        # Chunk 1 (id=1) з'являється в обох пошуках — повинен мати найвищий RRF скор
        self.assertTrue(len(results) > 0, "RRF повинен повернути результати")

        # Перевіряємо, що chunk 1 має найвищий скор (бо присутній в обох результатах)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn(1, chunk_ids)

        # Знаходимо скори
        scores_by_id = {r["chunk_id"]: r["score"] for r in results}
        # Chunk 1 має скор із двох джерел, тому його скор повинен бути більшим
        # ніж скор chunk 2 або chunk 3, які з'являються лише в одному
        self.assertGreater(scores_by_id[1], scores_by_id.get(2, 0))
        self.assertGreater(scores_by_id[1], scores_by_id.get(3, 0))

    def test_rrf_graph_boost(self):
        """Перевіряє, що чанки, пов'язані з сутностями запиту, отримують підсилений скор."""
        # Chunk 1 пов'язаний із "Apple Silicon" через chunk_entities
        # Мокаємо пошуки: chunk 1 і chunk 2 з однаковим рангом
        mock_vector_results = [
            self._make_search_result(1, "Apple Silicon content", "doc1.md", "Intro", 0.9),
            self._make_search_result(2, "Zero Trust content", "doc2.md", "Security", 0.8),
        ]
        mock_bm25_results = []  # Порожній BM25 для спрощення

        self.manager.search_vector = MagicMock(return_value=mock_vector_results)
        self.manager.search_bm25 = MagicMock(return_value=mock_bm25_results)

        # Запит з "Apple Silicon" — сутність знайдеться через get_query_entities
        results = self.manager.hybrid_search_rrf("Apple Silicon тестовий запит", limit=5, k=60, graph_boost=2.0)

        scores_by_id = {r["chunk_id"]: r["score"] for r in results}

        # Chunk 1 має сутність "Apple Silicon" → повинен отримати graph_boost
        # Chunk 2 має "Zero Trust", що не згадується в запиті → без boost
        self.assertIn(1, scores_by_id)
        self.assertIn(2, scores_by_id)

        # Chunk 1 повинен бути першим (бустнутий)
        self.assertEqual(results[0]["chunk_id"], 1)

        # Базовий RRF скор для rank 0 = 1/(60+0+1) ≈ 0.01639
        # Бустнутий скор chunk 1 = 0.01639 * 2.0 = 0.03279
        # Не-бустнутий скор chunk 2 = 1/(60+1+1) ≈ 0.01613
        self.assertGreater(scores_by_id[1], scores_by_id[2])

    def test_rrf_returns_correct_structure(self):
        """Перевіряє, що результати RRF містять усі необхідні ключі."""
        mock_vector_results = [
            self._make_search_result(1, "Content 1", "doc1.md", "Intro", 0.9),
        ]
        mock_bm25_results = [
            self._make_search_result(1, "Content 1", "doc1.md", "Intro", 0.8),
        ]

        self.manager.search_vector = MagicMock(return_value=mock_vector_results)
        self.manager.search_bm25 = MagicMock(return_value=mock_bm25_results)

        results = self.manager.hybrid_search_rrf("test", limit=5)

        self.assertTrue(len(results) > 0)
        required_keys = {"chunk_id", "content", "file_path", "heading", "score"}
        for result in results:
            self.assertTrue(
                required_keys.issubset(result.keys()),
                f"Результат RRF не містить усіх ключів: {result.keys()}"
            )

    def test_rrf_empty_results(self):
        """Перевіряє, що RRF повертає порожній список, коли обидва пошуки порожні."""
        self.manager.search_vector = MagicMock(return_value=[])
        self.manager.search_bm25 = MagicMock(return_value=[])

        results = self.manager.hybrid_search_rrf("nonexistent query", limit=5)
        self.assertEqual(results, [])

    def test_rrf_respects_limit(self):
        """Перевіряє, що RRF повертає не більше limit результатів."""
        # Створюємо багато мокнутих результатів
        mock_vector_results = [
            self._make_search_result(i, f"Content {i}", f"doc{i}.md", f"Heading {i}", 0.9 - i * 0.1)
            for i in range(1, 4)
        ]
        mock_bm25_results = []

        self.manager.search_vector = MagicMock(return_value=mock_vector_results)
        self.manager.search_bm25 = MagicMock(return_value=mock_bm25_results)

        results = self.manager.hybrid_search_rrf("test", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_rrf_graph_boost_via_relationship(self):
        """Перевіряє графове підсилення через зв'язок 1-го порядку в таблиці relationships.

        doc1.md → links_to → RAG. Запит із сутністю 'doc1.md' повинен бустнути chunk 3 (RAG),
        бо вони пов'язані через relationships.
        """
        # Chunk 3 (RAG) пов'язаний із doc1.md через relationship links_to
        mock_vector_results = [
            self._make_search_result(2, "Zero Trust content", "doc2.md", "Security", 0.9),
            self._make_search_result(3, "RAG content", "doc3.md", "RAG", 0.8),
        ]
        mock_bm25_results = []

        self.manager.search_vector = MagicMock(return_value=mock_vector_results)
        self.manager.search_bm25 = MagicMock(return_value=mock_bm25_results)

        # Запит, що містить "doc1.md" як сутність (довжина > 2)
        results = self.manager.hybrid_search_rrf("doc1.md пов'язані дані", limit=5, k=60, graph_boost=3.0)

        scores_by_id = {r["chunk_id"]: r["score"] for r in results}

        # Chunk 3 (RAG) пов'язаний з doc1.md через relationships → буст
        # Chunk 2 (Zero Trust) не пов'язаний з doc1.md → без бусту
        if 3 in scores_by_id and 2 in scores_by_id:
            self.assertGreater(scores_by_id[3], scores_by_id[2],
                               "Chunk 3 (RAG) повинен мати вищий скор через графове підсилення "
                               "зв'язку doc1.md → links_to → RAG")


if __name__ == "__main__":
    unittest.main()
