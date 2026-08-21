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

    def test_parser_global_prompt(self):
        deck_text = """# in watercolor studio ghibli fantasy anime style
        1 Byode, Inverse Sun (PH21) 3\tAn anime girl dressed like a pixie
        2 All-Seeing Toby (SLD) 2695\tAn anime boy in a library holding a book
        """
        res = parse_deck_text(deck_text)
        self.assertTrue(res.valid)
        self.assertEqual(res.global_prompt, "in watercolor studio ghibli fantasy anime style")
        self.assertEqual(len(res.cards), 2)
        self.assertEqual(
            res.cards[0].prompt,
            "in watercolor studio ghibli fantasy anime style An anime girl dressed like a pixie",
        )
        self.assertEqual(
            res.cards[1].prompt,
            "in watercolor studio ghibli fantasy anime style An anime boy in a library holding a book",
        )

    def test_parser_global_prompt_variations(self):
        # Leading whitespace and comments throughout
        deck_text = """
        
        # vibrant 8k digital art
        # regular comment
        1 Byode, Inverse Sun (PH21) 3\tPixie
        // another comment
        1 All-Seeing Toby (SLD) 2695\tBoy with book
        """
        res = parse_deck_text(deck_text)
        self.assertTrue(res.valid)
        self.assertEqual(res.global_prompt, "vibrant 8k digital art")
        self.assertEqual(res.cards[0].prompt, "vibrant 8k digital art Pixie")
        self.assertEqual(res.cards[1].prompt, "vibrant 8k digital art Boy with book")

        # Comment on first line with // is not global prompt
        deck_no_global = """// just a regular comment
        1 Byode, Inverse Sun (PH21) 3\tPixie
        """
        res_no_global = parse_deck_text(deck_no_global)
        self.assertTrue(res_no_global.valid)
        self.assertIsNone(res_no_global.global_prompt)
        self.assertEqual(res_no_global.cards[0].prompt, "Pixie")

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

    async def test_borderless_creature_and_noncreature_masking(self):
        # 1. Test All-Seeing Toby (SLD 2695) - Borderless Creature with Nickname / Subtitle
        toby_data = await scryfall_client.get_card("sld", "2695", "All-Seeing Toby")
        toby_img = Image.open(toby_data.cached_png_path).convert("RGB")
        toby_boxes = detect_card_boxes(
            toby_img,
            type_line=toby_data.type_line,
            flavor_name=toby_data.flavor_name,
            border_color=toby_data.border_color,
            frame_effects=toby_data.frame_effects,
            layout=toby_data.layout,
            full_art=toby_data.full_art,
        )
        self.assertTrue(toby_boxes["is_borderless"])
        self.assertIsNotNone(toby_boxes["stat_box"])
        self.assertIsNone(toby_boxes["stat_polygon"])
        # Title box must include subtitle banner (height > 100)
        self.assertGreater(toby_boxes["title_box"][3] - toby_boxes["title_box"][1], 90)

        # 2. Test Animate Dead (SLD 2189) - Borderless Non-Creature (Enchantment)
        animate_data = await scryfall_client.get_card("sld", "2189", "Animate Dead")
        animate_img = Image.open(animate_data.cached_png_path).convert("RGB")
        animate_boxes = detect_card_boxes(
            animate_img,
            type_line=animate_data.type_line,
            flavor_name=animate_data.flavor_name,
            border_color=animate_data.border_color,
            frame_effects=animate_data.frame_effects,
            layout=animate_data.layout,
            full_art=animate_data.full_art,
        )
        self.assertTrue(animate_boxes["is_borderless"])
        # Non-creature enchantment must have NO stat box or stat polygon
        self.assertIsNone(animate_boxes["stat_box"])
        self.assertIsNone(animate_boxes["stat_polygon"])

        # 3. Composite both and verify output dimensions
        gen = MockProceduralGenerator()
        toby_art = await gen.generate_art("scout in watchtower", "All-Seeing Toby", toby_img.width, toby_img.height)
        toby_final = composite_card(toby_img, toby_art, card_boxes=toby_boxes)
        self.assertEqual(toby_final.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))

        animate_art = await gen.generate_art("old man with white beard", "Animate Dead", animate_img.width, animate_img.height)
        animate_final = composite_card(animate_img, animate_art, card_boxes=animate_boxes)
        self.assertEqual(animate_final.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))


if __name__ == "__main__":
    unittest.main()
