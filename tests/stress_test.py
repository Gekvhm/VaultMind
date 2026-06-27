#!/usr/bin/env python3
import os
import sys
import shutil
import time
import psutil
import json
import sqlite3

# Додаємо кореневу директорію проекту до шляху імпорту
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion import DocumentIngester
from indexing import RAGIndexManager
from inference import LLMInferenceManager

TEMP_DB = "tests/temp_rag_storage.db"
TEMP_DOCS_DIR = "tests/temp_docs"

def setup_temp_environment():
    print("=== Налаштування тестового середовища ===")
    if os.path.exists(TEMP_DOCS_DIR):
        shutil.rmtree(TEMP_DOCS_DIR)
    os.makedirs(TEMP_DOCS_DIR, exist_ok=True)
    
    if os.path.exists(TEMP_DB):
        os.remove(TEMP_DB)

    # Створення тестових файлів
    # Файл 1: Зворотні та суперечливі факти про проект Alpha
    alpha_content = """---
title: Project Alpha
status: active
---
# Project Alpha
Project Alpha is led by Alice.
In 2026, Project Alpha was transferred to Bob. Bob is the current leader of Project Alpha now.
#project-alpha
"""
    # Файл 2: Факти про проект Beta
    beta_content = """---
title: Project Beta
status: active
---
# Project Beta
Project Beta is code-named X.
#project-beta
"""
    
    with open(os.path.join(TEMP_DOCS_DIR, "project_alpha.md"), "w", encoding="utf-8") as f:
        f.write(alpha_content)
        
    with open(os.path.join(TEMP_DOCS_DIR, "project_beta.md"), "w", encoding="utf-8") as f:
        f.write(beta_content)
        
    print("Тестові файли успішно створено.")

def get_memory_info():
    process = psutil.Process(os.getpid())
    # RSS в MB
    rss = process.memory_info().rss / (1024 * 1024)
    # Системна пам'ять
    sys_mem = psutil.virtual_memory()
    sys_used = sys_mem.used / (1024 * 1024 * 1024) # в GB
    sys_total = sys_mem.total / (1024 * 1024 * 1024) # в GB
    return {
        "process_rss_mb": rss,
        "system_used_gb": sys_used,
        "system_total_gb": sys_total,
        "system_percent": sys_mem.percent
    }

def run_stress_test():
    setup_temp_environment()
    
    metrics = {
        "phases": {},
        "test_results": []
    }
    
    # 1. Замір пам'яті до початку
    mem_start = get_memory_info()
    metrics["phases"]["start"] = mem_start
    print(f"Початкова пам'ять процесу: {mem_start['process_rss_mb']:.2f} MB")
    
    # 2. Ініціалізація та індексація
    t0 = time.time()
    manager = RAGIndexManager(db_path=TEMP_DB)
    manager.init_db()
    
    ingester = DocumentIngester(chunk_size=500, chunk_overlap=100)
    ingested = ingester.process_directory(TEMP_DOCS_DIR)
    
    manager.insert_ingested_data(ingested)
    t_index = time.time() - t0
    
    mem_after_index = get_memory_info()
    metrics["phases"]["after_indexing"] = mem_after_index
    metrics["indexing_time_sec"] = t_index
    print(f"Час індексації: {t_index:.2f} сек. Пам'ять після індексації: {mem_after_index['process_rss_mb']:.2f} MB")
    
    # 3. Виконання запитів
    queries = [
        {
            "id": "query_1",
            "name": "Cognitive Synthesis (Project Alpha leader)",
            "query": "Хто є актуальним керівником проекту Alpha?",
            "expected_contains": ["Bob"],
            "expected_not_contains": ["Alice"],
            "cannot_be_none": True
        },
        {
            "id": "query_2",
            "name": "Hallucination Leakage (Project Gamma leader)",
            "query": "Хто керує проектом Gamma?",
            "expected_exact": "[NO_CONTEXT_FOUND]",
            "cannot_be_none": False
        },
        {
            "id": "query_3",
            "name": "Out-of-domain knowledge leak (Capital of France)",
            "query": "Яка столиця Франції?",
            "expected_exact": "[NO_CONTEXT_FOUND]",
            "cannot_be_none": False
        }
    ]
    
    # Створюємо екземпляр LLM менеджера
    # Для тесту використовуємо ті ж шляхи, що і за замовчуванням
    inference_manager = LLMInferenceManager()
    
    for q in queries:
        print(f"\n--- Виконання запиту: {q['query']} ---")
        mem_before_q = get_memory_info()
        t_start = time.time()
        
        # Пошук контексту
        chunks = manager.hybrid_search_rrf(q["query"], limit=5)
        
        # Генерація
        response = inference_manager.generate_response(q["query"], chunks)
        t_elapsed = time.time() - t_start
        mem_after_q = get_memory_info()
        
        print(f"Відповідь: {response}")
        print(f"Час виконання: {t_elapsed:.2f} сек. Пам'ять: {mem_after_q['process_rss_mb']:.2f} MB")
        
        # Валідація результату
        status = "PASSED"
        fail_reasons = []
        
        if "expected_exact" in q:
            if response != q["expected_exact"]:
                status = "FAILED"
                fail_reasons.append(f"Очікувалось '{q['expected_exact']}', отримано '{response}'")
        
        if "expected_contains" in q:
            for item in q["expected_contains"]:
                if item.lower() not in response.lower():
                    status = "FAILED"
                    fail_reasons.append(f"У відповіді не знайдено '{item}'")
                    
        if "expected_not_contains" in q:
            for item in q["expected_not_contains"]:
                # Ми очікуємо, що Боб є актуальним керівником, тому Аліса не повинна вказуватись як актуальний керівник.
                # Але якщо вона згадується в контексті минулого ("Project Alpha was transferred to Bob..."),
                # модель повинна коректно відповісти, що лідером є саме Боб.
                # Перевіримо, чи модель стверджує, що Аліса є поточним керівником.
                if "alice" in response.lower() and "bob" not in response.lower():
                    status = "FAILED"
                    fail_reasons.append("Модель вказала Алісу замість Боба")
        
        result_item = {
            "query_id": q["id"],
            "name": q["name"],
            "query": q["query"],
            "response": response,
            "status": status,
            "fail_reasons": fail_reasons,
            "time_sec": t_elapsed,
            "memory_before": mem_before_q,
            "memory_after": mem_after_q
        }
        metrics["test_results"].append(result_item)
        
    # Загальний підсумок
    mem_end = get_memory_info()
    metrics["phases"]["end"] = mem_end
    
    print("\n=== Результати тестування ===")
    for r in metrics["test_results"]:
        print(f"[{r['status']}] {r['name']} - {r['time_sec']:.2f}s")
        if r["status"] == "FAILED":
            print(f"  Причини помилки: {r['fail_reasons']}")
            
    # Запис метрик у файл
    os.makedirs("tests/results", exist_ok=True)
    with open("tests/results/metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=4, ensure_ascii=False)
    print("Метрики записано у tests/results/metrics.json")
    
    # Видалення тимчасових файлів
    if os.path.exists(TEMP_DOCS_DIR):
        shutil.rmtree(TEMP_DOCS_DIR)
        
    return metrics

if __name__ == "__main__":
    run_stress_test()
