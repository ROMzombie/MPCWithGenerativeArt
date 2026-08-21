"""API Integration tests for MPCWithGenerativeArt."""

import unittest
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

    def test_settings_endpoints(self):
        get_resp = client.get("/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        
        post_resp = client.post("/api/settings", json={"provider": "mock"})
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["provider"], "mock")

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
