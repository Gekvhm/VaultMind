import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from inference import LLMInferenceManager

inference_manager = LLMInferenceManager(model_path="models/Qwen2.5-3B-Instruct-Q4_K_M.gguf")
inference_manager.init_llm()

# Створюємо мок-контекст
retrieved_chunks = [
    {
        "file_path": "tests/temp_docs/project_alpha.md",
        "heading": "Project Alpha",
        "content": "Project Alpha was transferred to Bob. Bob is the current leader of Project Alpha now.\n#project-alpha",
        "score": 0.016393
    }
]

# Тестуємо звичайний запуск без RRF перевірок
context_str = ""
for i, chunk in enumerate(retrieved_chunks):
    context_str += f"=== BLOCK {i+1} ===\n"
    context_str += f"Source File: {os.path.basename(chunk['file_path'])}\n"
    context_str += f"Section/Heading: {chunk['heading']}\n"
    context_str += f"Content: {chunk['content']}\n"
    context_str += "====================\n\n"

system_prompt = """Ти — суворий аналітичний помічник з нульовим витоком зовнішніх знань.
Твоє завдання — відповісти на запит користувача, спираючись ВИКЛЮЧНО на надані блоки контексту (BLOCK 1, BLOCK 2 тощо).
Контекст може бути англійською мовою, але відповідь обов'язково має бути українською мовою на основі перекладу фактів.

КРИТИЧНІ ПРАВИЛА:
1. Відповідай строго на основі наданих фактів. Не вигадуй інформацію та не використовуй свої внутрішні знання.
2. Якщо у наданих блоках контексту НЕМАЄ прямої та однозначної відповіді на запитання користувача, ти ЗОБОВ'ЯЗАНИЙ відповісти рівно одним словом: [NO_CONTEXT_FOUND]
3. Будь-які припущення, екстраполяції чи доповнення фактів заборонені.
4. Для кожного факту у відповіді обов'язково вказуй джерело у форматі [[НазваФайлу]].
5. Твоя відповідь має бути написана виключно українською мовою.
"""

query = "Хто є актуальним керівником проекту Alpha?"
user_prompt = f"Контекст:\n{context_str}\nЗапит користувача: {query}"

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt}
]

response = inference_manager.llm.create_chat_completion(
    messages=messages,
    temperature=0.0,
    max_tokens=1024
)
print("=== РЕЗУЛЬТАТ ===")
print(response["choices"][0]["message"]["content"])
