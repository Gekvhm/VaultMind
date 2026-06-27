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

## Session Closure Summary

### Completed
- **Аналіз ліміту контекстного вікна** — Проведено розрахунок споживання пам'яті для FP16 KV-кешу на моделі Qwen2.5-14B при контексті 8192 токени. Доведено, що збільшення контексту призведе до перевищення ліміту 16 ГБ RAM. Результати надано користувачу.
- **Оцінка рантайму Metal** — Підтверджено стабільність роботи Metal без квантування KV-кешу (через виявлені раніше `GGML_ASSERT` збої) при збереженні загального споживання системи в межах ~15.15 ГБ RAM.

### Not Completed
- Немає. Усі заплановані аналітичні та інженерні завдання виконано.

### Discovered
- При використанні FP16 KV-кешу лінійне зростання контексту (наприклад, до 16k чи 32k) створює значний оверхед пам'яті (~3.0 ГБ та ~6.0 ГБ відповідно), що робить 8k оптимальним лімітом для пристроїв із 16 ГБ RAM.

### Next Steps
1. Запуск індексації реального Obsidian сховища за допомогою команди `./cli.py ingest <шлях_до_нотаток>`.
2. Виконання тестових запитів через `./cli.py query "<запит>"` для перевірки когнітивного синтезу на реальних даних.
3. Моніторинг RAM за допомогою внутрішнього `Memory Monitor` під час перших запусків на реальній базі знань.


