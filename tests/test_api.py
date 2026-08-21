import os
import tempfile
import unittest
import unittest.mock
from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

class TestFastAPIEndpoints(unittest.TestCase):

    def test_index_page(self):
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("MPC With Generative Art", resp.text)

    def test_parse_valid_deck(self):
        payload = {
            "text": "1 Byode, Inverse Sun (PH21) 3\tAn anime girl dressed like a pixie\n1 All-Seeing Toby (SLD) 2695\tAn anime boy in a library"
        }
        resp = client.post("/api/parse", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(len(data["cards"]), 2)
        self.assertEqual(data["total_copies"], 2)

    def test_parse_invalid_deck(self):
        payload = {
            "text": "Invalid line without format"
        }
        resp = client.post("/api/parse", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(len(data["errors"]) > 0)

    def test_parse_with_global_prompt(self):
        payload = {
            "text": "# in cyberpunk futuristic style\n1 Byode, Inverse Sun (PH21) 3\tPixie\n1 All-Seeing Toby (SLD) 2695\tBoy"
        }
        resp = client.post("/api/parse", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["global_prompt"], "in cyberpunk futuristic style")
        self.assertEqual(data["cards"][0]["prompt"], "in cyberpunk futuristic style Pixie")
        self.assertEqual(data["cards"][1]["prompt"], "in cyberpunk futuristic style Boy")

    def test_parse_file_with_global_prompt(self):
        file_content = b"# retro synthwave style\n1 Byode, Inverse Sun (PH21) 3\tPixie\n"
        resp = client.post(
            "/api/parse-file",
            files={"file": ("deck.txt", file_content, "text/plain")}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["global_prompt"], "retro synthwave style")
        self.assertEqual(data["cards"][0]["prompt"], "retro synthwave style Pixie")

    def setUp(self):
        import tempfile
        self.temp_env = tempfile.NamedTemporaryFile(suffix=".env", delete=False)
        self.temp_env.close()
        self.env_patch = unittest.mock.patch.dict(os.environ, {"ENV_FILE": self.temp_env.name})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        if os.path.exists(self.temp_env.name):
            try:
                os.remove(self.temp_env.name)
            except OSError:
                pass

    def test_settings_endpoints(self):
        get_resp = client.get("/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        
        post_resp = client.post("/api/settings", json={"provider": "mock"})
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["provider"], "mock")

    def test_settings_persistence_in_dotenv(self):
        import os
        from pathlib import Path
        from dotenv import dotenv_values
        from backend.app import AppState, get_env_file

        # Test updating settings saves to temporary .env
        post_resp = client.post("/api/settings", json={"provider": "grok", "xai_api_key": "test_xai_secret_123"})
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["provider"], "grok")

        # Verify temporary .env file on disk contains the updated values
        target_env = get_env_file()
        self.assertIsNotNone(target_env)
        self.assertTrue(target_env.exists())
        env_vals = dotenv_values(str(target_env))
        self.assertEqual(env_vals.get("GENERATOR_PROVIDER"), "grok")
        self.assertEqual(env_vals.get("XAI_API_KEY"), "test_xai_secret_123")

        # Verify AppState loads GENERATOR_PROVIDER from environment
        with unittest.mock.patch.dict(os.environ, {"GENERATOR_PROVIDER": "gemini"}, clear=False):
            new_state = AppState()
            self.assertEqual(new_state.provider, "gemini")

    def test_generator_prompts_exclude_card_name(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        import io
        import base64
        from PIL import Image
        from backend.generator import GeminiImageGenerator, OpenAIImageGenerator

        # 1. Test Gemini Image Generator does not include card_name in prompt payload
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        sample_img = Image.new("RGB", (100, 100), (255, 255, 255))
        buf = io.BytesIO()
        sample_img.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
        mock_resp.json.return_value = {"predictions": [{"bytesBase64Encoded": b64_img}]}

        async def run_gemini():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp
                gen = GeminiImageGenerator(api_key="gemini_dummy_key")
                await gen.generate_art(
                    prompt="A mystical fairy in an enchanted forest",
                    card_name="Pixie Queen",
                    target_width=300,
                    target_height=400,
                )
                mock_post.assert_called_once()
                sent_payload = mock_post.call_args.kwargs["json"]
                sent_prompt = sent_payload["instances"][0]["prompt"]
                self.assertNotIn("Pixie Queen", sent_prompt)
                self.assertIn("A mystical fairy in an enchanted forest", sent_prompt)

        # 2. Test OpenAI Image Generator does not include card_name in prompt payload
        mock_openai_resp = MagicMock()
        mock_openai_resp.status_code = 200
        mock_openai_resp.json.return_value = {"data": [{"b64_json": b64_img}]}

        async def run_openai():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_openai_resp
                gen = OpenAIImageGenerator(api_key="openai_dummy_key")
                await gen.generate_art(
                    prompt="A massive dark dragon soaring across volcanoes",
                    card_name="Infernal Dragon",
                    target_width=300,
                    target_height=400,
                )
                mock_post.assert_called_once()
                sent_payload = mock_post.call_args.kwargs["json"]
                sent_prompt = sent_payload["prompt"]
                self.assertNotIn("Infernal Dragon", sent_prompt)
                self.assertIn("A massive dark dragon soaring across volcanoes", sent_prompt)

        import asyncio
        asyncio.run(run_gemini())
        asyncio.run(run_openai())

    def test_cards_and_export_flow(self):
        # 1. Parse sample deck
        deck = "1 Byode, Inverse Sun (PH21) 3\tAn anime pixie"
        client.post("/api/parse", json={"text": deck})

        # 2. Check cards endpoint
        cards_resp = client.get("/api/cards")
        self.assertEqual(cards_resp.status_code, 200)
        cards_data = cards_resp.json()
        self.assertEqual(len(cards_data["cards"]), 1)

        # 3. Export XML
        xml_resp = client.get("/api/export/xml")
        self.assertEqual(xml_resp.status_code, 200)
        self.assertIn("<order>", xml_resp.text)
        self.assertIn("Byode, Inverse Sun", xml_resp.text)

        # 4. Export ZIP
        zip_resp = client.get("/api/export/zip")
        self.assertEqual(zip_resp.status_code, 200)
        self.assertEqual(zip_resp.headers["content-type"], "application/zip")

if __name__ == "__main__":
    unittest.main()
