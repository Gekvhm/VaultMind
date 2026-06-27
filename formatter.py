import os
import shutil
import sqlite3
import re
from inference import LLMInferenceManager

class KnowledgeFormatter:
    def __init__(self, db_path="rag_storage.db", llm_model_path=None, llm_config=None):
        self.db_path = db_path
        self.llm_manager = LLMInferenceManager(config=llm_config, model_path=llm_model_path)
        
    def load_existing_concepts(self, vault_dir=None):
        """Збирає унікальні поняття з бази даних та назви файлів з Obsidian Vault."""
        concepts = set()
        
        # 1. Зчитуємо сутності з бази даних
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM entities")
                for row in cursor.fetchall():
                    if row[0]:
                        concepts.add(row[0].strip())
                cursor.execute("SELECT DISTINCT heading FROM chunks WHERE heading != '' AND heading IS NOT NULL")
                for row in cursor.fetchall():
                    if row[0]:
                        concepts.add(row[0].strip())
                conn.close()
            except Exception as e:
                print(f"[Warning] Не вдалося зчитати сутності з БД: {e}")
                
        # 2. Зчитуємо назви файлів з Obsidian Vault
        if vault_dir and os.path.exists(vault_dir):
            try:
                for root, _, files in os.walk(vault_dir):
                    # Пропускаємо системні та архівні папки
                    if ".archive" in root or ".git" in root or ".venv" in root:
                        continue
                    for file in files:
                        if file.endswith(".md"):
                            concepts.add(file[:-3])  # Відкидаємо ".md"
            except Exception as e:
                print(f"[Warning] Не вдалося зчитати назви файлів з Vault: {e}")
                
        # Очищуємо порожні та дуже короткі концепції
        concepts = {c for c in concepts if len(c) > 2}
        return list(concepts)

    def split_raw_text(self, text, max_chars=4000):
        """
        Розбиває довгий текст на логічні частини (до max_chars символів)
        для запобігання переповнення контексту LLM та створення менших нотаток.
        Спробує розбивати по абзацах.
        """
        if len(text) <= max_chars:
            return [text]
            
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_len = 0
        
        for para in paragraphs:
            para_len = len(para)
            if current_len + para_len > max_chars:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [para]
                    current_len = para_len
                else:
                    # Якщо один абзац занадто великий, розбиваємо по реченнях
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    for sent in sentences:
                        sent_len = len(sent)
                        if current_len + sent_len > max_chars:
                            if current_chunk:
                                chunks.append(" ".join(current_chunk))
                                current_chunk = [sent]
                                current_len = sent_len
                            else:
                                chunks.append(sent)
                        else:
                            current_chunk.append(sent)
                            current_len += sent_len + 1
            else:
                current_chunk.append(para)
                current_len += para_len + 2
                
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))
            
        return chunks

    def process_raw_data(self, input_path, vault_dir, auto_ingest=False):
        """
        Форматує сирі дані з input_path (файл або папка) та зберігає
        результати у vault_dir. За потреби запускає автоматичну індексацію.
        """
        if not os.path.exists(input_path):
            print(f"Помилка: Шлях '{input_path}' не існує.")
            return False
            
        os.makedirs(vault_dir, exist_ok=True)
        archive_dir = os.path.join(os.path.dirname(input_path) if os.path.isfile(input_path) else input_path, ".archive")
        
        # Збираємо список файлів для обробки
        files_to_process = []
        if os.path.isfile(input_path):
            files_to_process.append(input_path)
        else:
            for root, _, files in os.walk(input_path):
                if ".archive" in root or ".git" in root or ".venv" in root:
                    continue
                for file in files:
                    if file.endswith((".txt", ".md", ".docx")):
                        files_to_process.append(os.path.join(root, file))
                        
        if not files_to_process:
            print("Не знайдено сирих текстових або документних файлів (.txt, .md чи .docx) для обробки.")
            return False
            
        print(f"Знайдено {len(files_to_process)} файлів для структурування.")
        
        # Завантажуємо відомі концепти
        concepts = self.load_existing_concepts(vault_dir)
        print(f"Завантажено {len(concepts)} існуючих концептів для авто-лінкування.")
        
        formatted_files = []
        
        for file_path in files_to_process:
            print(f"\nОбробка файлу: {os.path.basename(file_path)}...")
            
            if file_path.endswith(".docx"):
                try:
                    import docx
                    doc = docx.Document(file_path)
                    content = "\n".join([p.text for p in doc.paragraphs]).strip()
                except Exception as e:
                    print(f"Помилка зчитування .docx файлу {file_path}: {e}")
                    continue
            else:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                
            if not content:
                print(f"Файл {os.path.basename(file_path)} порожній або не вдалося отримати текст. Пропуск.")
                continue
                
            # Розбиваємо текст на частини, якщо він занадто довгий
            parts = self.split_raw_text(content, max_chars=4000)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            
            for i, part in enumerate(parts):
                suffix = f"_{i+1}" if len(parts) > 1 else ""
                part_title = f"{base_name}{suffix}"
                
                # Додаємо контекст для зв'язку між розділеними частинами
                llm_input = part
                if len(parts) > 1:
                    llm_input = f"(Примітка: Це частина {i+1} з {len(parts)} документа '{base_name}')\n\n{part}"
                
                # Форматуємо частину через LLM
                formatted_md = self.llm_manager.generate_structured_note(llm_input, concepts)
                
                # Очищуємо вихідний Markdown від блоків коду ```markdown ... ```, які іноді додає LLM
                formatted_md = re.sub(r"^```markdown\n", "", formatted_md)
                formatted_md = re.sub(r"\n```$", "", formatted_md)
                formatted_md = formatted_md.strip()
                
                # Визначаємо шлях до нового файлу в Obsidian Vault
                out_file_path = os.path.join(vault_dir, f"{part_title}.md")
                with open(out_file_path, "w", encoding="utf-8") as out_f:
                    out_f.write(formatted_md)
                print(f"Збережено структуровану нотатку: {out_file_path}")
                formatted_files.append(out_file_path)
                
                # Оновлюємо динамічний список концептів новоствореним заголовком
                concepts.append(part_title)
                
            # Переносимо оригінальний файл в архів
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, os.path.basename(file_path))
            try:
                # Якщо файл вже є в архіві, додаємо унікальний індекс
                if os.path.exists(archive_path):
                    name, ext = os.path.splitext(os.path.basename(file_path))
                    archive_path = os.path.join(archive_dir, f"{name}_archived{ext}")
                shutil.move(file_path, archive_path)
                print(f"Оригінальний файл перенесено в архів: {archive_path}")
            except Exception as e:
                print(f"[Warning] Не вдалося перемістити файл до архіву: {e}")
                
        # Автоматична індексація нових файлів
        if auto_ingest and formatted_files:
            print("\n=== Запуск автоматичної індексації сформованих нотаток ===")
            from ingestion import DocumentIngester
            from indexing import RAGIndexManager
            
            ingester = DocumentIngester(chunk_size=1000, chunk_overlap=200)
            db_manager = RAGIndexManager(db_path=self.db_path)
            
            # Індексуємо кожен створений файл
            all_chunks = []
            all_entities = []
            all_relations = []
            
            for f_path in formatted_files:
                print(f"Індексація: {os.path.basename(f_path)}...")
                res = ingester.process_file(f_path)
                all_chunks.extend(res["chunks"])
                all_entities.extend(res["entities"])
                all_relations.extend(res["relations"])
                
            ingest_result = {
                "chunks": all_chunks,
                "entities": all_entities,
                "relations": all_relations
            }
            
            print(f"Запис у SQLite: {len(all_chunks)} чанків, {len(all_entities)} сутностей...")
            db_manager.insert_ingested_data(ingest_result)
            print("Індексацію завершено успішно.")
            
        return True
