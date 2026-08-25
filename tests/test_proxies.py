"""Unit and integration tests for Just Proxies generator and MPC upscaling pipeline."""

import os
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from backend.parser import parse_deck_text, CardItem
from backend.compositor import (
    create_proxy_card,
    detect_card_boxes,
    get_bold_arial_font,
    save_card_outputs,
    MPC_800DPI_WIDTH,
    MPC_800DPI_HEIGHT,
)
from backend.scryfall import scryfall_client, ScryfallCardData
from backend.app import app, state, process_single_proxy_card
from fastapi.testclient import TestClient


class TestProxyPipeline(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Create a mock 745x1040 Scryfall card frame image with holo stamp & copyright text
        self.card_w = 745
        self.card_h = 1040
        self.test_img = Image.new("RGB", (self.card_w, self.card_h), (20, 25, 35))
        draw = ImageDraw.Draw(self.test_img)

        # Title bar
        draw.rectangle([46, 50, 698, 110], fill=(200, 180, 140))
        # Art box
        draw.rectangle([60, 120, 685, 577], fill=(100, 150, 220))
        # Type line
        draw.rectangle([46, 584, 698, 644], fill=(200, 180, 140))
        # Rules box
        draw.rectangle([54, 650, 690, 958], fill=(230, 225, 215))

        # Bottom copyright and collector info text bar (white/grey text)
        draw.rectangle([36, 984, 709, 1026], fill=(10, 10, 10))
        draw.text((60, 995), "001/280 R PH21 * EN  Artist Name  TM & (C) Wizards of the Coast", fill=(220, 220, 220))

        # Silver Holofoil stamp at center-bottom
        draw.ellipse([336, 946, 408, 984], fill=(230, 235, 240), outline=(180, 180, 190))

        # P/T box
        draw.rectangle([566, 918, 708, 984], fill=(200, 180, 140))
        draw.text((610, 935), "4 / 4", fill=(10, 10, 10))

    def test_proxy_card_creation_removes_copyright_and_holo(self):
        card_boxes = detect_card_boxes(self.test_img, rarity="rare")
        self.assertIsNotNone(card_boxes.get("holo_stamp"))

        proxy_result = create_proxy_card(
            card_frame_img=self.test_img,
            card_boxes=card_boxes,
            target_dpi=800,
            target_width=MPC_800DPI_WIDTH,
            target_height=MPC_800DPI_HEIGHT,
        )

        self.assertIsInstance(proxy_result, Image.Image)
        # Dimensions must match MPC 800 DPI standard (2184x2968)
        self.assertEqual(proxy_result.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))

        # Verify that the silver holofoil stamp area (around center bottom) is no longer silver (RGB > 200)
        cut_w = int(MPC_800DPI_WIDTH * (1984 / 2184))
        cut_h = int(MPC_800DPI_HEIGHT * (2768 / 2968))
        ox = (MPC_800DPI_WIDTH - cut_w) // 2
        oy = (MPC_800DPI_HEIGHT - cut_h) // 2

        holo_center_x = ox + int(372 * (cut_w / 745.0))
        holo_center_y = oy + int(965 * (cut_h / 1040.0))
        holo_pixel = proxy_result.getpixel((holo_center_x, holo_center_y))
        # It should be dark black (sum < 100), not silver (sum > 600)
        self.assertLess(sum(holo_pixel[:3]), 100)

        # Verify PROXY text is rendered with dark grey (not bright white copyright text)
        bar_center_y = oy + int(1005 * (cut_h / 1040.0))
        bar_pixel = proxy_result.getpixel((MPC_800DPI_WIDTH // 2, bar_center_y))
        # Should be dark grey / black (not bright white)
        self.assertLess(sum(bar_pixel[:3]), 450)

    def test_save_proxy_outputs(self):
        proxy_img = create_proxy_card(self.test_img)
        png_path, thumb_path = save_card_outputs("test_proxy_card_1", proxy_img, target_dpi=800)

        self.assertTrue(os.path.exists(png_path))
        self.assertTrue(os.path.exists(thumb_path))

        with Image.open(png_path) as saved:
            self.assertEqual(saved.size, (2184, 2968))
            dpi = saved.info.get("dpi")
            self.assertIsNotNone(dpi)
            self.assertEqual(int(round(dpi[0])), 800)
            self.assertEqual(int(round(dpi[1])), 800)

    def test_parser_with_and_without_prompts(self):
        # Prompt omitted (standard proxy deck list)
        deck_without_prompts = """
        1 Byode, Inverse Sun (PH21) 3
        2 All-Seeing Toby (SLD) 2695
        4 Lightning Bolt (A25) 141
        """
        res_proxy = parse_deck_text(deck_without_prompts, require_prompt=False)
        self.assertTrue(res_proxy.valid)
        self.assertEqual(len(res_proxy.cards), 3)
        self.assertEqual(res_proxy.total_copies, 7)
        self.assertEqual(res_proxy.cards[0].prompt, "")

        # Standard prompt deck list
        deck_with_prompts = """
        1 Byode, Inverse Sun (PH21) 3 # An anime girl
        1 All-Seeing Toby (SLD) 2695 # An anime boy
        """
        res_art = parse_deck_text(deck_with_prompts, require_prompt=True)
        self.assertTrue(res_art.valid)
        self.assertEqual(len(res_art.cards), 2)
        self.assertEqual(res_art.cards[0].prompt, "An anime girl")

    def test_bold_arial_font_resolution(self):
        font = get_bold_arial_font(32)
        self.assertIsNotNone(font)


class TestProxyAPIEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        state.is_generating = False
        state.cards = [
            CardItem(
                id="card_1_ph21_3",
                line_number=1,
                copies=1,
                card_name="Byode, Inverse Sun",
                set_code="PH21",
                collector_number="3",
                prompt="",
            )
        ]

    def tearDown(self):
        state.is_generating = False
        state.mode = "art"

    def test_api_generate_proxies(self):
        resp = self.client.post("/api/generate-proxies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["mode"], "proxy")
        self.assertEqual(data["total_cards"], 1)

    def test_api_cards_mode_reporting(self):
        state.mode = "proxy"
        resp = self.client.get("/api/cards")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "proxy")


if __name__ == "__main__":
    unittest.main()
