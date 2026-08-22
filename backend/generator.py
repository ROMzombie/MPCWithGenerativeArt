"""Pluggable Generative Art Engine supporting Mock/Procedural, Gemini Imagen, and OpenAI DALL-E."""

import os
import math
import random
import hashlib
import io
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps


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
        focal_center: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        """Generates an image based on prompt, target dimensions, and optional focal center coordinates."""
        pass


class MockProceduralGenerator(BaseImageGenerator):
    """
    High-quality algorithmic procedural art generator that creates
    stylized fantasy / anime generative full-art card backgrounds out of the box without external API keys.
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
        focal_center: Optional[Tuple[int, int]] = None,
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

        # Default focal center to art frame location (~33% down from top) if not provided
        if focal_center is not None:
            cx, cy = focal_center
        else:
            cx = target_width // 2
            cy = int(target_height * 0.335)

        # 1. Background multi-point gradient radiating from focal center
        for y in range(0, target_height, 4):
            t_y = y / target_height
            for x in range(0, target_width, 4):
                t_x = x / target_width
                dist = math.sqrt(((x - cx) / target_width) ** 2 + ((y - cy) / target_height) ** 2)
                falloff = max(0.0, 1.0 - min(1.0, dist * 1.5))
                r = int(c3[0] * (1 - t_y) + c1[0] * falloff * 0.7 + c2[0] * t_x * 0.3)
                g = int(c3[1] * (1 - t_y) + c1[1] * falloff * 0.7 + c2[1] * t_x * 0.3)
                b = int(c3[2] * (1 - t_y) + c1[2] * falloff * 0.7 + c2[2] * t_x * 0.3)
                draw.rectangle([x, y, x + 4, y + 4], fill=(min(255, r), min(255, g), min(255, b)))

        # 2. Glowing celestial / magic orbs and nebulae centered around art region
        num_orbs = rng.randint(5, 9)
        for _ in range(num_orbs):
            ox = cx + rng.randint(int(-target_width * 0.35), int(target_width * 0.35))
            oy = cy + rng.randint(int(-target_height * 0.25), int(target_height * 0.35))
            radius = rng.randint(int(target_width * 0.15), int(target_width * 0.45))
            orb_color = rng.choice(theme_colors)
            for step in range(radius, 0, -8):
                col = (
                    min(255, int(orb_color[0] + (255 - orb_color[0]) * (1 - step / radius))),
                    min(255, int(orb_color[1] + (255 - orb_color[1]) * (1 - step / radius))),
                    min(255, int(orb_color[2] + (255 - orb_color[2]) * (1 - step / radius))),
                )
                draw.ellipse([ox - step, oy - step, ox + step, oy + step], outline=col, width=4)

        # 3. Dynamic atmospheric geometric fractal arcs / rune lines
        for i in range(rng.randint(8, 14)):
            start_x = rng.randint(0, target_width)
            start_y = rng.randint(0, target_height)
            angle = rng.uniform(0, 2 * math.pi)
            length = rng.randint(int(target_width * 0.3), int(target_width * 0.8))
            end_x = start_x + int(length * math.cos(angle))
            end_y = start_y + int(length * math.sin(angle))
            draw.line([(start_x, start_y), (end_x, end_y)], fill=(255, 255, 255), width=rng.randint(1, 3))

        # 4. Stylized character / silhouette focal figure precisely centered on the art frame
        focal_x = int(cx + rng.uniform(-0.02, 0.02) * target_width)
        focal_y = int(cy + rng.uniform(-0.02, 0.02) * target_height)
        focal_size = int(min(target_width, target_height) * 0.22)

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

        # 5. Fine sparkles / star field across the full card background
        for _ in range(160):
            sx = rng.randint(0, target_width - 1)
            sy = rng.randint(0, target_height - 1)
            intensity = rng.randint(150, 255)
            draw.point((sx, sy), fill=(intensity, intensity, intensity))

        # Smooth artistic blur & slight sharpening filter
        img = img.filter(ImageFilter.SMOOTH_MORE)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
        color_enhancer = ImageEnhance.Color(img)
        img = color_enhancer.enhance(1.2)

        return img


def get_generator_timeout(read_timeout: Optional[float] = None) -> httpx.Timeout:
    """
    Returns an httpx.Timeout object configured for AI image generation.
    Supports overriding via GENERATOR_TIMEOUT, GENERATOR_READ_TIMEOUT,
    GENERATOR_CONNECT_TIMEOUT, and GENERATOR_WRITE_TIMEOUT environment variables.
    Defaults to 300.0s (5 minutes) total and read timeout, 60.0s connect/write.
    """
    total = float(os.environ.get("GENERATOR_TIMEOUT", "300.0"))
    read = read_timeout if read_timeout is not None else float(os.environ.get("GENERATOR_READ_TIMEOUT", str(total)))
    connect = float(os.environ.get("GENERATOR_CONNECT_TIMEOUT", "60.0"))
    write = float(os.environ.get("GENERATOR_WRITE_TIMEOUT", "60.0"))
    return httpx.Timeout(total, connect=connect, read=read, write=write)


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
        focal_center: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        if not self.api_key:
            # Fallback to procedural generator if no key provided
            return await MockProceduralGenerator().generate_art(
                prompt=prompt,
                card_name=card_name,
                target_width=target_width,
                target_height=target_height,
                colors=colors,
                flavor_name=flavor_name,
                focal_center=focal_center,
            )

        # Formulate prompt optimized for full-art background
        full_prompt = (
            f"Full-bleed vertical fantasy digital painting of: {prompt}. "
            f"Primary subject composed and centered in upper frame, atmospheric extended background below, "
            f"highly detailed digital painting, 8k resolution, cinematic lighting, vertical composition."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={self.api_key}"
        payload = {
            "instances": [{"prompt": full_prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "3:4" if target_height > target_width else "4:3",
                "outputOptions": {"mimeType": "image/png"},
            },
        }

        try:
            timeout_config = get_generator_timeout()
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    predictions = data.get("predictions", [])
                    if predictions and "bytesBase64Encoded" in predictions[0]:
                        import base64
                        img_bytes = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        return ImageOps.fit(img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
                else:
                    print(f"[Gemini Generator] Imagen API request failed (HTTP {resp.status_code}: {resp.text}). Using procedural fallback.")
        except Exception as e:
            err_msg = str(e) or repr(e)
            print(f"[Gemini Generator] Generation failed ({type(e).__name__}: {err_msg}). Using procedural fallback.")

        # If API failed, fallback gracefully to procedural mock
        return await MockProceduralGenerator().generate_art(
            prompt=prompt,
            card_name=card_name,
            target_width=target_width,
            target_height=target_height,
            colors=colors,
            flavor_name=flavor_name,
            focal_center=focal_center,
        )


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
        focal_center: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        if not self.api_key:
            return await MockProceduralGenerator().generate_art(
                prompt=prompt,
                card_name=card_name,
                target_width=target_width,
                target_height=target_height,
                colors=colors,
                flavor_name=flavor_name,
                focal_center=focal_center,
            )

        full_prompt = f"Full-bleed vertical fantasy digital painting of: {prompt}, main focal character in upper half, vibrant atmospheric digital painting."
        url = "https://api.openai.com/v1/images/generations"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "dall-e-3",
            "prompt": full_prompt,
            "n": 1,
            "size": "1024x1792" if target_height > target_width else "1024x1024",
            "response_format": "b64_json",
        }

        try:
            timeout_config = get_generator_timeout()
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    b64 = data["data"][0]["b64_json"]
                    import base64
                    img_bytes = base64.b64decode(b64)
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    return ImageOps.fit(img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
                else:
                    print(f"[OpenAI Generator] DALL-E API request failed (HTTP {resp.status_code}: {resp.text}). Using procedural fallback.")
        except Exception as e:
            err_msg = str(e) or repr(e)
            print(f"[OpenAI Generator] Generation failed ({type(e).__name__}: {err_msg}). Using procedural fallback.")

        return await MockProceduralGenerator().generate_art(
            prompt=prompt,
            card_name=card_name,
            target_width=target_width,
            target_height=target_height,
            colors=colors,
            flavor_name=flavor_name,
            focal_center=focal_center,
        )


class GrokImageGenerator(BaseImageGenerator):
    """Generates images using xAI Grok API (grok-imagine-image-2.0)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "grok-imagine-image-2.0"):
        raw_key = api_key or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY", "")
        self.api_key = raw_key.strip()
        if self.api_key.lower().startswith("bearer "):
            self.api_key = self.api_key[7:].strip()
        self.model = model

    async def generate_art(
        self,
        prompt: str,
        card_name: str,
        target_width: int,
        target_height: int,
        colors: Optional[List[str]] = None,
        flavor_name: Optional[str] = None,
        focal_center: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        if not self.api_key:
            return await MockProceduralGenerator().generate_art(
                prompt=prompt,
                card_name=card_name,
                target_width=target_width,
                target_height=target_height,
                colors=colors,
                flavor_name=flavor_name,
                focal_center=focal_center,
            )

        full_prompt = (
            f"Full-bleed vertical fantasy digital painting of: {prompt}, "
            f"primary subject composed and centered in upper composition, atmospheric extended background, "
            f"highly detailed digital painting, vibrant cinematic lighting, vertical composition."
        )
        url = "https://api.x.ai/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        aspect_ratio = "3:4" if target_height > target_width else "4:3"
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "n": 1,
            "aspect_ratio": aspect_ratio,
        }

        try:
            # Extended timeout for AI image generation (up to 300s default, configurable via env)
            timeout_config = get_generator_timeout()
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    predictions = data.get("data", [])
                    if predictions:
                        item = predictions[0]
                        if "b64_json" in item and item["b64_json"]:
                            import base64
                            img_bytes = base64.b64decode(item["b64_json"])
                            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                            return ImageOps.fit(img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
                        elif "url" in item and item["url"]:
                            img_resp = await client.get(item["url"], timeout=timeout_config)
                            if img_resp.status_code == 200:
                                img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                                return ImageOps.fit(img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
                            else:
                                print(f"[Grok Generator] Failed to download generated image from URL (HTTP {img_resp.status_code}).")
                else:
                    error_detail = resp.text
                    print(f"[Grok Generator] API request failed (HTTP {resp.status_code}: {error_detail}). Using procedural fallback.")
        except Exception as e:
            err_msg = str(e) or repr(e)
            print(f"[Grok Generator] Generation failed ({type(e).__name__}: {err_msg}). Using procedural fallback.")

        return await MockProceduralGenerator().generate_art(
            prompt=prompt,
            card_name=card_name,
            target_width=target_width,
            target_height=target_height,
            colors=colors,
            flavor_name=flavor_name,
            focal_center=focal_center,
        )


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
                    await page.goto("https://perchance.org/ai-text-to-image-generator", wait_until="load", timeout=90000)

                    # Locate the dynamic Perchance generator iframe
                    target_frame = None
                    for _ in range(60):
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

                    full_prompt = f"Full-bleed vertical fantasy digital painting of {prompt}, main subject in upper half, detailed digital painting, vibrant lighting"

                    inp = await target_frame.wait_for_selector("#description-search-input", timeout=30000)
                    await inp.fill(full_prompt)

                    btn = await target_frame.query_selector("#generate-button")
                    if btn:
                        await btn.click()

                    # Wait for generated image URL to appear (up to 120s)
                    new_img_bytes = None
                    for _ in range(240):
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
                    return ImageOps.fit(pil_img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
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
        focal_center: Optional[Tuple[int, int]] = None,
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
                focal_center=focal_center,
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
        focal_center: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        try:
            full_prompt = f"Full-bleed vertical fantasy digital painting of {prompt}, main subject centered in upper composition, detailed digital painting, vibrant lighting"
            seed_str = f"{card_name}_{prompt}"
            seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % 100000

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._sync_predict, full_prompt, seed)

            pil_img = self._extract_image_from_result(result)
            if pil_img is not None:
                return ImageOps.fit(pil_img, (target_width, target_height), centering=(0.5, 0.33), method=Image.Resampling.LANCZOS)
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
                focal_center=focal_center,
            )


# Global singleton instance for Perchance generator to reuse browser
_global_perchance_generator: Optional[PerchanceImageGenerator] = None


def get_generator(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    hf_token: Optional[str] = None,
    xai_api_key: Optional[str] = None,
) -> BaseImageGenerator:
    """Factory to retrieve requested image generator."""
    global _global_perchance_generator
    if not provider:
        provider = os.environ.get("GENERATOR_PROVIDER") or os.environ.get("ART_GENERATOR") or os.environ.get("PROVIDER") or "perchance"
    p = provider.lower().strip()
    if p in ["grok", "xai", "grok-2", "grok-imagine", "grok-imagine-image", "grok-imagine-image-2.0", "x-ai"]:
        return GrokImageGenerator(api_key=xai_api_key or api_key)
    elif p in ["janus", "janus-pro", "janus-pro-7b", "deepseek", "deepseek-ai", "deepseek-ai/janus-pro-7b"]:
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



