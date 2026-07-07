#!/usr/bin/env python3
"""CLI-інтерфейс VaultMind. Надає команди для ініціалізації, інгестії, форматування, пошуку та запуску сервера."""
import argparse
import logging
import sys
import os

# TODO: Remove after switching to package install
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion import DocumentIngester
from indexing import RAGIndexManager
from inference import LLMInferenceManager

logger = logging.getLogger(__name__)


def cmd_init(args: argparse.Namespace) -> None:
    """Ініціалізує базу даних та завантажує моделі ембедінгів."""
    logger.info("=== Ініціалізація бази знань SQLite ===")
    manager = RAGIndexManager(db_path=args.db)
    manager.init_db()
    logger.info("Базу даних ініціалізовано за шляхом: %s", args.db)

def cmd_ingest(args: argparse.Namespace) -> None:
    """Виконує інгестію документів з вказаної директорії у RAG-індекс."""
    if not os.path.exists(args.path):
        logger.error("Помилка: Шлях '%s' не існує.", args.path)
        sys.exit(1)
        
    logger.info("=== Запуск інгестії даних: %s ===", args.path)
    ingester = DocumentIngester(chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    
    if os.path.isdir(args.path):
        result = ingester.process_directory(args.path)
    else:
        # Для окремого файлу створюємо сумісну структуру
        file_res = ingester.process_file(args.path)
        result = {
            "chunks": file_res["chunks"],
            "entities": file_res["entities"],
            "relations": file_res["relations"]
        }
        
    logger.info(
        "Оброблено: %d чанків, %d сутностей, %d зв'язків графа.",
        len(result['chunks']), len(result['entities']), len(result['relations']),
    )
    
    # Записуємо в базу знань та генеруємо вектори
    manager = RAGIndexManager(db_path=args.db)
    # Якщо користувач вказав шлях до моделі ембедінгів, передаємо її
    if args.embed_model:
        manager.embedding_model_path = args.embed_model
    manager.insert_ingested_data(result)

def cmd_query(args: argparse.Namespace) -> None:
    """Виконує пошуковий запит до RAG-системи та генерує відповідь LLM."""
    logger.info("=== Пошук та генерація для запиту: '%s' ===", args.query)
    manager = RAGIndexManager(db_path=args.db)
    if args.embed_model:
        manager.embedding_model_path = args.embed_model
        
    # Виконуємо гібридний пошук
    logger.info("Виконання гібридного пошуку (Vector + BM25 + Graph)...")
    chunks = manager.hybrid_search_rrf(args.query, limit=args.limit, graph_boost=args.graph_boost)
    
    if not chunks:
        print("\nРезультат:")
        print("[NO_CONTEXT_FOUND]")
        return
        
    if args.show_context:
        print("\n--- Знайдений контекст (Top Chunks) ---")
        for i, c in enumerate(chunks):
            print(f"[{i+1}] Файл: {os.path.basename(c['file_path'])} | Заголовок: {c['heading']} | Скор RRF: {c['score']:.4f}")
            print(f"Зміст: {c['content'][:150]}...")
            print("-" * 40)
            
    # Запуск LLM-інференсу
    inference = LLMInferenceManager(model_path=args.llm_model)
    response = inference.generate_response(args.query, chunks, rrf_threshold=args.threshold)
    
    print("\nРезультат:")
    print("=" * 60)
    print(response)
    print("=" * 60)

def cmd_format(args: argparse.Namespace) -> None:
    """Автоматично структурує сирі документи через LLM у Obsidian-нотатки."""
    if not os.path.exists(args.path):
        logger.error("Помилка: Шлях '%s' не існує.", args.path)
        sys.exit(1)
        
    logger.info("=== Запуск структурування сирих даних: %s ===", args.path)
    from formatter import KnowledgeFormatter
    
    formatter = KnowledgeFormatter(db_path=args.db, llm_model_path=args.llm_model)
    success = formatter.process_raw_data(
        input_path=args.path,
        vault_dir=args.out_dir,
        auto_ingest=args.auto_ingest
    )
    if success:
        logger.info("Процес структурування та наповнення бази завершено успішно.")
    else:
        logger.error("Під час структурування виникли помилки.")

def cmd_serve(args: argparse.Namespace) -> None:
    """Запускає FastAPI веб-сервер з UI та REST API."""
    logger.info("=== Запуск RAG-сервера 'NotebookLM' на %s:%s ===", args.host, args.port)
    import uvicorn
    uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload)

def main() -> None:
    """Головна точка входу CLI: парсить аргументи та делегує відповідній команді."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Локальна RAG-система з нульовим витоком знань та Metal прискоренням"
    )
    parser.add_argument(
        "--db", 
        default="rag_storage.db", 
        help="Шлях до файлу бази даних SQLite (за замовчуванням: rag_storage.db)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Команди системи")
    
    # Підкоманда init
    subparsers.add_parser("init", help="Ініціалізувати базу даних SQLite")
    
    # Підкоманда ingest
    parser_ingest = subparsers.add_parser("ingest", help="Індексувати файли або директорії")
    parser_ingest.add_argument("path", help="Шлях до файлу або папки для індексування")
    parser_ingest.add_argument("--chunk-size", type=int, default=1000, help="Розмір чанку в символах")
    parser_ingest.add_argument("--chunk-overlap", type=int, default=200, help="Накладання чанків")
    parser_ingest.add_argument("--embed-model", default=None, help="Локальний шлях до GGUF моделі ембедінгів")
    
    # Підкоманда format
    parser_format = subparsers.add_parser("format", help="Структурувати сирі тексти у замітки Obsidian та наповнити базу")
    parser_format.add_argument("path", help="Шлях до сирого файлу або папки для структурування")
    parser_format.add_argument("--out-dir", required=True, help="Папка призначення (Obsidian Vault)")
    parser_format.add_argument("--auto-ingest", action="store_true", help="Автоматично запустити індексацію після форматування")
    parser_format.add_argument("--llm-model", default=None, help="Локальний шлях до GGUF моделі LLM")

    # Підкоманда query
    parser_query = subparsers.add_parser("query", help="Запитати систему RAG")
    parser_query.add_argument("query", help="Текст запитання")
    parser_query.add_argument("--limit", type=int, default=5, help="Кількість чанків контексту")
    parser_query.add_argument("--threshold", type=float, default=0.015, help="Поріг RRF скору для заземлення")
    parser_query.add_argument("--graph-boost", type=float, default=1.5, help="Коефіцієнт підсилення зв'язаних графом чанків")
    parser_query.add_argument("--show-context", action="store_true", help="Показувати знайдені чанки контексту")
    parser_query.add_argument("--llm-model", default=None, help="Локальний шлях до GGUF моделі LLM")
    parser_query.add_argument("--embed-model", default=None, help="Локальний шлях до GGUF моделі ембедінгів")
    
    # Підкоманда serve
    parser_serve = subparsers.add_parser("serve", help="Запустити сервер API та веб-інтерфейс")
    parser_serve.add_argument("--host", default="127.0.0.1", help="Хост сервера")
    parser_serve.add_argument("--port", type=int, default=8001, help="Порт сервера")
    parser_serve.add_argument("--reload", action="store_true", help="Авто-перезапуск сервера при зміні коду")
    
    args = parser.parse_args()
    
    if args.command == "init":
        cmd_init(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "format":
        cmd_format(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
