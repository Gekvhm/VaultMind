"""HTTP-клієнт для VaultMind REST API."""

from __future__ import annotations

import requests
from typing import Any


class VaultMindClient:
    """Python SDK для роботи з VaultMind REST API.

    Приклад використання::

        from vaultmind import VaultMindClient

        vm = VaultMindClient("http://localhost:8001", api_key="vm-xxx")

        # Створити воркспейс
        vm.create_workspace("my-project")

        # Завантажити текст напряму
        vm.ingest_text("my-project", "Зміст документа...", filename="notes.md")

        # Завантажити з URL
        vm.ingest_url("my-project", "https://example.com/article")

        # Запитати
        answer = vm.query("my-project", "Про що цей документ?")
        print(answer["response"])
    """

    def __init__(self, base_url: str = "http://localhost:8001", api_key: str = "") -> None:
        """Ініціалізує клієнт.

        Args:
            base_url: URL сервера VaultMind.
            api_key: API-ключ для авторизації.
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Виконує HTTP-запит та повертає JSON-відповідь."""
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # --- Воркспейси ---

    def list_workspaces(self) -> dict:
        """Повертає список усіх воркспейсів."""
        return self._request("GET", "/api/workspaces")

    def create_workspace(self, name: str) -> dict:
        """Створює новий воркспейс."""
        return self._request("POST", "/api/workspaces", json={"name": name})

    def delete_workspace(self, ws_id: str) -> dict:
        """Видаляє воркспейс."""
        return self._request("DELETE", f"/api/workspaces/{ws_id}")

    def get_config(self, ws_id: str) -> dict:
        """Повертає конфігурацію воркспейсу."""
        return self._request("GET", f"/api/workspaces/{ws_id}/config")

    def update_settings(self, ws_id: str, settings: dict) -> dict:
        """Оновлює налаштування воркспейсу."""
        return self._request("POST", f"/api/workspaces/{ws_id}/settings", json=settings)

    def get_status(self, ws_id: str) -> dict:
        """Повертає статистику воркспейсу (кількість чанків, сутностей, RAM)."""
        return self._request("GET", f"/api/workspaces/{ws_id}/status")

    # --- Інгестія ---

    def ingest_text(self, ws_id: str, text: str, filename: str = "untitled.md", auto_structure: bool = False) -> dict:
        """Інгестує текст напряму у воркспейс.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            text: Текст для інгестії.
            filename: Ім'я файлу для збереження.
            auto_structure: Якщо True — пропускає текст через LLM для структурування.
        """
        return self._request("POST", f"/api/workspaces/{ws_id}/ingest-text", json={
            "text": text,
            "filename": filename,
            "auto_structure": auto_structure,
        })

    def ingest_url(self, ws_id: str, url: str, filename: str = "") -> dict:
        """Завантажує контент з URL та індексує у воркспейсі.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            url: URL для завантаження.
            filename: Ім'я файлу (автоматично генерується з URL якщо порожнє).
        """
        return self._request("POST", f"/api/workspaces/{ws_id}/ingest-url", json={
            "url": url,
            "filename": filename,
        })

    def upload_files(self, ws_id: str, file_paths: list[str]) -> dict:
        """Завантажує файли у воркспейс.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            file_paths: Список шляхів до файлів.
        """
        files = [("files", (open(p, "rb"))) for p in file_paths]
        try:
            return self._request("POST", f"/api/workspaces/{ws_id}/upload", files=files)
        finally:
            for _, f in files:
                f.close()

    # --- Джерела ---

    def list_sources(self, ws_id: str) -> dict:
        """Повертає список індексованих джерел."""
        return self._request("GET", f"/api/workspaces/{ws_id}/sources")

    def delete_source(self, ws_id: str, source_name: str) -> dict:
        """Видаляє джерело з воркспейсу."""
        return self._request("DELETE", f"/api/workspaces/{ws_id}/sources/{source_name}")

    # --- Граф знань ---

    def get_entities(self, ws_id: str, entity_type: str = "", limit: int = 100) -> dict:
        """Повертає сутності та зв'язки графу знань.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            entity_type: Фільтр за типом (Document, Tag, Concept, Metadata).
            limit: Максимальна кількість результатів.
        """
        params = {"limit": limit}
        if entity_type:
            params["entity_type"] = entity_type
        return self._request("GET", f"/api/workspaces/{ws_id}/entities", params=params)

    # --- Пошук та запити ---

    def query(self, ws_id: str, question: str) -> dict:
        """Виконує RAG-запит до воркспейсу та повертає відповідь з цитатами.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            question: Текст запиту.

        Returns:
            dict з ключами 'response' (відповідь LLM) та 'context' (список чанків-джерел).
        """
        return self._request("POST", f"/api/workspaces/{ws_id}/query", json={"query": question})

    def chat(self, ws_id: str, messages: list[dict], model: str = "vaultmind") -> dict:
        """OpenAI-сумісний chat completions через RAG.

        Args:
            ws_id: Ідентифікатор воркспейсу.
            messages: Список повідомлень у форматі OpenAI [{"role": "user", "content": "..."}].
            model: Назва моделі (ігнорується, використовується модель воркспейсу).
        """
        return self._request("POST", f"/v1/chat/completions/{ws_id}", json={
            "model": model,
            "messages": messages,
        })
