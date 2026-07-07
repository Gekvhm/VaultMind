"""Модуль гібридної індексації та пошуку.

Реалізує Vector + BM25 (FTS5) + Knowledge Graph з Reciprocal Rank Fusion.
"""

import logging
import os
import re
import sqlite3

import numpy as np
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

logger = logging.getLogger(__name__)


class RAGIndexManager:
    """Менеджер гібридного пошуку з підтримкою векторного, повнотекстового та графового пошуку."""

    def __init__(self, db_path: str = "rag_storage.db", embedding_model_path: str | None = None) -> None:
        """Ініціалізує менеджер індексації.

        Args:
            db_path: Шлях до файлу бази даних SQLite.
            embedding_model_path: Шлях до GGUF моделі ембедінгів. Якщо None — завантажується автоматично.
        """
        self.db_path = db_path
        self.embedding_model_path = embedding_model_path
        self.embed_model = None
        
    def init_db(self) -> None:
        """Ініціалізує базу даних SQLite та створює всі необхідні таблиці."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Створення основної таблиці чанків
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            heading TEXT,
            content TEXT,
            vector BLOB
        )
        """)
        
        # Створення віртуальної таблиці FTS5 для текстового пошуку BM25
        cursor.execute("DROP TABLE IF EXISTS fts_chunks")
        cursor.execute("""
        CREATE VIRTUAL TABLE fts_chunks USING fts5(
            chunk_id UNINDEXED,
            content
        )
        """)
        
        # Створення таблиць графа знань
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            type TEXT
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            target_id INTEGER,
            relation_type TEXT,
            FOREIGN KEY(source_id) REFERENCES entities(id),
            FOREIGN KEY(target_id) REFERENCES entities(id),
            UNIQUE(source_id, target_id, relation_type)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunk_entities (
            chunk_id INTEGER,
            entity_id INTEGER,
            FOREIGN KEY(chunk_id) REFERENCES chunks(id),
            FOREIGN KEY(entity_id) REFERENCES entities(id),
            PRIMARY KEY(chunk_id, entity_id)
        )
        """)
        
        conn.commit()
        conn.close()
        
    def load_embedding_model(self) -> None:
        """Завантажує модель ембедінгів GGUF з Hugging Face або локального шляху."""
        if self.embed_model is not None:
            return
            
        if self.embedding_model_path is None:
            # Створюємо директорію для моделей
            os.makedirs("models", exist_ok=True)
            logger.info("Завантаження моделі ембедінгів nomic-embed-text-v1.5 з Hugging Face...")
            self.embedding_model_path = hf_hub_download(
                repo_id="nomic-ai/nomic-embed-text-v1.5-GGUF",
                filename="nomic-embed-text-v1.5.f16.gguf",
                local_dir="models"
            )
            
        logger.info("Ініціалізація моделі ембедінгів з %s...", self.embedding_model_path)
        # Запуск моделі ембедінгів з підтримкою GPU
        self.embed_model = Llama(
            model_path=self.embedding_model_path,
            embedding=True,
            n_gpu_layers=-1, # Оффлоад на GPU
            verbose=False
        )

    def get_embedding(self, text: str) -> np.ndarray:
        """Генерує векторний ембедінг для тексту."""
        self.load_embedding_model()
        # nomic-embed потребує префіксу "search_document:" для документів та "search_query:" для запитів
        formatted_text = f"search_document: {text}"
        res = self.embed_model.create_embedding(formatted_text)
        return np.array(res['data'][0]['embedding'], dtype=np.float32)

    def get_query_embedding(self, text: str) -> np.ndarray:
        """Генерує векторний ембедінг для пошукового запиту."""
        self.load_embedding_model()
        formatted_text = f"search_query: {text}"
        res = self.embed_model.create_embedding(formatted_text)
        return np.array(res['data'][0]['embedding'], dtype=np.float32)

    def insert_ingested_data(self, ingestion_result: dict) -> None:
        """Записує результати інгестії у базу даних та генерує ембедінги."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        chunks = ingestion_result["chunks"]
        entities = ingestion_result["entities"]
        relations = ingestion_result["relations"]
        
        # 1. Вставка сутностей
        entity_name_to_id = {}
        for name, ent_type in entities:
            cursor.execute("""
            INSERT INTO entities (name, type) 
            VALUES (?, ?) 
            ON CONFLICT(name) DO UPDATE SET type=excluded.type
            """, (name, ent_type))
            
            cursor.execute("SELECT id FROM entities WHERE name = ?", (name,))
            entity_name_to_id[name] = cursor.fetchone()[0]
            
        # 2. Вставка зв'язків графа
        for src, rel, tgt in relations:
            src_id = entity_name_to_id.get(src)
            tgt_id = entity_name_to_id.get(tgt)
            if src_id and tgt_id:
                cursor.execute("""
                INSERT OR IGNORE INTO relationships (source_id, target_id, relation_type)
                VALUES (?, ?, ?)
                """, (src_id, tgt_id, rel))
                
        # 3. Вставка чанків та генерація їхніх векторів
        for i, chunk in enumerate(chunks):
            content = chunk["content"]
            file_path = chunk["file_path"]
            heading = chunk["heading"]
            chunk_entities = chunk["entities"]
            
            logger.info("Індексація чанку %d/%d (Розмір: %d символів)...", i + 1, len(chunks), len(content))
            vector = self.get_embedding(content)
            vector_blob = vector.tobytes()
            
            cursor.execute("""
            INSERT INTO chunks (file_path, heading, content, vector)
            VALUES (?, ?, ?, ?)
            """, (file_path, heading, content, vector_blob))
            
            chunk_id = cursor.lastrowid
            
            # Вставка у FTS5 індекс
            cursor.execute("""
            INSERT INTO fts_chunks (chunk_id, content)
            VALUES (?, ?)
            """, (chunk_id, content))
            
            # Зв'язування чанку з сутностями
            for ent_name, _ in chunk_entities:
                ent_id = entity_name_to_id.get(ent_name)
                if ent_id:
                    cursor.execute("""
                    INSERT OR IGNORE INTO chunk_entities (chunk_id, entity_id)
                    VALUES (?, ?)
                    """, (chunk_id, ent_id))
                    
        conn.commit()
        conn.close()
        logger.info("Індексацію бази знань завершено успішно.")

    def search_vector(self, query_text: str, limit: int = 10) -> list[dict]:
        """Здійснює семантичний векторний пошук у базі даних SQLite через numpy."""
        query_vec = self.get_query_embedding(query_text)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content, vector, file_path, heading FROM chunks")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
            
        chunk_ids = []
        contents = []
        vectors = []
        file_paths = []
        headings = []
        
        for row in rows:
            chunk_ids.append(row[0])
            contents.append(row[1])
            vectors.append(np.frombuffer(row[2], dtype=np.float32))
            file_paths.append(row[3])
            headings.append(row[4])
            
        vectors_np = np.stack(vectors)
        
        # Обчислення косинусної схожості
        dot_product = np.dot(vectors_np, query_vec)
        norms = np.linalg.norm(vectors_np, axis=1) * np.linalg.norm(query_vec)
        # Запобігання діленню на 0
        norms[norms == 0] = 1e-10
        similarities = dot_product / norms
        
        # Сортування
        sorted_indices = np.argsort(similarities)[::-1][:limit]
        
        results = []
        for idx in sorted_indices:
            results.append({
                "chunk_id": chunk_ids[idx],
                "content": contents[idx],
                "score": float(similarities[idx]),
                "file_path": file_paths[idx],
                "heading": headings[idx]
            })
        return results

    def search_bm25(self, query_text: str, limit: int = 10) -> list[dict]:
        """Швидкий повнотекстовий пошук BM25 через SQLite FTS5."""
        # Очищення запиту від спецсимволів FTS5 для безпеки
        clean_query = re.sub(r'[^\w\s]', ' ', query_text).strip()
        if not clean_query:
            return []
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # SQLite FTS5 використовує 'bm25' функцію для розрахунку рангу (чим менше значення, тим кращий збіг)
        cursor.execute("""
        SELECT f.chunk_id, f.content, c.file_path, c.heading, f.rank
        FROM fts_chunks f
        JOIN chunks c ON f.chunk_id = c.id
        WHERE fts_chunks MATCH ?
        ORDER BY rank
        LIMIT ?
        """, (clean_query, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            # Перетворюємо ранг FTS5 на позитивний скор (1.0 / (1.0 + rank))
            rank = row[4]
            score = 1.0 / (1.0 + abs(rank))
            results.append({
                "chunk_id": row[0],
                "content": row[1],
                "file_path": row[2],
                "heading": row[3],
                "score": score
            })
        return results

    def get_query_entities(self, query_text: str) -> list[dict]:
        """Визначає сутності, присутні в запиті користувача, на основі бази знань."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type FROM entities")
        all_entities = cursor.fetchall()
        conn.close()
        
        matched_entities = []
        for ent_id, name, ent_type in all_entities:
            # Регістронезалежний пошук точного збігу
            if name.lower() in query_text.lower() and len(name) > 2:
                matched_entities.append({"id": ent_id, "name": name, "type": ent_type})
        return matched_entities

    def hybrid_search_rrf(self, query_text: str, limit: int = 5, k: int = 60, graph_boost: float = 1.5) -> list[dict]:
        """Гібридний пошук: злиття Vector + BM25 за методом RRF з графовим підсиленням."""
        # 1. Отримуємо результати з обох пошуковиків
        vector_res = self.search_vector(query_text, limit=limit*3)
        bm25_res = self.search_bm25(query_text, limit=limit*3)
        
        # 2. Виділяємо сутності запиту для графової валідації
        query_entities = self.get_query_entities(query_text)
        query_entity_ids = [ent["id"] for ent in query_entities]
        
        # Побудова словників для RRF
        scores = {}
        meta_cache = {}
        
        # Ранг у векторному пошуку
        for rank, res in enumerate(vector_res):
            cid = res["chunk_id"]
            meta_cache[cid] = {
                "content": res["content"],
                "file_path": res["file_path"],
                "heading": res["heading"]
            }
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))
            
        # Ранг у BM25 пошуку
        for rank, res in enumerate(bm25_res):
            cid = res["chunk_id"]
            meta_cache[cid] = {
                "content": res["content"],
                "file_path": res["file_path"],
                "heading": res["heading"]
            }
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))
            
        # 3. Графове підсилення (Graph Grounding)
        if query_entity_ids:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for cid in list(scores.keys()):
                # Перевіряємо сутності, пов'язані з поточним чанком
                cursor.execute("SELECT entity_id FROM chunk_entities WHERE chunk_id = ?", (cid,))
                chunk_ent_ids = [row[0] for row in cursor.fetchall()]
                
                # Шукаємо перетин або зв'язок 1-го порядку між сутностями запиту та чанку
                has_connection = False
                for q_ent_id in query_entity_ids:
                    if q_ent_id in chunk_ent_ids:
                        has_connection = True
                        break
                    
                    # Перевіряємо зв'язок 1-го порядку в таблиці relationships
                    if chunk_ent_ids:
                        placeholders = ','.join('?' for _ in chunk_ent_ids)
                        query = f"""
                        SELECT COUNT(*) FROM relationships 
                        WHERE (source_id = ? AND target_id IN ({placeholders}))
                           OR (target_id = ? AND source_id IN ({placeholders}))
                        """
                        params = [q_ent_id] + chunk_ent_ids + [q_ent_id] + chunk_ent_ids
                        cursor.execute(query, params)
                        
                        if cursor.fetchone()[0] > 0:
                            has_connection = True
                            break
                        
                # Бустимо RRF скор, якщо знайдено логічний зв'язок у графі знань
                if has_connection:
                    scores[cid] = scores[cid] * graph_boost
                    
            conn.close()
            
        # Сортування фінальних результатів RRF
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        final_results = []
        for cid, score in sorted_scores:
            final_results.append({
                "chunk_id": cid,
                "content": meta_cache[cid]["content"],
                "file_path": meta_cache[cid]["file_path"],
                "heading": meta_cache[cid]["heading"],
                "score": score
            })
            
        return final_results
