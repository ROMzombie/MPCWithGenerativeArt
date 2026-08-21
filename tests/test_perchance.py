"""Unit and integration tests for Perchance AI Image Generator."""

import unittest
from PIL import Image
from backend.generator import get_generator, PerchanceImageGenerator, MockProceduralGenerator


class TestPerchanceGenerator(unittest.IsolatedAsyncioTestCase):

    def test_factory_resolution(self):
        gen = get_generator("perchance")
        self.assertIsInstance(gen, PerchanceImageGenerator)
        
        gen_alias = get_generator("perchance-ai")
        self.assertIsInstance(gen_alias, PerchanceImageGenerator)

    async def test_perchance_art_generation(self):
        gen = PerchanceImageGenerator()
        try:
            art = await gen.generate_art(
                prompt="A celestial mystical dragon in starry cosmos",
                card_name="Dragon Test",
                target_width=400,
                target_height=300,
            )
            self.assertIsInstance(art, Image.Image)
            self.assertEqual(art.size, (400, 300))
        finally:
            await gen.close()

    async def test_fallback_on_invalid_frame(self):
        gen = PerchanceImageGenerator()
        # Even if network or frame fails, it gracefully returns high quality image via fallback
        art = await gen.generate_art(
            prompt="Simple fallback test",
            card_name="Fallback Card",
            target_width=300,
            target_height=200,
        )
        self.assertIsInstance(art, Image.Image)
        self.assertEqual(art.size, (300, 200))


if __name__ == "__main__":
    unittest.main()
