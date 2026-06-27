# PROJECT_LOG.md

## History

[2026-06-27 12:27:55] {Red-Team-QA} - Fix NameError in indexing.py
Modified files: [indexing.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/indexing.py)
Motivation: Discovered that `indexing.py` was using the `re` module without importing it.
Description: Added `import re` statement to `indexing.py` to prevent NameError runtime exceptions when running FTS5 queries via BM25.

[2026-06-27 12:27:56] {Red-Team-QA} - Create stress test script
Modified files: [tests/stress_test.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/tests/stress_test.py)
Motivation: User request to benchmark Cognitive Synthesis, Hallucination Leakage, and monitor VRAM allocation.
Description: Implemented a python-based automated stress test that sets up a temporary SQLite database, indexes contradictory and missing fact md files, and tests three queries while tracking RAM/VRAM usage.

[2026-06-27 13:10:20] {Red-Team-QA} - Fix HuggingFace Repo ID and Filename in inference.py
Modified files: [inference.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/inference.py)
Motivation: RepositoryNotFoundError when trying to download LLM model.
Description: Updated `repo_id` and `filename` in `LLMInferenceManager.download_model` to point to the correct, existing repo `bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF` and file `Qwen2.5-Coder-14B-Instruct-abliterated-Q4_K_M.gguf`.

[2026-06-27 13:34:00] {Master-Orchestrator} - Аналіз ліміту контекстного вікна та бюджету пам'яті
Modified files: [PROJECT_LOG.md](file:///Users/admin/Desktop/Projects/RAGLMGoal/PROJECT_LOG.md)
Motivation: Запит користувача щодо уточнення ліміту контекстного вікна та бюджету оперативної пам'яті.
Description: Розраховано обсяг пам'яті для FP16 KV-кешу (1.5 ГБ) при 8k контексті для моделі Qwen2.5-14B та підтверджено сумісність із жорстким лімітом 16 ГБ RAM.

[2026-06-27 14:15:00] {Master-Orchestrator} - Реалізація автоматизованого конвеєра форматування та авто-лінкування
Modified files: [formatter.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/formatter.py), [inference.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/inference.py), [cli.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/cli.py), [tests/test_formatter.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/tests/test_formatter.py), [PROJECT_LOG.md](file:///Users/admin/Desktop/Projects/RAGLMGoal/PROJECT_LOG.md)
Motivation: Запит користувача на створення алгоритму наповнення бази знань згідно з розробленими рекомендаціями (структурування заголовків, авто-лінкування вікі-посилань, архівація та розбиття довгих текстів).
Description: Реалізовано клас `KnowledgeFormatter`, додано нову команду `cli.py format` для структурування сирих файлів. Впроваджено автоматичне лінкування концептів з бази даних та файлів Obsidian Vault, автоматичне архівування сирих файлів у `.archive/` та логічне розбиття довгих документів на дрібніші зв'язані нотатки. Додано модульний тест `tests/test_formatter.py` для перевірки.

[2026-06-27 14:20:00] {Master-Orchestrator} - Покращення промпту структурування нотаток
Modified files: [inference.py](file:///Users/admin/Desktop/Projects/RAGLMGoal/inference.py)
Motivation: Виявлено, що локальна LLM меншого розміру (Qwen2.5-3B) не завжди слідує правилам форматування заголовків та авто-лінкування концептів без наочних прикладів.
Description: Додано few-shot приклад структурування та авто-лінкування у системний промпт методу `generate_structured_note` для забезпечення стабільного результату форматування на моделях меншого розміру.

[2026-06-27 15:30:00] {Master-Orchestrator} - Тестування точності відповідей та безпеки витоку знань RAG
Modified files: None (Analysis stage completed)
Motivation: Запит користувача на перевірку точності лінкування джерел та суворої фільтрації фактів, яких немає в базі знань (Zero Hallucination).
Description: Проведено тестування запитів до локальної RAG-системи. Модель Qwen2.5-3B-Instruct успішно відповіла на запит про Apple Silicon, вказавши посилання на блок джерела `[[test_note.md#BLOCK 1]]`. Запит про висоту Евересту (факту немає в базі) повернув строгий токен `[NO_CONTEXT_FOUND]`, підтверджуючи захист від витоку знань.

[2026-06-27 15:21:00] {System-Analyst} - Аналіз архітектури та кодової бази локальної RAG-системи
Modified files: [project_analysis.md](file:///Users/admin/.gemini/antigravity/brain/e4cd4373-ca90-4e6b-a9e5-3d1de9bbb6de/project_analysis.md) (Artifact)
Motivation: Запит користувача на проведення аналізу проекту.
Description: Проведено детальний аналіз архітектури, модулів (cli.py, ingestion.py, indexing.py, inference.py, formatter.py) та результатів стрес-тестування. Виявлено потенційні слабкі місця (проблема сумісності `IN ()` в SQLite на старих версіях, відсутність фактичного увімкнення квантування KV-кешу в коді, обмеження парсингу списків у frontmatter та масштабованість векторного пошуку numpy). Створено артефакт з детальним звітом та рекомендаціями.

## Session Closure Summary

### Completed
- **Тестування автоматичного конвеєра структурування даних** — Перевірено роботу команди `./cli.py format` на тестовому файлі `test_note.txt` з авто-індексацією. Конвеєр успішно обробляє сирі файли, генерує YAML метадані, логічну розмітку заголовків, автоматично додає вікі-посилання на наявні концепції з БД та переміщує оригінальний файл в архів `.archive/`.
- **Оптимізація LLM промпту для малих моделей** — Виявлено проблему з ігноруванням структурування заголовків та авто-лінкування моделлю `Qwen2.5-3B-Instruct`. Додано few-shot приклад у системний промпт методу `generate_structured_note` в `inference.py`, що дозволило отримати ідеальне форматування.
- **SQLite та FTS5 Індексація** — Перевірено успішне додавання згенерованих чанків та нових сутностей у таблиці SQLite бази знань `rag_storage.db` після авто-інгестії.
- **Тестування точності відповідей та безпеки RAG** — Успішно перевірено точність посилань на джерела (виведено `[[test_note.md#BLOCK 1]]`) та стійкість системи до галюцинацій (виведено `[NO_CONTEXT_FOUND]` при запиті про висоту Евересту).

### Not Completed
- Немає. Усі заплановані тестові та верифікаційні завдання виконано.

### Discovered
- Локальні LLM невеликого розміру (наприклад, Qwen2.5-3B) критично потребують few-shot прикладів у промптах для точного слідування складним Markdown-структурам та правилам авто-лінкування концептів.
- Система заземлення (Strict Grounding) успішно блокує внутрішні знання локальної LLM, запобігаючи витоку фактів, яких немає в базі знань, навіть коли модель володіє цією інформацією (наприклад, про Еверест).

### Next Steps
1. Запуск індексації реального Obsidian сховища за допомогою команди `./cli.py ingest <шлях_до_нотаток>`.
2. Виконання тестових запитів через `./cli.py query "<запит>"` для перевірки когнітивного синтезу на реальних даних.
3. Моніторинг RAM за допомогою внутрішнього `Memory Monitor` під час перших запусків на реальній базі знань.
