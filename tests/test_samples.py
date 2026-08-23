import os
import unittest
from pathlib import Path
from PIL import Image

from backend.generate_samples import (
    SAMPLE_CARD_VARIANTS,
    generate_all_samples,
    build_samples_readme,
    DOCS_DIR,
    DOCS_IMAGES_DIR,
)
from backend.compositor import MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT


class TestSampleCardDocumentation(unittest.IsolatedAsyncioTestCase):
    def test_sample_card_variants_structure(self):
        """Validates that all standard card variants are properly defined with required metadata."""
        self.assertGreaterEqual(len(SAMPLE_CARD_VARIANTS), 12)
        
        seen_ids = set()
        for variant in SAMPLE_CARD_VARIANTS:
            self.assertIn("id", variant)
            self.assertIn("set_code", variant)
            self.assertIn("collector_number", variant)
            self.assertIn("card_name", variant)
            self.assertIn("category", variant)
            self.assertIn("description", variant)
            self.assertIn("prompt", variant)
            self.assertIn("key_elements", variant)
            self.assertGreater(len(variant["key_elements"]), 0)
            
            # IDs must be unique
            self.assertNotIn(variant["id"], seen_ids)
            seen_ids.add(variant["id"])

    async def test_generate_and_validate_all_sample_cards(self):
        """Generates all sample cards and validates their dimensions, DPI, and preview assets."""
        samples = await generate_all_samples(output_dir=DOCS_IMAGES_DIR)
        self.assertEqual(len(samples), len(SAMPLE_CARD_VARIANTS))

        for sample in samples:
            png_path = Path(sample["png_abs_path"])
            thumb_path = Path(sample["thumb_abs_path"])

            self.assertTrue(png_path.exists(), f"Missing 800 DPI output: {png_path}")
            self.assertTrue(thumb_path.exists(), f"Missing thumbnail: {thumb_path}")

            # Validate 800 DPI print image dimensions
            with Image.open(png_path) as png_img:
                self.assertEqual(png_img.size, (MPC_800DPI_WIDTH, MPC_800DPI_HEIGHT))
                dpi = png_img.info.get("dpi")
                self.assertIsNotNone(dpi)
                self.assertEqual((round(dpi[0]), round(dpi[1])), (800, 800))

            # Validate thumbnail dimensions
            with Image.open(thumb_path) as thumb_img:
                self.assertEqual(thumb_img.width, 480)
                self.assertEqual(thumb_img.height, 652)

    def test_build_and_validate_samples_readme(self):
        """Validates that docs/samples/README.md is built and embeds all sample images."""
        readme_path = DOCS_DIR / "README.md"
        content = build_samples_readme(SAMPLE_CARD_VARIANTS, output_readme=readme_path)
        
        self.assertTrue(readme_path.exists())
        self.assertIn("# MTG Card Layout Variants & Sample Gallery", content)

        for variant in SAMPLE_CARD_VARIANTS:
            self.assertIn(variant["card_name"], content)
            self.assertIn(variant["category"], content)
            self.assertIn(f"images/{variant['id']}_thumb.jpg", content)


if __name__ == "__main__":
    unittest.main()
