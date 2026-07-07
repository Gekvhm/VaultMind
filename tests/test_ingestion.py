"""Тести для модуля ingestion.py — DocumentIngester.

Покриває: clean_frontmatter, extract_structural_entities, chunk_text,
process_file, process_directory.
"""

import os
import shutil
import tempfile
import unittest

from ingestion import DocumentIngester


class TestCleanFrontmatter(unittest.TestCase):
    """Тести методу clean_frontmatter."""

    def setUp(self):
        self.ingester = DocumentIngester()

    # ── clean_frontmatter ──────────────────────────────────────────────

    def test_clean_frontmatter_with_yaml(self):
        """Перевіряє коректне вилучення YAML frontmatter та повернення метаданих."""
        text = "---\ntags: test\ndate: 2026-01-01\n---\n# Content"
        content, meta = self.ingester.clean_frontmatter(text)
        self.assertEqual(content, "# Content")
        self.assertEqual(meta, {"tags": "test", "date": "2026-01-01"})

    def test_clean_frontmatter_without_yaml(self):
        """Перевіряє, що звичайний текст без frontmatter повертається без змін."""
        text = "Just a plain text without frontmatter."
        content, meta = self.ingester.clean_frontmatter(text)
        self.assertEqual(content, text)
        self.assertEqual(meta, {})

    def test_clean_frontmatter_partial_yaml(self):
        """Перевіряє текст, що починається з --- але має лише один роздільник."""
        text = "---\ntags: test\ndate: 2026-01-01\n# Content after single separator"
        content, meta = self.ingester.clean_frontmatter(text)
        # Тільки один ---, тому split('---', 2) дає лише 2 частини → повертає оригінал
        self.assertEqual(content, text)
        self.assertEqual(meta, {})


class TestExtractStructuralEntities(unittest.TestCase):
    """Тести методу extract_structural_entities."""

    def setUp(self):
        self.ingester = DocumentIngester()
        self.file_name = "test_note.md"

    # ── wiki-links ─────────────────────────────────────────────────────

    def test_extract_wiki_links(self):
        """Перевіряє витягання вікі-посилань у форматах [[target]] та [[target|alias]]."""
        text = "See [[Apple Silicon]] and [[RAG|Retrieval Augmented Generation]]."
        entities, relations = self.ingester.extract_structural_entities(text, self.file_name)

        entity_names = [name for name, _ in entities]
        entity_types = {name: etype for name, etype in entities}

        self.assertIn("Apple Silicon", entity_names)
        self.assertIn("RAG", entity_names)
        self.assertEqual(entity_types["Apple Silicon"], "Document")
        self.assertEqual(entity_types["RAG"], "Document")

        relation_tuples = [(src, rel, tgt) for src, rel, tgt in relations]
        self.assertIn((self.file_name, "links_to", "Apple Silicon"), relation_tuples)
        self.assertIn((self.file_name, "links_to", "RAG"), relation_tuples)

    # ── tags ───────────────────────────────────────────────────────────

    def test_extract_tags(self):
        """Перевіряє витягання хеш-тегів, зокрема вкладених з /."""
        text = "Topics: #cybersecurity #ai/ml are important."
        entities, relations = self.ingester.extract_structural_entities(text, self.file_name)

        entity_names = [name for name, _ in entities]
        entity_types = {name: etype for name, etype in entities}

        self.assertIn("#cybersecurity", entity_names)
        self.assertIn("#ai/ml", entity_names)
        self.assertEqual(entity_types["#cybersecurity"], "Tag")
        self.assertEqual(entity_types["#ai/ml"], "Tag")

        relation_tuples = [(src, rel, tgt) for src, rel, tgt in relations]
        self.assertIn((self.file_name, "has_tag", "#cybersecurity"), relation_tuples)
        self.assertIn((self.file_name, "has_tag", "#ai/ml"), relation_tuples)

    # ── bold concepts ──────────────────────────────────────────────────

    def test_extract_bold_concepts(self):
        """Перевіряє витягання жирних концептів як сутностей типу Concept."""
        text = "Apply **Zero Trust** architecture."
        entities, relations = self.ingester.extract_structural_entities(text, self.file_name)

        entity_names = [name for name, _ in entities]
        entity_types = {name: etype for name, etype in entities}

        self.assertIn("Zero Trust", entity_names)
        self.assertEqual(entity_types["Zero Trust"], "Concept")

        relation_tuples = [(src, rel, tgt) for src, rel, tgt in relations]
        self.assertIn((self.file_name, "mentions", "Zero Trust"), relation_tuples)

    def test_extract_bold_skips_long(self):
        """Перевіряє, що жирний текст довжиною >= 50 символів ігнорується."""
        long_bold = "A" * 50  # рівно 50 символів — повинен бути пропущений (< 50 = False)
        text = f"This is **{long_bold}** in a sentence."
        entities, relations = self.ingester.extract_structural_entities(text, self.file_name)

        entity_names = [name for name, _ in entities]
        self.assertNotIn(long_bold, entity_names)

        # Також перевіримо текст з 60 символами
        very_long_bold = "This is a very long bold text that exceeds fifty characters limit"
        text2 = f"Intro **{very_long_bold}** end."
        entities2, _ = self.ingester.extract_structural_entities(text2, self.file_name)
        entity_names2 = [name for name, _ in entities2]
        self.assertNotIn(very_long_bold, entity_names2)

    # ── combined ───────────────────────────────────────────────────────

    def test_extract_combined(self):
        """Перевіряє одночасне витягання вікі-посилань, тегів та жирних концептів."""
        text = "See [[Obsidian]] for #pkm with **Second Brain** approach."
        entities, relations = self.ingester.extract_structural_entities(text, self.file_name)

        entity_names = [name for name, _ in entities]

        # Документ-посилання
        self.assertIn("Obsidian", entity_names)
        # Тег
        self.assertIn("#pkm", entity_names)
        # Концепт
        self.assertIn("Second Brain", entity_names)
        # Сам файл
        self.assertIn(self.file_name, entity_names)

        # Перевіряємо кількість зв'язків: 1 links_to + 1 has_tag + 1 mentions = 3
        self.assertEqual(len(relations), 3)


class TestChunkText(unittest.TestCase):
    """Тести методу chunk_text."""

    def setUp(self):
        self.file_path = "/tmp/test_doc.md"

    # ── short text ─────────────────────────────────────────────────────

    def test_chunk_short_text(self):
        """Перевіряє, що текст коротший за chunk_size повертає рівно 1 чанк."""
        ingester = DocumentIngester(chunk_size=1000, chunk_overlap=200)
        short_text = "This is a short text."
        chunks = ingester.chunk_text(short_text, self.file_path, [], [])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], short_text)

    # ── long text ──────────────────────────────────────────────────────

    def test_chunk_long_text(self):
        """Перевіряє, що довгий текст (3000 символів) розбивається на кілька чанків."""
        ingester = DocumentIngester(chunk_size=1000, chunk_overlap=200)
        # Генеруємо текст з речень, щоб було де розділити
        sentences = ["This is sentence number %d. " % i for i in range(200)]
        long_text = "".join(sentences)
        # Обрізаємо до ~3000 символів
        long_text = long_text[:3000]

        chunks = ingester.chunk_text(long_text, self.file_path, [], [])

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            # Допускаємо невеликий запас через вирівнювання по реченню
            self.assertLessEqual(len(chunk["content"]), 1200)

    # ── overlap ────────────────────────────────────────────────────────

    def test_chunk_overlap(self):
        """Перевіряє, що між послідовними чанками існує перекриття контенту."""
        ingester = DocumentIngester(chunk_size=500, chunk_overlap=100)
        sentences = ["Word%d " % i for i in range(500)]
        text = "".join(sentences)

        chunks = ingester.chunk_text(text, self.file_path, [], [])

        if len(chunks) >= 2:
            for i in range(len(chunks) - 1):
                content_a = chunks[i]["content"]
                content_b = chunks[i + 1]["content"]
                # Кінець першого чанку повинен перетинатися з початком другого
                # Беремо останні 50 символів першого чанку і шукаємо їх у другому
                tail = content_a[-50:]
                self.assertTrue(
                    tail in content_b or any(
                        word in content_b for word in tail.split()
                    ),
                    f"Очікувалося перекриття між чанками {i} і {i+1}"
                )

    # ── heading tracking ───────────────────────────────────────────────

    def test_chunk_heading_tracking(self):
        """Перевіряє, що чанки коректно відстежують поточний заголовок."""
        ingester = DocumentIngester(chunk_size=100, chunk_overlap=20)
        text = "# First\n" + "a " * 80 + "\n# Second\n" + "b " * 80
        chunks = ingester.chunk_text(text, self.file_path, [], [])

        self.assertGreater(len(chunks), 1)

        # Перший чанк повинен мати заголовок "First"
        self.assertEqual(chunks[0]["heading"], "First")

        # Останній чанк повинен мати заголовок "Second"
        last_chunk = chunks[-1]
        self.assertEqual(last_chunk["heading"], "Second")

    # ── entity binding ─────────────────────────────────────────────────

    def test_chunk_entity_binding(self):
        """Перевіряє, що сутності прив'язуються лише до чанків, де вони присутні."""
        ingester = DocumentIngester(chunk_size=100, chunk_overlap=20)
        # Слово "Alpha" лише на початку, "Beta" лише наприкінці
        text = "Alpha " + "x " * 100 + " Beta"
        base_entities = [("Alpha", "Concept"), ("Beta", "Concept")]

        chunks = ingester.chunk_text(text, self.file_path, base_entities, [])

        self.assertGreater(len(chunks), 1)

        first_entity_names = [name for name, _ in chunks[0]["entities"]]
        last_entity_names = [name for name, _ in chunks[-1]["entities"]]

        self.assertIn("Alpha", first_entity_names)
        self.assertNotIn("Beta", first_entity_names)

        self.assertIn("Beta", last_entity_names)
        self.assertNotIn("Alpha", last_entity_names)


class TestProcessFile(unittest.TestCase):
    """Тести методу process_file."""

    def setUp(self):
        self.ingester = DocumentIngester()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    # ── .md file ───────────────────────────────────────────────────────

    def test_process_md_file(self):
        """Перевіряє повну обробку .md файлу з frontmatter, вікі-посиланнями та тегами."""
        md_content = (
            "---\ntags: research\ndate: 2026-06-01\n---\n"
            "# My Research\n\n"
            "This document references [[Knowledge Graph]] and uses #ai tag.\n"
            "It also mentions **RAG Pipeline** concept.\n"
        )
        file_path = os.path.join(self.temp_dir, "research.md")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        result = self.ingester.process_file(file_path)

        self.assertIn("chunks", result)
        self.assertIn("entities", result)
        self.assertIn("relations", result)
        self.assertIsInstance(result["chunks"], list)
        self.assertGreater(len(result["chunks"]), 0)
        self.assertGreater(len(result["entities"]), 0)
        self.assertGreater(len(result["relations"]), 0)

        entity_names = [name for name, _ in result["entities"]]
        self.assertIn("Knowledge Graph", entity_names)
        self.assertIn("#ai", entity_names)
        self.assertIn("RAG Pipeline", entity_names)
        # Метадані frontmatter
        self.assertIn("research", entity_names)
        self.assertIn("2026-06-01", entity_names)

    # ── .txt file ──────────────────────────────────────────────────────

    def test_process_txt_file(self):
        """Перевіряє обробку простого .txt файлу без frontmatter."""
        txt_content = "Simple plain text document with **Important Term** inside."
        file_path = os.path.join(self.temp_dir, "notes.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(txt_content)

        result = self.ingester.process_file(file_path)

        self.assertIn("chunks", result)
        self.assertIn("entities", result)
        self.assertIn("relations", result)
        self.assertGreater(len(result["chunks"]), 0)

        entity_names = [name for name, _ in result["entities"]]
        self.assertIn("Important Term", entity_names)


class TestProcessDirectory(unittest.TestCase):
    """Тести методу process_directory."""

    def setUp(self):
        self.ingester = DocumentIngester()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    # ── multiple files ─────────────────────────────────────────────────

    def test_process_directory_multiple_files(self):
        """Перевіряє, що обробляються лише .md та .txt, а .docx ігнорується."""
        # Створюємо .md
        md_path = os.path.join(self.temp_dir, "doc1.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# Document One\nContent of doc one with [[Link1]].")

        # Створюємо .txt
        txt_path = os.path.join(self.temp_dir, "doc2.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("Content of doc two with #tag2.")

        # Створюємо .docx (заглушка — бінарний файл, який не повинен оброблятися)
        docx_path = os.path.join(self.temp_dir, "doc3.docx")
        with open(docx_path, "wb") as f:
            f.write(b"PK\x03\x04fake docx content")

        result = self.ingester.process_directory(self.temp_dir)

        # Маємо чанки лише з 2 файлів
        processed_files = set(chunk["file_path"] for chunk in result["chunks"])
        self.assertIn(md_path, processed_files)
        self.assertIn(txt_path, processed_files)
        self.assertNotIn(docx_path, processed_files)
        self.assertEqual(len(processed_files), 2)

    # ── empty directory ────────────────────────────────────────────────

    def test_process_directory_empty(self):
        """Перевіряє, що порожня директорія повертає порожні списки."""
        empty_dir = tempfile.mkdtemp(dir=self.temp_dir)
        result = self.ingester.process_directory(empty_dir)

        self.assertEqual(result["chunks"], [])
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["relations"], [])

    # ── deduplication ──────────────────────────────────────────────────

    def test_process_directory_deduplicates_entities(self):
        """Перевіряє дедуплікацію сутностей, коли два файли посилаються на одну ціль."""
        # Обидва файли посилаються на [[SharedTarget]]
        file1 = os.path.join(self.temp_dir, "file1.md")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("Ref to [[SharedTarget]] from file1.")

        file2 = os.path.join(self.temp_dir, "file2.md")
        with open(file2, "w", encoding="utf-8") as f:
            f.write("Ref to [[SharedTarget]] from file2.")

        result = self.ingester.process_directory(self.temp_dir)

        entity_names = [name for name, _ in result["entities"]]
        # SharedTarget повинен бути присутній рівно один раз
        self.assertEqual(
            entity_names.count("SharedTarget"), 1,
            "Сутність 'SharedTarget' повинна бути дедуплікована"
        )


if __name__ == "__main__":
    unittest.main()
