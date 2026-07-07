"""FastAPI сервер VaultMind. Надає REST API, OpenAI-сумісні ендпоінти та веб-інтерфейс для управління воркспейсами."""
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import urllib.request
from urllib.parse import urlparse

import psutil
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ingestion import DocumentIngester
from indexing import RAGIndexManager
from inference import LLMInferenceManager
from formatter import KnowledgeFormatter

logger = logging.getLogger(__name__)

# --- Автентифікація через API-ключ ---
API_KEY_FILE = ".vaultmind_key"


def _load_or_generate_api_key() -> str:
    """Завантажує API-ключ з файлу або генерує новий при першому запуску."""
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    key = f"vm-{secrets.token_urlsafe(32)}"
    with open(API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    os.chmod(API_KEY_FILE, 0o600)
    logger.info("Згенеровано новий API-ключ: %s", API_KEY_FILE)
    return key


API_KEY = _load_or_generate_api_key()


async def verify_api_key(request: Request) -> None:
    """Перевіряє API-ключ з заголовків Authorization (Bearer) або X-API-Key."""
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")

    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif api_key_header:
        token = api_key_header

    if not secrets.compare_digest(token, API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Use 'Authorization: Bearer <key>' or 'X-API-Key: <key>' header.",
        )

app = FastAPI(
    title="VaultMind API",
    description="REST API для управління локальними воркспейсами, джерелами та RAG-запитами",
    version="0.1.0"
)

# Налаштування CORS — лише локальні джерела
CORS_ORIGINS = [
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_headers=["Content-Type", "Authorization"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
)

WORKSPACES_DIR = "workspaces"
os.makedirs(WORKSPACES_DIR, exist_ok=True)

# Глобальний стан для активного воркспейсу по замовчуванню
ACTIVE_WORKSPACE = "default"

# Допоміжна функція для ініціалізації default воркспейсу при старті
def ensure_default_workspace() -> None:
    """Створює воркспейс 'default' якщо він не існує."""
    global ACTIVE_WORKSPACE
    default_path = os.path.join(WORKSPACES_DIR, "default")
    if not os.path.exists(default_path):
        # Створюємо default воркспейс
        os.makedirs(default_path, exist_ok=True)
        os.makedirs(os.path.join(default_path, "vault"), exist_ok=True)
        os.makedirs(os.path.join(default_path, "raw_inputs"), exist_ok=True)
        os.makedirs(os.path.join(default_path, "raw_inputs", ".archive"), exist_ok=True)
        
        default_config = {
            "provider": "local",
            "local_model_path": "models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "openai_api_key": "",
            "openai_base_url": "",
            "openai_model_name": "",
            "context_size": 8192,
            "rrf_threshold": 0.015
        }
        with open(os.path.join(default_path, "config.json"), "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
            
        manager = RAGIndexManager(db_path=os.path.join(default_path, "rag_storage.db"))
        manager.init_db()
        logger.info("Default воркспейс успішно ініціалізовано.")

ensure_default_workspace()

# --- Моделі запитів Pydantic ---
class WorkspaceCreate(BaseModel):
    """Модель запиту на створення нового воркспейсу."""
    name: str

class SettingsUpdate(BaseModel):
    """Модель запиту на оновлення налаштувань воркспейсу."""
    provider: str
    local_model_path: Optional[str] = ""
    openai_api_key: Optional[str] = ""
    openai_base_url: Optional[str] = ""
    openai_model_name: Optional[str] = ""
    context_size: Optional[int] = 8192
    rrf_threshold: Optional[float] = 0.015

class QueryRequest(BaseModel):
    """Модель запиту для RAG-пошуку."""
    query: str

# Моделі OpenAI-сумісних запитів
class ChatMessage(BaseModel):
    """Повідомлення в форматі OpenAI Chat API."""
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    """Запит до OpenAI-сумісного ендпоінту чат-комплішенів."""
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = 1024


class IngestTextRequest(BaseModel):
    """Запит на пряму інгестію тексту без файлу."""
    text: str
    filename: str = "untitled.md"
    auto_structure: bool = False


class IngestUrlRequest(BaseModel):
    """Запит на завантаження та інгестію контенту з URL."""
    url: str
    filename: str = ""

# --- Допоміжні функції воркспейсів ---
def get_workspace_path(ws_id: str) -> str:
    """Повертає безпечний шлях до директорії воркспейсу."""
    # Захист від Path Traversal
    safe_id = re.sub(r'[^\w\-]', '_', ws_id)
    return os.path.join(WORKSPACES_DIR, safe_id)

def load_workspace_config(ws_id: str) -> dict:
    """Завантажує конфігурацію воркспейсу з config.json."""
    ws_path = get_workspace_path(ws_id)
    cfg_file = os.path.join(ws_path, "config.json")
    if not os.path.exists(cfg_file):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
    with open(cfg_file, "r", encoding="utf-8") as f:
        return json.load(f)

# --- Ендпоінти управління воркспейсами ---

@app.get("/api/workspaces")
def list_workspaces(_: None = Depends(verify_api_key)) -> dict:
    """Повертає список усіх наявних воркспейсів."""
    ensure_default_workspace()
    workspaces = []
    for d in os.listdir(WORKSPACES_DIR):
        d_path = os.path.join(WORKSPACES_DIR, d)
        if os.path.isdir(d_path) and os.path.exists(os.path.join(d_path, "config.json")):
            workspaces.append(d)
    return {"workspaces": sorted(workspaces), "active_workspace": ACTIVE_WORKSPACE}

@app.post("/api/active_workspace")
def set_active_workspace(ws: WorkspaceCreate, _: None = Depends(verify_api_key)) -> dict:
    """Встановлює активний воркспейс по замовчуванню."""
    global ACTIVE_WORKSPACE
    ws_path = get_workspace_path(ws.name)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не існує.")
    ACTIVE_WORKSPACE = ws.name
    return {"status": "success", "active_workspace": ACTIVE_WORKSPACE}

@app.post("/api/workspaces")
def create_workspace(ws: WorkspaceCreate, _: None = Depends(verify_api_key)) -> dict:
    """Створює новий воркспейс та ініціалізує його структуру."""
    if not ws.name.strip():
        raise HTTPException(status_code=400, detail="Назва воркспейсу не може бути порожньою.")
        
    ws_id = re.sub(r'[^\w\-]', '_', ws.name.strip())
    ws_path = get_workspace_path(ws_id)
    
    if os.path.exists(ws_path):
        raise HTTPException(status_code=400, detail="Воркспейс із такою назвою вже існує.")
        
    try:
        os.makedirs(ws_path, exist_ok=True)
        os.makedirs(os.path.join(ws_path, "vault"), exist_ok=True)
        os.makedirs(os.path.join(ws_path, "raw_inputs"), exist_ok=True)
        os.makedirs(os.path.join(ws_path, "raw_inputs", ".archive"), exist_ok=True)
        
        # Створення базової конфігурації
        default_config = {
            "provider": "local",
            "local_model_path": "models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "openai_api_key": "",
            "openai_base_url": "",
            "openai_model_name": "",
            "context_size": 8192,
            "rrf_threshold": 0.015
        }
        with open(os.path.join(ws_path, "config.json"), "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
            
        # Ініціалізація SQLite
        manager = RAGIndexManager(db_path=os.path.join(ws_path, "rag_storage.db"))
        manager.init_db()
        
        global ACTIVE_WORKSPACE
        ACTIVE_WORKSPACE = ws_id
        
        return {"status": "success", "workspace_id": ws_id}
    except (OSError, sqlite3.Error) as e:
        if os.path.exists(ws_path):
            shutil.rmtree(ws_path)
        raise HTTPException(status_code=500, detail=f"Не вдалося створити воркспейс: {str(e)}")

@app.delete("/api/workspaces/{ws_id}")
def delete_workspace(ws_id: str, _: None = Depends(verify_api_key)) -> dict:
    """Повністю видаляє воркспейс та його дані."""
    if ws_id == "default":
        raise HTTPException(status_code=400, detail="Неможливо видалити воркспейс по замовчуванню (default).")
        
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    try:
        shutil.rmtree(ws_path)
        global ACTIVE_WORKSPACE
        if ACTIVE_WORKSPACE == ws_id:
            ACTIVE_WORKSPACE = "default"
        return {"status": "success"}
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Помилка при видаленні: {str(e)}")

# --- Ендпоінти роботи всередині воркспейсу ---

@app.get("/api/workspaces/{ws_id}/status")
def get_workspace_status(ws_id: str, _: None = Depends(verify_api_key)) -> dict:
    """Повертає статистику бази знань та параметри воркспейсу."""
    ws_path = get_workspace_path(ws_id)
    db_path = os.path.join(ws_path, "rag_storage.db")
    
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    config = load_workspace_config(ws_id)
    
    # Замір метрик бази SQLite
    chunks_count = 0
    entities_count = 0
    relations_count = 0
    sources = set()
    
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            chunks_count = cursor.execute("SELECT count(*) FROM chunks").fetchone()[0]
            entities_count = cursor.execute("SELECT count(*) FROM entities").fetchone()[0]
            relations_count = cursor.execute("SELECT count(*) FROM relationships").fetchone()[0]
            rows = cursor.execute("SELECT DISTINCT file_path FROM chunks").fetchall()
            for r in rows:
                if r[0]:
                    sources.add(os.path.basename(r[0]))
            conn.close()
        except sqlite3.Error as e:
            logger.error("Error querying SQLite stats: %s", e)
            
    process = psutil.Process(os.getpid())
    ram_mb = process.memory_info().rss / (1024 * 1024)
    
    return {
        "workspace_id": ws_id,
        "active_model": {
            "provider": config.get("provider"),
            "model_name": config.get("openai_model_name") if config.get("provider") == "openai" else os.path.basename(config.get("local_model_path", ""))
        },
        "statistics": {
            "sources_count": len(sources),
            "chunks_count": chunks_count,
            "entities_count": entities_count,
            "relationships_count": relations_count
        },
        "system": {
            "ram_usage_mb": round(ram_mb, 2)
        }
    }

@app.get("/api/workspaces/{ws_id}/config")
def get_config(ws_id: str, _: None = Depends(verify_api_key)) -> dict:
    """Повертає конфігурацію воркспейсу."""
    return load_workspace_config(ws_id)

@app.post("/api/workspaces/{ws_id}/settings")
def update_settings(ws_id: str, settings: SettingsUpdate, _: None = Depends(verify_api_key)) -> dict:
    """Оновлює конфігурацію воркспейсу."""
    ws_path = get_workspace_path(ws_id)
    cfg_file = os.path.join(ws_path, "config.json")
    
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    try:
        config = {
            "provider": settings.provider,
            "local_model_path": settings.local_model_path,
            "openai_api_key": settings.openai_api_key,
            "openai_base_url": settings.openai_base_url,
            "openai_model_name": settings.openai_model_name,
            "context_size": settings.context_size,
            "rrf_threshold": settings.rrf_threshold
        }
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return {"status": "success", "config": config}
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Помилка при оновленні налаштувань: {str(e)}")

@app.get("/api/workspaces/{ws_id}/sources")
def list_sources(ws_id: str, _: None = Depends(verify_api_key)) -> dict:
    """Повертає список усіх проіндексованих файлів у воркспейсі."""
    ws_path = get_workspace_path(ws_id)
    db_path = os.path.join(ws_path, "rag_storage.db")
    
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    sources = []
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Зчитуємо файли
            rows = cursor.execute("""
                SELECT DISTINCT file_path 
                FROM chunks
            """).fetchall()
            for r in rows:
                if r[0]:
                    file_name = os.path.basename(r[0])
                    # Рахуємо чанки для цього файлу
                    chunks_c = cursor.execute("SELECT count(*) FROM chunks WHERE file_path = ?", (r[0],)).fetchone()[0]
                    sources.append({"name": file_name, "path": r[0], "chunks_count": chunks_c})
            conn.close()
        except sqlite3.Error as e:
            logger.error("Error querying SQLite sources: %s", e)
            
    return {"sources": sources}

@app.delete("/api/workspaces/{ws_id}/sources/{source_name}")
def delete_source(ws_id: str, source_name: str, _: None = Depends(verify_api_key)) -> dict:
    """Видаляє джерело з Obsidian Vault та очищує його чанки й сутності з БД."""
    ws_path = get_workspace_path(ws_id)
    db_path = os.path.join(ws_path, "rag_storage.db")
    vault_dir = os.path.join(ws_path, "vault")
    
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    target_md_path = os.path.join(vault_dir, source_name)
    if not target_md_path.endswith(".md"):
        target_md_path += ".md"
        
    # 1. Очищення бази даних SQLite
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Шукаємо ID чанків, які належать цьому файлу
            cursor.execute("SELECT id FROM chunks WHERE file_path LIKE ?", (f"%{source_name}%",))
            chunk_ids = [row[0] for row in cursor.fetchall()]
            
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                # Видаляємо зв'язки чанків із сутностями
                cursor.execute(f"DELETE FROM chunk_entities WHERE chunk_id IN ({placeholders})", chunk_ids)
                # Видаляємо чанки
                cursor.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", chunk_ids)
                # Видаляємо з FTS5
                cursor.execute(f"DELETE FROM fts_chunks WHERE chunk_id IN ({placeholders})", chunk_ids)
                
                # Очищення сирітських (unreferenced) сутностей та зв'язків
                cursor.execute("""
                    DELETE FROM entities 
                    WHERE id NOT IN (SELECT DISTINCT entity_id FROM chunk_entities)
                      AND type != 'Metadata'
                """)
                cursor.execute("""
                    DELETE FROM relationships 
                    WHERE source_id NOT IN (SELECT id FROM entities) 
                       OR target_id NOT IN (SELECT id FROM entities)
                """)
                
            conn.commit()
            conn.close()
            logger.info("Базу SQLite очищено від джерела %s.", source_name)
        except sqlite3.Error as e:
            logger.error("Очищення SQLite не вдалося: %s", e)
            
    # 2. Видалення файлу з диска
    if os.path.exists(target_md_path):
        try:
            os.remove(target_md_path)
            return {"status": "success", "deleted_file": target_md_path}
        except (OSError, PermissionError) as e:
            raise HTTPException(status_code=500, detail=f"Помилка при видаленні файлу: {str(e)}")
            
    return {"status": "success", "message": "Дані вилучено з бази, файл не був знайдений на диску."}

@app.post("/api/workspaces/{ws_id}/upload")
async def upload_files(ws_id: str, files: List[UploadFile] = File(...), _: None = Depends(verify_api_key)) -> dict:
    """Завантажує сирі файли у воркспейс, структурує їх та автоматично індексує."""
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    config = load_workspace_config(ws_id)
    raw_inputs_dir = os.path.join(ws_path, "raw_inputs")
    vault_dir = os.path.join(ws_path, "vault")
    db_path = os.path.join(ws_path, "rag_storage.db")
    
    saved_paths = []
    for file in files:
        safe_filename = re.sub(r'[^\w\-\.]', '_', file.filename)
        dest_path = os.path.join(raw_inputs_dir, safe_filename)
        try:
            with open(dest_path, "wb") as f:
                content = await file.read()
                f.write(content)
            saved_paths.append(dest_path)
        except (OSError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=500, detail=f"Не вдалося зберегти файл {file.filename}: {str(e)}")
            
    # Запуск конвеєру структурування KnowledgeFormatter
    try:
        formatter = KnowledgeFormatter(
            db_path=db_path,
            llm_config=config
        )
        for file_path in saved_paths:
            formatter.process_raw_data(
                input_path=file_path,
                vault_dir=vault_dir,
                auto_ingest=True
            )
        return {"status": "success", "processed_files": [os.path.basename(p) for p in saved_paths]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка конвеєра структурування: {str(e)}")

@app.post("/api/workspaces/{ws_id}/query")
def query_workspace(ws_id: str, req: QueryRequest, _: None = Depends(verify_api_key)) -> dict:
    """Пошук фактів та генерація відповіді в межах конкретного воркспейсу."""
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")
        
    config = load_workspace_config(ws_id)
    db_path = os.path.join(ws_path, "rag_storage.db")
    
    # 1. Гібридний пошук
    db_manager = RAGIndexManager(db_path=db_path)
    chunks = db_manager.hybrid_search_rrf(req.query, limit=5, graph_boost=1.5)
    
    # 2. LLM Генерація
    inference = LLMInferenceManager(config=config)
    response = inference.generate_response(req.query, chunks)
    
    # Повертаємо і відповідь, і чанки для візуалізації джерел у UI
    serializable_chunks = []
    for c in chunks:
        serializable_chunks.append({
            "file_name": os.path.basename(c["file_path"]),
            "heading": c["heading"],
            "content": c["content"],
            "score": c["score"]
        })
        
    return {"response": response, "context": serializable_chunks}

@app.post("/api/workspaces/{ws_id}/ingest-text")
def ingest_text(ws_id: str, req: IngestTextRequest, _: None = Depends(verify_api_key)) -> dict:
    """Пряма інгестія тексту у воркспейс без завантаження файлу."""
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")

    config = load_workspace_config(ws_id)
    vault_dir = os.path.join(ws_path, "vault")
    db_path = os.path.join(ws_path, "rag_storage.db")

    safe_filename = re.sub(r'[^\w\-\.]', '_', req.filename)
    if not safe_filename.endswith(('.md', '.txt')):
        safe_filename += '.md'

    if req.auto_structure:
        # Зберігаємо у raw_inputs та пропускаємо через KnowledgeFormatter
        raw_inputs_dir = os.path.join(ws_path, "raw_inputs")
        file_path = os.path.join(raw_inputs_dir, safe_filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(req.text)
        try:
            formatter = KnowledgeFormatter(db_path=db_path, llm_config=config)
            formatter.process_raw_data(input_path=file_path, vault_dir=vault_dir, auto_ingest=True)
            return {"status": "success", "filename": safe_filename, "mode": "structured"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Помилка структурування: {str(e)}")
    else:
        # Прямий запис у vault та індексація
        file_path = os.path.join(vault_dir, safe_filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(req.text)

        ingester = DocumentIngester()
        result = ingester.process_file(file_path)

        manager = RAGIndexManager(db_path=db_path)
        manager.init_db()
        manager.insert_ingested_data(result)

        return {
            "status": "success",
            "filename": safe_filename,
            "mode": "direct",
            "chunks": len(result["chunks"]),
            "entities": len(result["entities"]),
        }


@app.post("/api/workspaces/{ws_id}/ingest-url")
def ingest_url(ws_id: str, req: IngestUrlRequest, _: None = Depends(verify_api_key)) -> dict:
    """Завантажує контент з URL та індексує його у воркспейсі."""
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")

    # Завантаження контенту з URL
    try:
        req_obj = urllib.request.Request(req.url, headers={"User-Agent": "VaultMind/0.1"})
        with urllib.request.urlopen(req_obj, timeout=30) as response:
            content = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не вдалося завантажити URL: {str(e)}")

    # Генерація імені файлу з URL якщо не вказано
    if not req.filename:
        parsed = urlparse(req.url)
        path_part = parsed.path.strip("/").replace("/", "_") or parsed.netloc
        filename = re.sub(r'[^\w\-\.]', '_', path_part)
        if not filename.endswith(('.md', '.txt')):
            filename += '.md'
    else:
        filename = re.sub(r'[^\w\-\.]', '_', req.filename)
        if not filename.endswith(('.md', '.txt')):
            filename += '.md'

    vault_dir = os.path.join(ws_path, "vault")
    db_path = os.path.join(ws_path, "rag_storage.db")
    file_path = os.path.join(vault_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"---\nsource: {req.url}\n---\n\n{content}")

    ingester = DocumentIngester()
    result = ingester.process_file(file_path)

    manager = RAGIndexManager(db_path=db_path)
    manager.init_db()
    manager.insert_ingested_data(result)

    return {
        "status": "success",
        "filename": filename,
        "url": req.url,
        "chunks": len(result["chunks"]),
        "entities": len(result["entities"]),
        "content_length": len(content),
    }


@app.get("/api/workspaces/{ws_id}/entities")
def get_entities(ws_id: str, entity_type: str = "", limit: int = 100, _: None = Depends(verify_api_key)) -> dict:
    """Повертає список сутностей та зв'язків графу знань воркспейсу."""
    ws_path = get_workspace_path(ws_id)
    if not os.path.exists(ws_path):
        raise HTTPException(status_code=404, detail="Воркспейс не знайдено.")

    db_path = os.path.join(ws_path, "rag_storage.db")
    if not os.path.exists(db_path):
        return {"entities": [], "relationships": [], "stats": {"total_entities": 0, "total_relationships": 0}}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Отримання сутностей
    if entity_type:
        cursor.execute("SELECT id, name, type FROM entities WHERE type = ? LIMIT ?", (entity_type, limit))
    else:
        cursor.execute("SELECT id, name, type FROM entities LIMIT ?", (limit,))
    entities = [{"id": row[0], "name": row[1], "type": row[2]} for row in cursor.fetchall()]

    # Отримання зв'язків
    entity_ids = [e["id"] for e in entities]
    relationships = []
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        cursor.execute(f"""
            SELECT r.id, s.name, r.relation_type, t.name
            FROM relationships r
            JOIN entities s ON r.source_id = s.id
            JOIN entities t ON r.target_id = t.id
            WHERE r.source_id IN ({placeholders}) OR r.target_id IN ({placeholders})
            LIMIT ?
        """, entity_ids + entity_ids + [limit])
        relationships = [
            {"id": row[0], "source": row[1], "relation": row[2], "target": row[3]}
            for row in cursor.fetchall()
        ]

    # Статистика
    cursor.execute("SELECT COUNT(*) FROM entities")
    total_entities = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM relationships")
    total_relationships = cursor.fetchone()[0]

    conn.close()

    return {
        "entities": entities,
        "relationships": relationships,
        "stats": {
            "total_entities": total_entities,
            "total_relationships": total_relationships,
        }
    }

# --- OpenAI-сумісні ендпоінти ---

def run_rag_inference(ws_id: str, user_query: str) -> str:
    """Виконує повний RAG-пайплайн: пошук контексту та генерацію відповіді LLM."""
    ws_path = get_workspace_path(ws_id)
    db_path = os.path.join(ws_path, "rag_storage.db")
    config = load_workspace_config(ws_id)
    
    db_manager = RAGIndexManager(db_path=db_path)
    chunks = db_manager.hybrid_search_rrf(user_query, limit=5)
    
    inference = LLMInferenceManager(config=config)
    return inference.generate_response(user_query, chunks)

@app.post("/v1/chat/completions")
def openai_chat_completions_active(req: ChatCompletionRequest, _: None = Depends(verify_api_key)) -> dict:
    """OpenAI-сумісний інтерфейс RAG для АКТИВНОГО воркспейсу."""
    global ACTIVE_WORKSPACE
    ensure_default_workspace()
    user_query = req.messages[-1].content
    
    logger.info("[API OpenAI] Отримано запит до активного воркспейсу '%s'", ACTIVE_WORKSPACE)
    answer = run_rag_inference(ACTIVE_WORKSPACE, user_query)
    
    return {
        "id": "chatcmpl-localrag",
        "object": "chat.completion",
        "created": 1677652288,
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer
            },
            "finish_reason": "stop"
        }]
    }

@app.post("/workspaces/{ws_id}/v1/chat/completions")
def openai_chat_completions_specific(ws_id: str, req: ChatCompletionRequest, _: None = Depends(verify_api_key)) -> dict:
    """OpenAI-сумісний інтерфейс RAG для КОНКРЕТНОГО воркспейсу."""
    user_query = req.messages[-1].content
    
    logger.info("[API OpenAI] Отримано запит до конкретного воркспейсу '%s'", ws_id)
    answer = run_rag_inference(ws_id, user_query)
    
    return {
        "id": f"chatcmpl-{ws_id}",
        "object": "chat.completion",
        "created": 1677652288,
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer
            },
            "finish_reason": "stop"
        }]
    }

# Маршрутизація UI (Static Files)
@app.get("/", response_class=HTMLResponse)
def read_root() -> HTMLResponse:
    """Повертає головну HTML-сторінку веб-інтерфейсу з вбудованим API-ключем."""
    index_html_path = "templates/index.html"
    if os.path.exists(index_html_path):
        with open(index_html_path, "r", encoding="utf-8") as f:
            html = f.read()
        # Вбудовуємо API-ключ у HTML для автоматичної автентифікації UI
        key_script = f'<script>window.__VAULTMIND_API_KEY__ = "{API_KEY}";</script>'
        html = html.replace("</head>", f"{key_script}\n</head>", 1)
        return HTMLResponse(content=html)
    return HTMLResponse(content="""
    <html>
        <head><title>VaultMind UI</title></head>
        <body>
            <h2>Dashboard HTML templates/index.html is missing.</h2>
        </body>
    </html>
    """)

if os.path.exists("templates"):
    app.mount("/static", StaticFiles(directory="templates"), name="static")
