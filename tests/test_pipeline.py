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
from backend.compositor import detect_art_box, composite_card, save_card_outputs, MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT
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

    async def test_art_generator_and_compositor(self):
        # 1. Fetch card data
        card_data = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        card_img = Image.open(card_data.cached_png_path).convert("RGB")
        art_crop_img = Image.open(card_data.cached_art_path).convert("RGB") if card_data.cached_art_path else None

        # 2. Detect art box
        art_box = detect_art_box(card_img, art_crop_img)
        self.assertEqual(len(art_box), 4)
        bw = art_box[2] - art_box[0]
        bh = art_box[3] - art_box[1]
        self.assertTrue(bw > 200)
        self.assertTrue(bh > 200)

        # 3. Generate art
        generator = MockProceduralGenerator()
        art = await generator.generate_art(
            prompt="An anime girl dressed like a pixie",
            card_name="Byode, Inverse Sun",
            target_width=bw,
            target_height=bh,
            colors=card_data.colors,
        )
        self.assertEqual(art.size, (bw, bh))

        # 4. Composite & upscale to 800 DPI
        final_img = composite_card(card_img, art, art_box, target_dpi=800)
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
