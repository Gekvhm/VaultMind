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

