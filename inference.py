import os
import gc
import psutil
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

class LLMInferenceManager:
    def __init__(self, model_path=None, context_size=8192):
        self.model_path = model_path
        self.context_size = context_size
        self.llm = None
        
    def download_model(self):
        """Завантажує Qwen2.5-14B-Instruct-Abliterated GGUF з Hugging Face."""
        if self.model_path is not None:
            return self.model_path
            
        os.makedirs("models", exist_ok=True)
        print("Завантаження моделі Qwen2.5-14B-Instruct-Abliterated (Q4_K_M)...")
        # Використовуємо перевірений репозиторій bartowski або mradermacher
        self.model_path = hf_hub_download(
            repo_id="mradermacher/Qwen2.5-14B-Instruct-Abliterated-GGUF",
            filename="Qwen2.5-14B-Instruct-Abliterated.Q4_K_M.gguf",
            local_dir="models"
        )
        return self.model_path

    def init_llm(self):
        """Ініціалізує LLM з Metal-прискоренням та квантованим KV Cache (Q8_0)."""
        if self.llm is not None:
            return
            
        model_file = self.download_model()
        print(f"Ініціалізація LLM моделі з {model_file}...")
        
        # Налаштування параметрів для Metal API
        # type_k = 8 означає GGML_TYPE_Q8_0 (квантований KV-кеш)
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
        """Виводить поточне споживання пам'яті системою."""
        process = psutil.Process(os.getpid())
        ram_usage = process.memory_info().rss / (1024 * 1024)
        print(f"[Memory Monitor] Споживання RAM процесом Python: {ram_usage:.2f} MB")

    def generate_response(self, query, retrieved_chunks, rrf_threshold=0.015):
        """Генерує відповідь за допомогою LLM на основі контексту з суворим заземленням."""
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
            
        # 3. Ініціалізація моделі
        self.init_llm()
        self.print_memory_usage()
        
        # Системний промпт для Strict Grounding (Zero Hallucination)
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
        
        # Виклик моделі через Chat Completion API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        print("Генерація відповіді локальною LLM (Metal API)...")
        # Обгортаємо генерацію в блок try-finally для примусового очищення пам'яті
        try:
            response = self.llm.create_chat_completion(
                messages=messages,
                temperature=0.0, # Робимо відповіді максимально детермінованими
                max_tokens=1024
            )
            ans = response["choices"][0]["message"]["content"].strip()
            # Нормалізуємо токен відсутності контексту
            if "NO_CONTEXT_FOUND" in ans.upper() or not ans:
                return "[NO_CONTEXT_FOUND]"
            return ans
        finally:
            # Ручне очищення сміття після інференсу
            gc.collect()
