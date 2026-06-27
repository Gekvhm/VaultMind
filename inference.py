import os
import gc
import psutil
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

class LLMInferenceManager:
    def __init__(self, config=None, model_path=None, context_size=8192):
        self.config = config or {
            "provider": "local",
            "local_model_path": model_path,
            "context_size": context_size,
            "rrf_threshold": 0.015
        }
        # Збереження сумісності зі старим інтерфейсом
        self.model_path = self.config.get("local_model_path") or model_path
        self.context_size = self.config.get("context_size") or context_size
        self.llm = None
        
    def download_model(self):
        """Завантажує Qwen2.5-14B-Instruct-Abliterated GGUF з Hugging Face."""
        if self.model_path is not None:
            return self.model_path
            
        os.makedirs("models", exist_ok=True)
        print("Завантаження моделі Qwen2.5-14B-Instruct-Abliterated (Q4_K_M)...")
        self.model_path = hf_hub_download(
            repo_id="mradermacher/Qwen2.5-14B-Instruct-Abliterated-GGUF",
            filename="Qwen2.5-14B-Instruct-Abliterated.Q4_K_M.gguf",
            local_dir="models"
        )
        return self.model_path

    def init_llm(self):
        """Ініціалізує LLM з Metal-прискоренням та квантованим KV Cache (Q8_0)."""
        if self.config.get("provider", "local") == "openai":
            return
            
        if self.llm is not None:
            return
            
        model_file = self.download_model()
        print(f"Ініціалізація LLM моделі з {model_file}...")
        
        try:
            self.llm = Llama(
                model_path=model_file,
                n_ctx=self.context_size,
                n_gpu_layers=-1,       # Завантаження всіх шарів у GPU (Metal)
                use_mmap=True,         # Використання memory-mapped файлів
                verbose=False          # Приховуємо низькорівневі логи llama.cpp
            )
        except Exception as e:
            print(f"Помилка ініціалізації LLM: {str(e)}")
            raise e

    def print_memory_usage(self):
        """Виводит поточне споживання пам'яті системою."""
        process = psutil.Process(os.getpid())
        ram_usage = process.memory_info().rss / (1024 * 1024)
        print(f"[Memory Monitor] Споживання RAM процесом Python: {ram_usage:.2f} MB")

    def generate_response(self, query, retrieved_chunks, rrf_threshold=None):
        """Генерує відповідь за допомогою LLM на основі контексту з суворим заземленням."""
        if rrf_threshold is None:
            rrf_threshold = self.config.get("rrf_threshold", 0.015)
            
        # 1. Перевірка RRF-порогу
        if not retrieved_chunks:
            return "[NO_CONTEXT_FOUND]"
            
        best_score = retrieved_chunks[0]["score"]
        if best_score < rrf_threshold:
            print(f"[Strict Grounding] Найкращий RRF бал ({best_score:.4f}) нижчий за поріг ({rrf_threshold}). Блокування LLM.")
            return "[NO_CONTEXT_FOUND]"
            
        # 2. Підготовка контексту
        context_str = ""
        for i, chunk in enumerate(retrieved_chunks):
            context_str += f"=== BLOCK {i+1} ===\n"
            context_str += f"Source File: {os.path.basename(chunk['file_path'])}\n"
            context_str += f"Section/Heading: {chunk['heading']}\n"
            context_str += f"Content: {chunk['content']}\n"
            context_str += "====================\n\n"
            
        # 3. Підготовка промпту
        system_prompt = """Ти — суворий аналітичний помічник з нульовим витоком зовнішніх знань.
Твоє завдання — відповісти на запит користувача, спираючись ВИКЛЮЧНО на надані блоки контексту (BLOCK 1, BLOCK 2 тощо).
Контекст може бути англійською або іншою мовою, але ти повинен дати відповідь українською мовою на основі перекладу та аналізу наданих фактів.

КРИТИЧНІ ПРАВИЛА:
1. Відповідай строго на основі наданих фактів. Не вигадуй інформацію та не використовуй свої внутрішні знання, отримані під час попереднього навчання.
2. Якщо у наданих блоках контексту НЕМАЄ прямої та однозначної відповіді на запитання користувача, ти ЗОБОВ'ЯЗАНИЙ відповісти рівно одним словом: [NO_CONTEXT_FOUND]
3. Будь-які припущення, екстраполяції чи доповнення фактів заборонені. Якщо факт не згаданий — його не існує.
4. Для кожного факту у відповіді обов'язково вказуй джерело у форматі [[НазваФайлу]].
5. Твоя відповідь має бути написана виключно українською мовою.
"""
        user_prompt = f"Контекст:\n{context_str}\nЗапит користувача: {query}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        provider = self.config.get("provider", "local")
        
        if provider == "local":
            self.init_llm()
            self.print_memory_usage()
            print("Генерація відповіді локальною LLM (Metal API)...")
            try:
                response = self.llm.create_chat_completion(
                    messages=messages,
                    temperature=0.0,
                    max_tokens=1024
                )
                ans = response["choices"][0]["message"]["content"].strip()
            finally:
                gc.collect()
        else:
            print(f"Генерація відповіді через Cloud API ({self.config.get('openai_model_name')})...")
            from openai import OpenAI
            client = OpenAI(
                api_key=self.config.get("openai_api_key"),
                base_url=self.config.get("openai_base_url") or None
            )
            res = client.chat.completions.create(
                model=self.config.get("openai_model_name"),
                messages=messages,
                temperature=0.0,
                max_tokens=1024
            )
            ans = res.choices[0].message.content.strip()
            
        if "NO_CONTEXT_FOUND" in ans.upper() or not ans:
            return "[NO_CONTEXT_FOUND]"
        return ans

    def generate_structured_note(self, raw_text, concepts):
        """Перетворює сирий текст на структуровану нотатку Markdown з авто-лінкуванням."""
        concepts_str = ", ".join([f'"{c}"' for c in concepts]) if concepts else "немає"
        
        system_prompt = f"""Ти — професійний аналітик та редактор баз знань Obsidian.
Твоє завдання — перетворити сирий, неструктурований текст на акуратну, структуровану нотатку Markdown з логічними заголовками, тегами та вікі-посиланнями.

КРИТИЧНІ ПРАВИЛА ФОРМАТУВАННЯ:
1. Завжди починай відповідь з блоку метаданих YAML (frontmatter) у такому форматі:
---
tags: [відповідні теги через кому]
date: 2026-06-27
status: active
type: concept
---
2. Організуй вміст за допомогою логічних заголовків ## та ###. Прибери хаотичне форматування чи артефакти сканування.
3. Текст має бути написаний у нейтральному, аналітичному та лаконічному стилі, без зайвих вступів та висновків. Відразу пиши Markdown.
4. Тобі надано список відомих концептів: [{concepts_str}].
   Якщо у тексті зустрічається поняття з цього списку (у будь-кому відмінку, числі чи близькому синонімі), ти ЗОБОВ'ЯЗАНИЙ обгорнути його у [[вікі-посилання]] (наприклад, якщо в списку є "Apple Silicon", а в тексті "процесорі Apple Silicon", напиши "процесорі [[Apple Silicon]]").
5. Якщо в тексті згадуються інші важливі терміни, назви технологій, проектів чи людей, яких немає в списку, але які є важливими концептами, також обгорни їх у [[вікі-посилання]], щоб створити нові потенційні нотатки.
6. Вся нотатка має бути написана виключно українською мовою.

ПРИКЛАД:
Відомі концепти: ["RAG", "Apple Silicon", "SQLite"]
Вхідний текст:
"сьогодні дивився на RAG системи. вони класно запускаються на комп'ютерах з Apple Silicon та використовують базу sqlite"
Вихідний текст:
---
tags: [RAG, Apple Silicon, SQLite]
date: 2026-06-27
status: active
type: concept
---
## Локальні архітектури знань
### Використання RAG систем
Сьогодні було проведено аналіз [[RAG]] систем. Вони показують високу ефективність при запуску на комп'ютерах з процесорами [[Apple Silicon]].
### Сховище даних
Для збереження інформації та чанків використовується реляційна база даних [[SQLite]].
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Відомі концепти: [{concepts_str}]\n\nСирий текст для структурування:\n\n{raw_text}"}
        ]
        
        provider = self.config.get("provider", "local")
        
        if provider == "local":
            self.init_llm()
            self.print_memory_usage()
            print("Форматування тексту за допомогою LLM (Metal API)...")
            try:
                response = self.llm.create_chat_completion(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=2048
                )
                return response["choices"][0]["message"]["content"].strip()
            finally:
                gc.collect()
        else:
            print(f"Форматування тексту через Cloud API ({self.config.get('openai_model_name')})...")
            from openai import OpenAI
            client = OpenAI(
                api_key=self.config.get("openai_api_key"),
                base_url=self.config.get("openai_base_url") or None
            )
            res = client.chat.completions.create(
                model=self.config.get("openai_model_name"),
                messages=messages,
                temperature=0.2,
                max_tokens=2048
            )
            return res.choices[0].message.content.strip()

