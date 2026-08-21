"""Unit and integration tests for Grok (xAI) Image Generator."""
import os
import io
import base64
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from PIL import Image
import httpx
from fastapi.testclient import TestClient

from backend.generator import get_generator, GrokImageGenerator, MockProceduralGenerator
from backend.app import app


class TestGrokGenerator(unittest.IsolatedAsyncioTestCase):

    def test_factory_resolution(self):
        aliases = [
            "grok",
            "xai",
            "grok-2",
            "grok-imagine",
            "grok-imagine-image",
            "grok-imagine-image-2.0",
            "x-ai",
            "GROK",
            "XAI",
        ]
        for alias in aliases:
            gen = get_generator(alias, xai_api_key="test_key_123")
            self.assertIsInstance(gen, GrokImageGenerator, f"Failed resolving alias: {alias}")
            self.assertEqual(gen.api_key, "test_key_123")

    def test_api_key_initialization(self):
        # Direct key parameter
        gen1 = GrokImageGenerator(api_key="direct_key")
        self.assertEqual(gen1.api_key, "direct_key")

        # Environment variable XAI_API_KEY
        with patch.dict(os.environ, {"XAI_API_KEY": "env_xai_key"}, clear=True):
            gen2 = GrokImageGenerator()
            self.assertEqual(gen2.api_key, "env_xai_key")

        # Environment variable GROK_API_KEY
        with patch.dict(os.environ, {"GROK_API_KEY": "env_grok_key"}, clear=True):
            gen3 = GrokImageGenerator()
            self.assertEqual(gen3.api_key, "env_grok_key")

    async def test_fallback_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            gen = GrokImageGenerator(api_key="")
            art = await gen.generate_art(
                prompt="A cybernetic samurai in neo-tokyo",
                card_name="Cyber Samurai",
                target_width=400,
                target_height=600,
            )
            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (400, 600))

    async def test_generate_art_b64_json_response(self):
        # Create a sample test image and encode to base64
        sample_img = Image.new("RGB", (300, 400), (30, 144, 255))
        buf = io.BytesIO()
        sample_img.save(buf, format="PNG")
        b64_str = base64.b64decode(base64.b64encode(buf.getvalue())).decode("latin1")
        b64_encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"b64_json": b64_encoded}
            ]
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp

            gen = GrokImageGenerator(api_key="valid_xai_key")
            art = await gen.generate_art(
                prompt="A mystical wizard in glowing robes",
                card_name="Archmage",
                target_width=350,
                target_height=500,
            )

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer valid_xai_key")
            self.assertEqual(call_kwargs["json"]["model"], "grok-imagine-image-2.0")
            self.assertEqual(call_kwargs["json"]["aspect_ratio"], "3:4")
            self.assertNotIn("Archmage", call_kwargs["json"]["prompt"])
            self.assertIn("A mystical wizard in glowing robes", call_kwargs["json"]["prompt"])

            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (350, 500))

    async def test_generate_art_url_response(self):
        # Create a sample test image bytes
        sample_img = Image.new("RGB", (400, 300), (255, 100, 50))
        buf = io.BytesIO()
        sample_img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "data": [
                {"url": "https://api.x.ai/temp_images/test_image.png"}
            ]
        }

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = raw_bytes

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
             patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_post.return_value = mock_post_resp
            mock_get.return_value = mock_get_resp

            gen = GrokImageGenerator(api_key="valid_xai_key")
            # Landscape orientation (width > height) -> aspect ratio should be 4:3
            art = await gen.generate_art(
                prompt="A wide dragon canyon landscape",
                card_name="Dragon Canyon",
                target_width=600,
                target_height=400,
            )

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            self.assertEqual(call_kwargs["json"]["aspect_ratio"], "4:3")
            mock_get.assert_called_once_with("https://api.x.ai/temp_images/test_image.png", timeout=60.0)

            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (600, 400))

    async def test_fallback_on_api_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp

            gen = GrokImageGenerator(api_key="valid_xai_key")
            art = await gen.generate_art(
                prompt="An enchanted forest",
                card_name="Mystic Woods",
                target_width=300,
                target_height=400,
            )
            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (300, 400))

    async def test_fallback_on_network_exception(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.RequestError("Connection refused")

            gen = GrokImageGenerator(api_key="valid_xai_key")
            art = await gen.generate_art(
                prompt="An enchanted forest",
                card_name="Mystic Woods",
                target_width=300,
                target_height=400,
            )
            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (300, 400))


class TestGrokSettingsAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_settings_get_and_post_grok(self):
        # 1. Update settings with Grok provider and xAI key
        payload = {
            "provider": "grok",
            "xai_api_key": "xai-test-key-999",
            "hf_token": "hf_dummy",
            "gemini_api_key": "gemini_dummy",
            "openai_api_key": "openai_dummy",
        }
        post_resp = self.client.post("/api/settings", json=payload)
        self.assertEqual(post_resp.status_code, 200)
        data = post_resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertEqual(data["provider"], "grok")
        self.assertTrue(data["has_xai_key"])

        # 2. Get settings to verify values are persisted
        get_resp = self.client.get("/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.json()
        self.assertEqual(get_data["provider"], "grok")
        self.assertEqual(get_data["xai_api_key"], "xai-test-key-999")
        self.assertTrue(get_data["has_xai_key"])


if __name__ == "__main__":
    unittest.main()
