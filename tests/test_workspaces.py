import os
import shutil
import unittest
from fastapi.testclient import TestClient
from server import app

class TestWorkspaceAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_ws_name_a = "tmp_ws_test_a"
        self.test_ws_name_b = "tmp_ws_test_b"

    def tearDown(self):
        # Очищення папок воркспейсів, якщо вони залишились
        for ws_name in [self.test_ws_name_a, self.test_ws_name_b]:
            ws_path = os.path.join("workspaces", ws_name)
            if os.path.exists(ws_path):
                shutil.rmtree(ws_path)

    def test_workspace_crud(self):
        # 1. Отримання початкового списку воркспейсів
        res = self.client.get("/api/workspaces")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("workspaces", data)
        self.assertIn("default", data["workspaces"])

        # 2. Створення воркспейсу А
        res = self.client.post("/api/workspaces", json={"name": self.test_ws_name_a})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")
        self.assertEqual(res.json()["workspace_id"], self.test_ws_name_a)

        # 3. Створення воркспейсу Б
        res = self.client.post("/api/workspaces", json={"name": self.test_ws_name_b})
        self.assertEqual(res.status_code, 200)

        # 4. Перевірка списку воркспейсів
        res = self.client.get("/api/workspaces")
        data = res.json()
        self.assertIn(self.test_ws_name_a, data["workspaces"])
        self.assertIn(self.test_ws_name_b, data["workspaces"])

        # 5. Отримання конфігурації
        res = self.client.get(f"/api/workspaces/{self.test_ws_name_a}/config")
        self.assertEqual(res.status_code, 200)
        config = res.json()
        self.assertEqual(config["provider"], "local")

        # 6. Зміна конфігурації
        settings_payload = {
            "provider": "openai",
            "openai_base_url": "https://api.deepseek.com/v1",
            "openai_api_key": "sk-test-key",
            "openai_model_name": "deepseek-chat",
            "rrf_threshold": 0.02
        }
        res = self.client.post(f"/api/workspaces/{self.test_ws_name_a}/settings", json=settings_payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        # Перевірка оновлення
        res = self.client.get(f"/api/workspaces/{self.test_ws_name_a}/config")
        config = res.json()
        self.assertEqual(config["provider"], "openai")
        self.assertEqual(config["openai_model_name"], "deepseek-chat")
        self.assertEqual(config["rrf_threshold"], 0.02)

        # 7. Перевірка статусу
        res = self.client.get(f"/api/workspaces/{self.test_ws_name_a}/status")
        self.assertEqual(res.status_code, 200)
        status = res.json()
        self.assertEqual(status["workspace_id"], self.test_ws_name_a)
        self.assertEqual(status["active_model"]["provider"], "openai")

        # 8. Видалення воркспейсів
        res = self.client.delete(f"/api/workspaces/{self.test_ws_name_a}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        res = self.client.delete(f"/api/workspaces/{self.test_ws_name_b}")
        self.assertEqual(res.status_code, 200)

        # Перевірка вилучення зі списку
        res = self.client.get("/api/workspaces")
        data = res.json()
        self.assertNotIn(self.test_ws_name_a, data["workspaces"])
        self.assertNotIn(self.test_ws_name_b, data["workspaces"])

if __name__ == "__main__":
    unittest.main()
