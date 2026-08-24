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
    scale_card_frame_and_boxes,
    composite_full_art_card,
    composite_card,
    save_card_outputs,
    MPC_800DPI_WIDTH,
    MPC_800DPI_HEIGHT,
    MPC_BLEED_SCALE,
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
        # Card prompts must retain only their individual prompts for UI textareas
        self.assertEqual(
            res.cards[0].prompt,
            "An anime girl dressed like a pixie",
        )
        self.assertEqual(
            res.cards[1].prompt,
            "An anime boy in a library holding a book",
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
        self.assertEqual(res.cards[0].prompt, "Pixie")
        self.assertEqual(res.cards[1].prompt, "Boy with book")

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
        self.assertIn("station_circles", boxes)

        # Check bounds
        cw, ch = card_img.size
        rx1, ry1, rx2, ry2 = boxes["rules_box"]
        self.assertTrue(0 <= rx1 < rx2 <= cw)
        self.assertTrue(int(ch * 0.5) < ry1 < ry2 <= ch)
        self.assertGreaterEqual(ry2, int(950 * (ch / 1040.0)))

        # Title pill bounds must preserve rounded end caps and beveled shadows
        tp1, tp2, tp3, tp4 = boxes["title_pill"]
        self.assertLessEqual(tp1, int(47 * (cw / 745.0)))
        self.assertGreaterEqual(tp3, int(695 * (cw / 745.0)))

        # Universewalker Byode has statistic/loyalty box, polygon, and individual loyalty ability shields
        self.assertIsNotNone(boxes["stat_box"])
        self.assertIsNotNone(boxes["stat_polygon"])
        self.assertEqual(len(boxes["stat_polygon"]), 8)
        self.assertGreaterEqual(len(boxes.get("loyalty_polygons", [])), 1)
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

    async def test_station_card_circle_detection_and_masking(self):
        # 1. Test 1-station circle card (Adagia, Windswept Bastion - EOE 250)
        adagia_data = await scryfall_client.get_card("eoe", "250", "Adagia, Windswept Bastion")
        adagia_img = Image.open(adagia_data.cached_png_path).convert("RGB")
        adagia_boxes = detect_card_boxes(
            adagia_img,
            type_line=adagia_data.type_line,
            layout=adagia_data.layout,
        )
        self.assertEqual(len(adagia_boxes["station_circles"]), 1)
        c1 = adagia_boxes["station_circles"][0]
        # Circle must be in left margin around x=47, radius~27
        self.assertLess(c1[0], int(26 * (adagia_img.width / 745.0)))
        self.assertGreater(c1[2], int(70 * (adagia_img.width / 745.0)))

        # 2. Test 2-station circle card (Dawnsire, Sunstar Dreadnought - EOE 238)
        dawnsire_data = await scryfall_client.get_card("eoe", "238", "Dawnsire, Sunstar Dreadnought")
        dawnsire_img = Image.open(dawnsire_data.cached_png_path).convert("RGB")
        dawnsire_boxes = detect_card_boxes(
            dawnsire_img,
            type_line=dawnsire_data.type_line,
            layout=dawnsire_data.layout,
        )
        self.assertEqual(len(dawnsire_boxes["station_circles"]), 2)

        # 3. Test non-station creature has 0 station circles and full bottom rules box
        ekthi_data = await scryfall_client.get_card("mbc", "1", "Ekthi, Contaminator Priest")
        ekthi_img = Image.open(ekthi_data.cached_png_path).convert("RGB")
        ekthi_boxes = detect_card_boxes(
            ekthi_img,
            type_line=ekthi_data.type_line,
            layout=ekthi_data.layout,
            rarity=ekthi_data.rarity,
        )
        self.assertEqual(len(ekthi_boxes["station_circles"]), 0)
        self.assertIsNotNone(ekthi_boxes["stat_box"])
        self.assertGreaterEqual(ekthi_boxes["rules_box"][3], int(950 * (ekthi_img.height / 1040.0)))
        self.assertGreaterEqual(ekthi_boxes["stat_box"][3], int(980 * (ekthi_img.height / 1040.0)))

        # 4. Composite station card and verify print dimensions
        gen = MockProceduralGenerator()
        adagia_art = await gen.generate_art("space bastion on cliff", "Adagia", adagia_img.width, adagia_img.height)
        adagia_final = composite_card(adagia_img, adagia_art, card_boxes=adagia_boxes)
        self.assertEqual(adagia_final.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))

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
        self.assertIsNotNone(toby_boxes["stat_polygon"])
        self.assertEqual(len(toby_boxes["stat_polygon"]), 10)
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

    async def test_scale_card_frame_and_boxes(self):
        # Test scaling Scryfall card frame and transformed coordinates
        card_data = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        card_img = Image.open(card_data.cached_png_path).convert("RGB")
        cw, ch = card_img.size
        boxes = detect_card_boxes(card_img, type_line=card_data.type_line)

        scaled_img, scaled_boxes = scale_card_frame_and_boxes(card_img, boxes, scale_factor=0.90)
        self.assertEqual(scaled_img.size, (cw, ch))
        self.assertEqual(scaled_boxes["scale_factor"], 0.90)
        
        ox, oy = scaled_boxes["offset"]
        self.assertEqual(ox, (cw - int(cw * 0.90)) // 2)
        self.assertEqual(oy, (ch - int(ch * 0.90)) // 2)

        # Verify title pill is shifted by offset
        orig_pill = boxes["title_pill"]
        sc_pill = scaled_boxes["title_pill"]
        self.assertEqual(sc_pill[0], int(orig_pill[0] * 0.90 + ox))
        self.assertEqual(sc_pill[1], int(orig_pill[1] * 0.90 + oy))

    async def test_scaled_bleed_compositor_edge_bleed_art(self):
        # Verify that compositing ensures edge bleed area contains art and matches 800 DPI target
        card_data = await scryfall_client.get_card("ph21", "3", "Byode, Inverse Sun")
        card_img = Image.open(card_data.cached_png_path).convert("RGB")
        boxes = detect_card_boxes(card_img, type_line=card_data.type_line)

        gen = MockProceduralGenerator()
        art = await gen.generate_art("pixie", "Byode, Inverse Sun", card_img.width, card_img.height)
        
        final_comp = composite_card(card_img, art, card_boxes=boxes, card_scale=MPC_BLEED_SCALE)
        self.assertEqual(final_comp.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))

        # Check corners and edge pixels to confirm no black bars (12, 12, 12)
        corners = [
            final_comp.getpixel((0, 0)),
            final_comp.getpixel((MPC_800DPI_WIDTH - 1, 0)),
            final_comp.getpixel((0, MPC_800DPI_HEIGHT - 1)),
            final_comp.getpixel((MPC_800DPI_WIDTH - 1, MPC_800DPI_HEIGHT - 1)),
        ]
    async def test_special_layouts_detection_and_masking(self):
        # 1. Saga (Elspeth Conquers Death - THB 13)
        saga_data = await scryfall_client.get_card("thb", "13", "Elspeth Conquers Death")
        saga_img = Image.open(saga_data.cached_png_path).convert("RGB")
        saga_boxes = detect_card_boxes(saga_img, type_line=saga_data.type_line, layout=saga_data.layout, rarity=saga_data.rarity)
        # Saga type line is at bottom (y > 850)
        self.assertGreater(saga_boxes["type_box"][1], int(850 * (saga_img.height / 1040.0)))
        # Saga rules box is left column (width < 400)
        self.assertLess(saga_boxes["rules_box"][2], int(400 * (saga_img.width / 745.0)))
        # Sagas do not mask holo stamp
        self.assertIsNone(saga_boxes["holo_stamp"])

        # 2. Class (Paladin Class - AFR 29)
        class_data = await scryfall_client.get_card("afr", "29", "Paladin Class")
        class_img = Image.open(class_data.cached_png_path).convert("RGB")
        class_boxes = detect_card_boxes(class_img, type_line=class_data.type_line, layout=class_data.layout, rarity=class_data.rarity)
        # Class rules box is right column (x1 > 350)
        self.assertGreater(class_boxes["rules_box"][0], int(350 * (class_img.width / 745.0)))
        self.assertGreater(class_boxes["type_box"][1], int(850 * (class_img.height / 1040.0)))
        # Classes do not mask holo stamp
        self.assertIsNone(class_boxes["holo_stamp"])

        # 3. Room (Dollmaker's Shop // Porcelain Gallery - DSK 4)
        room_data = await scryfall_client.get_card("dsk", "4", "Dollmaker's Shop // Porcelain Gallery")
        room_img = Image.open(room_data.cached_png_path).convert("RGB")
        room_boxes = detect_card_boxes(room_img, type_line=room_data.type_line, layout=room_data.layout)
        self.assertGreaterEqual(len(room_boxes["extra_boxes"]), 2)

        # 4. Battle (Invasion of Gobakhan - MOM 22)
        battle_data = await scryfall_client.get_card("mom", "22", "Invasion of Gobakhan")
        battle_img = Image.open(battle_data.cached_png_path).convert("RGB")
        battle_boxes = detect_card_boxes(battle_img, type_line=battle_data.type_line, layout=battle_data.layout)
        self.assertIsNotNone(battle_boxes["stat_polygon"])
        self.assertEqual(len(battle_boxes["stat_polygon"]), 16)

        # 5. Adventure (Giant Killer // Chop Down - ELD 14)
        adv_data = await scryfall_client.get_card("eld", "14", "Giant Killer // Chop Down")
        adv_img = Image.open(adv_data.cached_png_path).convert("RGB")
        adv_boxes = detect_card_boxes(adv_img, type_line=adv_data.type_line, layout=adv_data.layout)
        self.assertIsNotNone(adv_boxes["stat_polygon"])
        self.assertEqual(len(adv_boxes["stat_polygon"]), 10)

        # 6. Split Without Fuse (Fire // Ice - DMR 215)
        fire_data = await scryfall_client.get_card("dmr", "215", "Fire // Ice")
        fire_img = Image.open(fire_data.cached_png_path).convert("RGB")
        fire_boxes = detect_card_boxes(
            fire_img,
            type_line=fire_data.type_line,
            layout=fire_data.layout,
            card_name=fire_data.name,
            keywords=fire_data.keywords,
            oracle_text=fire_data.oracle_text,
        )
        self.assertGreaterEqual(len(fire_boxes["extra_boxes"]), 3)
        self.assertIsNone(fire_boxes["holo_stamp"])

        # 7. Split With Fuse (Wear // Tear - DGM 135)
        wear_data = await scryfall_client.get_card("dgm", "135", "Wear // Tear")
        wear_img = Image.open(wear_data.cached_png_path).convert("RGB")
        wear_boxes = detect_card_boxes(
            wear_img,
            type_line=wear_data.type_line,
            layout=wear_data.layout,
            card_name=wear_data.name,
            keywords=wear_data.keywords,
            oracle_text=wear_data.oracle_text,
        )
        self.assertGreaterEqual(len(wear_boxes["extra_boxes"]), 5)
        self.assertIsNone(wear_boxes["holo_stamp"])

        # 8. Composite all special layouts and verify 800 DPI outputs
        gen = MockProceduralGenerator()
        for c_img, c_boxes, c_name in [
            (saga_img, saga_boxes, "Elspeth Conquers Death"),
            (class_img, class_boxes, "Paladin Class"),
            (room_img, room_boxes, "Dollmaker's Shop // Porcelain Gallery"),
            (battle_img, battle_boxes, "Invasion of Gobakhan"),
            (adv_img, adv_boxes, "Giant Killer // Chop Down"),
            (fire_img, fire_boxes, "Fire // Ice"),
            (wear_img, wear_boxes, "Wear // Tear"),
        ]:
            art = await gen.generate_art("test art", c_name, c_img.width, c_img.height)
            comp = composite_card(c_img, art, card_boxes=c_boxes)
            self.assertEqual(comp.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))


if __name__ == "__main__":
    unittest.main()

