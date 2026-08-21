"""End-to-end integration and unit tests for MPCWithGenerativeArt."""

import asyncio
import os
import io
import unittest
from pathlib import Path
from PIL import Image

from backend.parser import parse_deck_text, CardItem
from backend.scryfall import scryfall_client
from backend.generator import get_generator, MockProceduralGenerator
from backend.compositor import (
    detect_card_boxes,
    detect_art_box,
    create_card_exclusion_mask,
    composite_full_art_card,
    composite_card,
    save_card_outputs,
    MPC_800DPI_WIDTH,
    MPC_800DPI_HEIGHT,
)
from backend.mpc_autofill import generate_mpc_xml, create_mpc_zip_bundle, calculate_mpc_bracket


class TestMPCWithGenerativeArt(unittest.TestCase):

    def test_parser_valid_input(self):
        deck_text = """
        1 Byode, Inverse Sun (PH21) 3\tAn anime girl dressed like a pixie
        2 All-Seeing Toby (SLD) 2695\tAn anime boy in a library holding a book
        4 Animate Dead (SLD) 2189\tAn old man in an anime style holding his hand up with a magic sphere surroundning him
        """
        res = parse_deck_text(deck_text)
        self.assertTrue(res.valid)
        self.assertEqual(len(res.cards), 3)
        self.assertEqual(res.total_copies, 7)
        self.assertEqual(res.cards[0].card_name, "Byode, Inverse Sun")
        self.assertEqual(res.cards[0].set_code, "PH21")
        self.assertEqual(res.cards[0].collector_number, "3")
        self.assertEqual(res.cards[0].prompt, "An anime girl dressed like a pixie")
        self.assertEqual(res.cards[1].copies, 2)
        self.assertEqual(res.cards[2].copies, 4)

    def test_parser_invalid_input(self):
        # Missing prompt
        res1 = parse_deck_text("1 Byode, Inverse Sun (PH21) 3")
        self.assertFalse(res1.valid)
        self.assertTrue(len(res1.errors) > 0)

        # Invalid copies count
        res2 = parse_deck_text("0 Byode, Inverse Sun (PH21) 3\tAn anime girl")
        self.assertFalse(res2.valid)

        # Empty
        res3 = parse_deck_text("")
        self.assertFalse(res3.valid)

    def test_mpc_bracket_calculation(self):
        self.assertEqual(calculate_mpc_bracket(5), 18)
        self.assertEqual(calculate_mpc_bracket(18), 18)
        self.assertEqual(calculate_mpc_bracket(19), 36)
        self.assertEqual(calculate_mpc_bracket(55), 55)
        self.assertEqual(calculate_mpc_bracket(100), 108)
        self.assertEqual(calculate_mpc_bracket(612), 612)

    def test_xml_generation(self):
        cards = [
            CardItem(
                id="card_1",
                line_number=1,
                copies=2,
                card_name="Byode, Inverse Sun",
                set_code="PH21",
                collector_number="3",
                prompt="An anime girl dressed like a pixie",
            )
        ]
        img_paths = {"card_1": "output/cards/card_1.png"}
        xml_str = generate_mpc_xml(cards, img_paths)
        self.assertIn("<order>", xml_str)
        self.assertIn("<quantity>2</quantity>", xml_str)
        self.assertIn("<slots>0</slots>", xml_str)
        self.assertIn("<slots>1</slots>", xml_str)
        self.assertIn("Byode, Inverse Sun", xml_str)

    def test_zip_bundle_generation(self):
        cards = [
            CardItem(
                id="card_test",
                line_number=1,
                copies=1,
                card_name="Test Card",
                set_code="TST",
                collector_number="1",
                prompt="test prompt",
            )
        ]
        # Create a dummy image
        test_img_path = Path("output/cards/card_test.png")
        test_img_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        img.save(test_img_path)

        zip_bytes = create_mpc_zip_bundle(cards, {"card_test": str(test_img_path)})
        self.assertTrue(len(zip_bytes) > 0)


class TestAsyncPipeline(unittest.IsolatedAsyncioTestCase):

    async def test_scryfall_fetch(self):
        # Test fetching Byode from Scryfall
        card = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        self.assertIsNotNone(card)
        self.assertEqual(card.set_code, "ph21")
        self.assertEqual(card.collector_number, "3")
        self.assertTrue(os.path.exists(card.cached_png_path))

    async def test_card_boxes_detection_and_masking(self):
        # 1. Fetch card data
        card_data = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        card_img = Image.open(card_data.cached_png_path).convert("RGB")
        art_crop_img = Image.open(card_data.cached_art_path).convert("RGB") if card_data.cached_art_path else None

        # 2. Detect all card boxes
        boxes = detect_card_boxes(card_img, art_crop_img=art_crop_img, type_line=card_data.type_line)
        self.assertIn("art_box", boxes)
        self.assertIn("rules_box", boxes)
        self.assertIn("stat_box", boxes)
        self.assertIn("title_box", boxes)
        self.assertIn("type_box", boxes)

        # Check bounds
        cw, ch = card_img.size
        rx1, ry1, rx2, ry2 = boxes["rules_box"]
        self.assertTrue(0 <= rx1 < rx2 <= cw)
        self.assertTrue(int(ch * 0.5) < ry1 < ry2 <= ch)

        # Universewalker Byode has statistic/loyalty box and polygon
        self.assertIsNotNone(boxes["stat_box"])
        self.assertIsNotNone(boxes["stat_polygon"])
        self.assertEqual(len(boxes["stat_polygon"]), 8)
        sx1, sy1, sx2, sy2 = boxes["stat_box"]
        self.assertTrue(0 < sx1 < sx2 <= cw)
        self.assertTrue(int(ch * 0.8) < sy1 < sy2 <= ch)

        # 3. Verify exclusion mask generation
        mask = create_card_exclusion_mask(card_img, boxes)
        self.assertEqual(mask.size, (cw, ch))
        self.assertEqual(mask.mode, "L")
        # In the center of the art box (reveal full art background), mask should be 0 (transparent)
        art_cx = (boxes["art_box"][0] + boxes["art_box"][2]) // 2
        art_cy = (boxes["art_box"][1] + boxes["art_box"][3]) // 2
        self.assertEqual(mask.getpixel((art_cx, art_cy)), 0)
        # In the center of the rules text box (preserve card text), mask should be 255 (opaque)
        rules_cx = (rx1 + rx2) // 2
        rules_cy = (ry1 + ry2) // 2
        self.assertEqual(mask.getpixel((rules_cx, rules_cy)), 255)

    async def test_full_art_generator_and_compositor(self):
        # 1. Fetch card data
        card_data = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        card_img = Image.open(card_data.cached_png_path).convert("RGB")
        art_crop_img = Image.open(card_data.cached_art_path).convert("RGB") if card_data.cached_art_path else None
        cw, ch = card_img.size

        # 2. Detect boxes
        boxes = detect_card_boxes(card_img, art_crop_img=art_crop_img, type_line=card_data.type_line)
        art_box = boxes["art_box"]
        art_cx = (art_box[0] + art_box[2]) // 2
        art_cy = (art_box[1] + art_box[3]) // 2

        # 3. Generate full-art background centered at art frame
        generator = MockProceduralGenerator()
        full_art = await generator.generate_art(
            prompt="An anime girl dressed like a pixie",
            card_name="Byode, Inverse Sun",
            target_width=cw,
            target_height=ch,
            colors=card_data.colors,
            focal_center=(art_cx, art_cy),
        )
        self.assertEqual(full_art.size, (cw, ch))

        # 4. Composite & upscale to 800 DPI
        final_img = composite_card(
            card_frame_img=card_img,
            generated_art_img=full_art,
            card_boxes=boxes,
            target_dpi=800,
        )
        self.assertEqual(final_img.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))

        # 5. Save outputs
        png_path, thumb_path = save_card_outputs("test_byode_800dpi", final_img, target_dpi=800)
        self.assertTrue(os.path.exists(png_path))
        self.assertTrue(os.path.exists(thumb_path))

        # Verify saved PNG DPI metadata
        saved_img = Image.open(png_path)
        self.assertEqual(saved_img.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))
        dpi = saved_img.info.get("dpi")
        self.assertIsNotNone(dpi)
        self.assertEqual(round(dpi[0]), 800)
        self.assertEqual(round(dpi[1]), 800)


if __name__ == "__main__":
    unittest.main()
