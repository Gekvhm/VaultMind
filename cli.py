#!/usr/bin/env python3
import argparse
import sys
import os

# Додаємо поточну директорію до шляху імпорту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion import DocumentIngester
from indexing import RAGIndexManager
from inference import LLMInferenceManager

def cmd_init(args):
    print("=== Ініціалізація бази знань SQLite ===")
    manager = RAGIndexManager(db_path=args.db)
    manager.init_db()
    print(f"Базу даних ініціалізовано за шляхом: {args.db}")

def cmd_ingest(args):
    if not os.path.exists(args.path):
        print(f"Помилка: Шлях '{args.path}' не існує.")
        sys.exit(1)
        
    print(f"=== Запуск інгестії даних: {args.path} ===")
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
        
    print(f"Оброблено: {len(result['chunks'])} чанків, {len(result['entities'])} сутностей, {len(result['relations'])} зв'язків графа.")
    
    # Записуємо в базу знань та генеруємо вектори
    manager = RAGIndexManager(db_path=args.db)
    # Якщо користувач вказав шлях до моделі ембедінгів, передаємо її
    if args.embed_model:
        manager.embedding_model_path = args.embed_model
    manager.insert_ingested_data(result)

def cmd_query(args):
    print(f"=== Пошук та генерація для запиту: '{args.query}' ===")
    manager = RAGIndexManager(db_path=args.db)
    if args.embed_model:
        manager.embedding_model_path = args.embed_model
        
    # Виконуємо гібридний пошук
    print("Виконання гібридного пошуку (Vector + BM25 + Graph)...")
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

def cmd_format(args):
    if not os.path.exists(args.path):
        print(f"Помилка: Шлях '{args.path}' не існує.")
        sys.exit(1)
        
    print(f"=== Запуск структурування сирих даних: {args.path} ===")
    from formatter import KnowledgeFormatter
    
    formatter = KnowledgeFormatter(db_path=args.db, llm_model_path=args.llm_model)
    success = formatter.process_raw_data(
        input_path=args.path,
        vault_dir=args.out_dir,
        auto_ingest=args.auto_ingest
    )
    if success:
        print("Процес структурування та наповнення бази завершено успішно.")
    else:
        print("Під час структурування виникли помилки.")

def cmd_serve(args):
    print(f"=== Запуск RAG-сервера 'NotebookLM' на {args.host}:{args.port} ===")
    import uvicorn
    uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload)

def main():
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
    parser_serve.add_argument("--port", type=int, default=8000, help="Порт сервера")
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
