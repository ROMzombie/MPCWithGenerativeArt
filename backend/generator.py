"""Pluggable Generative Art Engine supporting Mock/Procedural, Gemini Imagen, and OpenAI DALL-E."""

import os
import math
import random
import hashlib
import io
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


class BaseImageGenerator(ABC):
    @abstractmethod
    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        """Generates an image based on prompt and target dimensions."""
        pass


class MockProceduralGenerator(BaseImageGenerator):
    """
    High-quality algorithmic procedural art generator that creates
    stylized fantasy / anime generative card art out of the box without external API keys.
    """

    COLOR_MAP = {
        "W": (248, 246, 220),  # White / Plains
        "U": (40, 110, 200),   # Blue / Island
        "B": (45, 35, 55),     # Black / Swamp
        "R": (210, 60, 45),    # Red / Mountain
        "G": (35, 140, 60),    # Green / Forest
    }

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        # Generate deterministic seed from prompt and card name
        seed_str = f"{card_name}_{prompt}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        # Base image
        img = Image.new("RGB", (target_width, target_height), (15, 18, 28))
        draw = ImageDraw.Draw(img)

        # Palette selection based on colors and prompt
        theme_colors = []
        if colors:
            for c in colors:
                if c in self.COLOR_MAP:
                    theme_colors.append(self.COLOR_MAP[c])
        if not theme_colors:
            # Infer from prompt
            p_lower = prompt.lower()
            if any(k in p_lower for k in ["fire", "flame", "red", "dragon", "lava"]):
                theme_colors.extend([(220, 50, 30), (250, 160, 40), (80, 20, 20)])
            elif any(k in p_lower for k in ["water", "ice", "blue", "ocean", "sky", "library"]):
                theme_colors.extend([(30, 90, 200), (80, 180, 240), (10, 30, 70)])
            elif any(k in p_lower for k in ["death", "dark", "shadow", "necromancer", "demon", "sphere"]):
                theme_colors.extend([(60, 30, 80), (140, 40, 180), (20, 15, 30)])
            elif any(k in p_lower for k in ["forest", "nature", "pixie", "green", "elf"]):
                theme_colors.extend([(30, 130, 60), (110, 200, 80), (15, 50, 25)])
            elif any(k in p_lower for k in ["sun", "holy", "light", "angel", "gold"]):
                theme_colors.extend([(240, 210, 80), (255, 245, 180), (180, 120, 40)])
            else:
                theme_colors.extend([(80, 60, 150), (200, 90, 140), (40, 120, 180)])

        c1 = rng.choice(theme_colors)
        c2 = (
            min(255, max(0, c1[0] + rng.randint(-50, 50))),
            min(255, max(0, c1[1] + rng.randint(-50, 50))),
            min(255, max(0, c1[2] + rng.randint(-50, 50))),
        )
        c3 = (rng.randint(20, 60), rng.randint(20, 60), rng.randint(30, 80))

        # 1. Background multi-point gradient
        cx, cy = target_width // 2, target_height // 2
        for y in range(0, target_height, 4):
            t_y = y / target_height
            for x in range(0, target_width, 4):
                t_x = x / target_width
                r = int(c3[0] * (1 - t_y) + c1[0] * t_y * 0.7 + c2[0] * t_x * 0.3)
                g = int(c3[1] * (1 - t_y) + c1[1] * t_y * 0.7 + c2[1] * t_x * 0.3)
                b = int(c3[2] * (1 - t_y) + c1[2] * t_y * 0.7 + c2[2] * t_x * 0.3)
                draw.rectangle([x, y, x + 4, y + 4], fill=(min(255, r), min(255, g), min(255, b)))

        # 2. Glowing celestial / magic orbs and nebulae
        num_orbs = rng.randint(4, 8)
        for _ in range(num_orbs):
            ox = rng.randint(int(target_width * 0.1), int(target_width * 0.9))
            oy = rng.randint(int(target_height * 0.1), int(target_height * 0.9))
            radius = rng.randint(int(target_width * 0.15), int(target_width * 0.45))
            orb_color = rng.choice(theme_colors)
            for step in range(radius, 0, -8):
                alpha = int(180 * (1 - (step / radius) ** 0.8))
                col = (
                    min(255, int(orb_color[0] + (255 - orb_color[0]) * (1 - step / radius))),
                    min(255, int(orb_color[1] + (255 - orb_color[1]) * (1 - step / radius))),
                    min(255, int(orb_color[2] + (255 - orb_color[2]) * (1 - step / radius))),
                )
                draw.ellipse([ox - step, oy - step, ox + step, oy + step], outline=col, width=4)

        # 3. Dynamic atmospheric geometric fractal arcs / rune lines
        for i in range(rng.randint(6, 12)):
            start_x = rng.randint(0, target_width)
            start_y = rng.randint(0, target_height)
            angle = rng.uniform(0, 2 * math.pi)
            length = rng.randint(int(target_width * 0.3), int(target_width * 0.8))
            end_x = start_x + int(length * math.cos(angle))
            end_y = start_y + int(length * math.sin(angle))
            draw.line([(start_x, start_y), (end_x, end_y)], fill=(255, 255, 255), width=rng.randint(1, 3))

        # 4. Stylized character / silhouette focal figure
        focal_x = int(target_width * rng.uniform(0.4, 0.6))
        focal_y = int(target_height * rng.uniform(0.45, 0.65))
        focal_size = int(min(target_width, target_height) * 0.32)

        # Halo aura behind subject
        for r in range(focal_size + 40, focal_size, -4):
            draw.ellipse(
                [focal_x - r, focal_y - r, focal_x + r, focal_y + r],
                outline=(255, 240, 180),
                width=3,
            )

        # Mystical core
        draw.ellipse(
            [focal_x - focal_size, focal_y - focal_size, focal_x + focal_size, focal_y + focal_size],
            fill=(25, 20, 35),
            outline=(240, 210, 120),
            width=5,
        )

        # 5. Fine sparkles / star field
        for _ in range(120):
            sx = rng.randint(0, target_width - 1)
            sy = rng.randint(0, target_height - 1)
            intensity = rng.randint(150, 255)
            draw.point((sx, sy), fill=(intensity, intensity, intensity))

        # 6. Subtle stylish typography overlay on generated art
        try:
            font_title = ImageFont.load_default()
        except Exception:
            font_title = None

        # Text banner on art bottom
        banner_h = int(target_height * 0.14)
        banner_y = target_height - banner_h
        draw.rectangle([0, banner_y, target_width, target_height], fill=(10, 12, 18))
        draw.line([(0, banner_y), (target_width, banner_y)], fill=(210, 180, 100), width=2)

        # Write prompt on the procedural art
        clean_prompt = prompt[:75] + ("..." if len(prompt) > 75 else "")
        draw.text((16, banner_y + 8), f"PROMPT: {clean_prompt}", fill=(240, 240, 245), font=font_title)
        draw.text((16, banner_y + banner_h - 18), f"[AI Generative Art Preview: {card_name}]", fill=(160, 170, 190), font=font_title)

        # Smooth artistic blur & slight sharpening filter
        img = img.filter(ImageFilter.SMOOTH_MORE)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
        color_enhancer = ImageEnhance.Color(img)
        img = color_enhancer.enhance(1.2)

        return img


class GeminiImageGenerator(BaseImageGenerator):
    """Generates images using Google Gemini / Imagen 3 API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        if not self.api_key:
            # Fallback to procedural generator if no key provided
            return await MockProceduralGenerator().generate_art(prompt, card_name, target_width, target_height, colors, flavor_name)

        # Formulate prompt optimized for card art
        full_prompt = f"Fantasy trading card illustration of: {prompt}. Card subject: {card_name}. Highly detailed digital painting, 8k resolution, cinematic lighting, card art composition, clean framing."

        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={self.api_key}"
        payload = {
            "instances": [{"prompt": full_prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "4:3" if target_width > target_height else "3:4",
                "outputOptions": {"mimeType": "image/png"},
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                predictions = data.get("predictions", [])
                if predictions and "bytesBase64Encoded" in predictions[0]:
                    import base64
                    img_bytes = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    return img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # If API failed, fallback gracefully to procedural mock
        print(f"[Gemini Generator] Imagen API request failed (HTTP {resp.status_code if 'resp' in locals() else 'unknown'}). Using procedural fallback.")
        return await MockProceduralGenerator().generate_art(prompt, card_name, target_width, target_height, colors, flavor_name)


class OpenAIImageGenerator(BaseImageGenerator):
    """Generates images using OpenAI DALL-E 3 API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        if not self.api_key:
            return await MockProceduralGenerator().generate_art(prompt, card_name, target_width, target_height, colors, flavor_name)

        full_prompt = f"Fantasy card game artwork: {prompt}, character {card_name}, vibrant, detailed digital art."
        url = "https://api.openai.com/v1/images/generations"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "dall-e-3",
            "prompt": full_prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                b64 = data["data"][0]["b64_json"]
                import base64
                img_bytes = base64.b64decode(b64)
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                return img.resize((target_width, target_height), Image.Resampling.LANCZOS)

class PerchanceImageGenerator(BaseImageGenerator):
    """
    Generates AI art through Perchance.org text-to-image generator using headless Playwright.
    Provides free high quality fantasy and stylized trading card art without requiring API keys.
    Runs inside a dedicated Proactor loop worker for complete Windows/uvicorn compatibility.
    """

    _instance: Optional["PerchanceImageGenerator"] = None

    def __init__(self):
        self._lock = asyncio.Lock()

    @staticmethod
    async def _async_generate_internal(
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
    ) -> Image.Image:
        import base64
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                try:
                    await page.goto("https://perchance.org/ai-text-to-image-generator", wait_until="load", timeout=45000)

                    # Locate the dynamic Perchance generator iframe
                    target_frame = None
                    for _ in range(40):
                        await asyncio.sleep(0.5)
                        for f in page.frames:
                            if f != page.main_frame:
                                try:
                                    inp_check = await f.query_selector("#description-search-input")
                                    if inp_check:
                                        target_frame = f
                                        break
                                except Exception:
                                    pass
                        if target_frame:
                            break

                    if not target_frame:
                        raise TimeoutError("Could not locate Perchance generator frame.")

                    full_prompt = f"Fantasy trading card game artwork of {card_name}, {prompt}, detailed digital painting, vibrant lighting"

                    inp = await target_frame.wait_for_selector("#description-search-input", timeout=15000)
                    await inp.fill(full_prompt)

                    btn = await target_frame.query_selector("#generate-button")
                    if btn:
                        await btn.click()

                    # Wait for generated image URL to appear
                    new_img_bytes = None
                    for _ in range(60):
                        await asyncio.sleep(0.5)
                        imgs = await target_frame.query_selector_all("img")
                        for img in imgs:
                            src = await img.get_attribute("src")
                            if src and ("downloadTemporaryImage" in src or "userGenImage" in src):
                                b64 = await target_frame.evaluate("""async (imgEl) => {
                                    const canvas = document.createElement('canvas');
                                    canvas.width = imgEl.naturalWidth || imgEl.width;
                                    canvas.height = imgEl.naturalHeight || imgEl.height;
                                    const ctx = canvas.getContext('2d');
                                    ctx.drawImage(imgEl, 0, 0);
                                    return canvas.toDataURL('image/png').split(',')[1];
                                }""", img)
                                if b64:
                                    new_img_bytes = base64.b64decode(b64)
                                    break
                        if new_img_bytes:
                            break

                    if not new_img_bytes:
                        raise TimeoutError("Timed out waiting for Perchance art generation.")

                    pil_img = Image.open(io.BytesIO(new_img_bytes)).convert("RGB")
                    return pil_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                finally:
                    await page.close()
            finally:
                await browser.close()

    @staticmethod
    def _run_in_proactor_loop(coro_fn, *args):
        import sys
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro_fn(*args))
        finally:
            loop.close()

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        try:
            async with self._lock:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None,
                    self._run_in_proactor_loop,
                    self._async_generate_internal,
                    prompt,
                    card_name,
                    target_width,
                    target_height,
                )
        except Exception as e:
            print(f"[Perchance Generator] Failed to generate art ({e}). Using procedural fallback.")
            return await MockProceduralGenerator().generate_art(
                prompt=prompt,
                card_name=card_name,
                target_width=target_width,
                target_height=target_height,
                colors=colors,
                flavor_name=flavor_name,
            )

    async def close(self):
        """No persistent resources needing explicit close."""
        pass


class JanusProImageGenerator(BaseImageGenerator):
    """
    Generates AI art using DeepSeek Janus-Pro-7B via Hugging Face Space (deepseek-ai/Janus-Pro-7B).
    Provides multimodal text-to-image generation with support for optional Hugging Face tokens
    for higher ZeroGPU priority.
    """

    SPACE_ID = "deepseek-ai/Janus-Pro-7B"

    def __init__(self, hf_token: Optional[str] = None):
        self.hf_token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN", "")

    @staticmethod
    def _extract_image_from_result(result: Any) -> Optional[Image.Image]:
        """Extracts a PIL Image from Gradio Gallery response format."""
        if not result:
            return None

        if isinstance(result, list):
            for item in result:
                img = JanusProImageGenerator._extract_single_item(item)
                if img is not None:
                    return img
        else:
            return JanusProImageGenerator._extract_single_item(result)
        return None

    @staticmethod
    def _extract_single_item(item: Any) -> Optional[Image.Image]:
        if isinstance(item, Image.Image):
            return item.convert("RGB")
        if isinstance(item, dict):
            # Gradio GalleryData dict format: {'image': {'path': '...'}}
            if "image" in item:
                sub = item["image"]
                if isinstance(sub, dict):
                    p = sub.get("path") or sub.get("url")
                    if p and os.path.exists(p):
                        return Image.open(p).convert("RGB")
                elif isinstance(sub, str) and os.path.exists(sub):
                    return Image.open(sub).convert("RGB")
            if "path" in item:
                p = item["path"]
                if p and os.path.exists(p):
                    return Image.open(p).convert("RGB")
        elif isinstance(item, (tuple, list)) and len(item) > 0:
            p = item[0]
            if isinstance(p, str) and os.path.exists(p):
                return Image.open(p).convert("RGB")
            elif isinstance(p, dict):
                return JanusProImageGenerator._extract_single_item(p)
        elif isinstance(item, str) and os.path.exists(item):
            return Image.open(item).convert("RGB")
        return None

    def _sync_predict(self, prompt: str, seed: int) -> Any:
        from gradio_client import Client
        token = self.hf_token.strip() if self.hf_token else None
        client = Client(self.SPACE_ID, token=token)
        return client.predict(

            prompt=prompt,
            seed=seed,
            guidance=5.0,
            t2i_temperature=1.0,
            api_name="/generate_image",
        )

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
    ) -> Image.Image:
        try:
            full_prompt = f"Fantasy trading card artwork of {card_name}, {prompt}, detailed digital painting, vibrant lighting"
            seed_str = f"{card_name}_{prompt}"
            seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % 100000

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._sync_predict, full_prompt, seed)

            pil_img = self._extract_image_from_result(result)
            if pil_img is not None:
                return pil_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            else:
                raise ValueError("No valid image could be extracted from Janus-Pro-7B response.")

        except Exception as e:
            print(f"[Janus Pro Generator] Generation via Hugging Face Space failed ({e}). Using procedural fallback.")
            return await MockProceduralGenerator().generate_art(
                prompt=prompt,
                card_name=card_name,
                target_width=target_width,
                target_height=target_height,
                colors=colors,
                flavor_name=flavor_name,
            )


# Global singleton instance for Perchance generator to reuse browser
_global_perchance_generator: Optional[PerchanceImageGenerator] = None


def get_generator(
    provider: str = "perchance",
    api_key: Optional[str] = None,
    hf_token: Optional[str] = None,
) -> BaseImageGenerator:
    """Factory to retrieve requested image generator."""
    global _global_perchance_generator
    p = provider.lower().strip()
    if p in ["janus", "janus-pro", "janus-pro-7b", "deepseek", "deepseek-ai", "deepseek-ai/janus-pro-7b"]:
        return JanusProImageGenerator(hf_token=hf_token or api_key)
    elif p in ["perchance", "perchance-ai"]:
        if _global_perchance_generator is None:
            _global_perchance_generator = PerchanceImageGenerator()
        return _global_perchance_generator
    elif p in ["gemini", "imagen", "google"]:
        return GeminiImageGenerator(api_key=api_key)
    elif p in ["openai", "dalle", "dall-e"]:
        return OpenAIImageGenerator(api_key=api_key)
    else:
        return MockProceduralGenerator()


