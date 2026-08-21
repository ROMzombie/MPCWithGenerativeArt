"""Unit and integration tests for DeepSeek Janus-Pro-7B Image Generator."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image
from fastapi.testclient import TestClient

from backend.generator import get_generator, JanusProImageGenerator, MockProceduralGenerator
from backend.app import app


class TestJanusProGenerator(unittest.IsolatedAsyncioTestCase):

    def test_factory_resolution(self):
        gen1 = get_generator("janus")
        self.assertIsInstance(gen1, JanusProImageGenerator)

        gen2 = get_generator("janus-pro")
        self.assertIsInstance(gen2, JanusProImageGenerator)

        gen3 = get_generator("janus-pro-7b")
        self.assertIsInstance(gen3, JanusProImageGenerator)

        gen4 = get_generator("deepseek")
        self.assertIsInstance(gen4, JanusProImageGenerator)

        gen5 = get_generator("deepseek-ai/janus-pro-7b")
        self.assertIsInstance(gen5, JanusProImageGenerator)

    def test_token_initialization(self):
        gen = JanusProImageGenerator(hf_token="test_hf_token_123")
        self.assertEqual(gen.hf_token, "test_hf_token_123")

    def test_extract_single_item_formats(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
            img = Image.new("RGB", (50, 50), (255, 0, 0))
            img.save(temp_path)

        try:
            # 1. Dict with 'image' dict containing 'path'
            dict_res = {"image": {"path": temp_path, "url": None}}
            extracted = JanusProImageGenerator._extract_image_from_result([dict_res])
            self.assertIsNotNone(extracted)
            self.assertEqual(extracted.size, (50, 50))

            # 2. Dict with 'path'
            dict_res2 = {"path": temp_path}
            extracted2 = JanusProImageGenerator._extract_image_from_result([dict_res2])
            self.assertIsNotNone(extracted2)
            self.assertEqual(extracted2.size, (50, 50))

            # 3. Tuple (path, caption)
            tuple_res = [(temp_path, "Generated Image")]
            extracted3 = JanusProImageGenerator._extract_image_from_result(tuple_res)
            self.assertIsNotNone(extracted3)
            self.assertEqual(extracted3.size, (50, 50))

            # 4. Direct string path
            extracted4 = JanusProImageGenerator._extract_image_from_result([temp_path])
            self.assertIsNotNone(extracted4)
            self.assertEqual(extracted4.size, (50, 50))

            # 5. Direct PIL Image
            extracted5 = JanusProImageGenerator._extract_image_from_result([img])
            self.assertIsNotNone(extracted5)
            self.assertEqual(extracted5.size, (50, 50))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def test_generate_art_with_mocked_prediction(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
            img = Image.new("RGB", (100, 100), (0, 128, 255))
            img.save(temp_path)

        try:
            gen = JanusProImageGenerator(hf_token="dummy_token")
            mock_gallery = [{"image": {"path": temp_path}}]

            with patch.object(gen, "_sync_predict", return_value=mock_gallery) as mock_predict:
                art = await gen.generate_art(
                    prompt="A cosmic phoenix rising from stardust",
                    card_name="Phoenix",
                    target_width=450,
                    target_height=320,
                )
                mock_predict.assert_called_once()
                self.assertIsInstance(art, Image.Image)
                self.assertEqual(art.size, (450, 320))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def test_generate_art_fallback_on_queue_timeout(self):
        gen = JanusProImageGenerator(hf_token="dummy_token")

        with patch.object(gen, "_sync_predict", side_effect=Exception("No GPU was available after 60s")):
            art = await gen.generate_art(
                prompt="A radiant angel with golden wings",
                card_name="Angel of Light",
                target_width=300,
                target_height=200,
            )
            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (300, 200))


class TestJanusSettingsAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_settings_get_and_post_janus(self):
        # 1. Update settings with Janus provider and HF token
        payload = {
            "provider": "janus",
            "hf_token": "hf_custom_test_token",
            "gemini_api_key": "gemini_test",
            "openai_api_key": "openai_test",
        }
        post_resp = self.client.post("/api/settings", json=payload)
        self.assertEqual(post_resp.status_code, 200)
        data = post_resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertEqual(data["provider"], "janus")
        self.assertTrue(data["has_hf_token"])

        # 2. Get settings to verify values are persisted and returned for UI pre-population
        get_resp = self.client.get("/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.json()
        self.assertEqual(get_data["provider"], "janus")
        self.assertEqual(get_data["hf_token"], "hf_custom_test_token")
        self.assertEqual(get_data["gemini_api_key"], "gemini_test")
        self.assertEqual(get_data["openai_api_key"], "openai_test")


if __name__ == "__main__":
    unittest.main()
