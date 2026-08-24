"""FastAPI Backend Application for MPCWithGenerativeArt."""

import sys
import os
import json
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv, set_key

_TEST_FALLBACK_ENV: Optional[Path] = None

def get_env_file() -> Optional[Path]:
    """Get the target .env file path, supporting ENV_FILE env var override or disabling."""
    global _TEST_FALLBACK_ENV
    env_path = os.environ.get("ENV_FILE")
    if env_path is not None:
        if not env_path or env_path.lower() in ("none", "false", "off", "disable", "disabled"):
            return None
        return Path(env_path)

    # If running under unittest or pytest or TESTING flag, never touch local production .env
    if "unittest" in sys.modules or "pytest" in sys.modules or os.environ.get("TESTING") == "true":
        if _TEST_FALLBACK_ENV is None:
            import tempfile
            temp_f = tempfile.NamedTemporaryFile(suffix=".env", delete=False)
            _TEST_FALLBACK_ENV = Path(temp_f.name)
            temp_f.close()
        return _TEST_FALLBACK_ENV

    return Path(".env")

ENV_FILE = get_env_file()
if ENV_FILE and ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)

from backend.parser import parse_deck_text, CardItem, ParseResult
from backend.scryfall import scryfall_client
from backend.generator import get_generator, MockProceduralGenerator
from backend.compositor import (
    detect_card_boxes,
    detect_art_box,
    composite_card,
    composite_full_art_card,
    save_card_outputs,
    MPC_BLEED_SCALE,
    scale_card_frame_and_boxes,
)
from backend.mpc_autofill import generate_mpc_xml, create_mpc_zip_bundle, mpc_uploader
from PIL import Image

app = FastAPI(
    title="MPCWithGenerativeArt",
    description="Generate custom-appearing decks of cards for MakePlayingCards using generative tools",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Application state
class AppState:
    def __init__(self):
        self.cards: List[CardItem] = []
        self.card_image_paths: Dict[str, str] = {}
        self.card_thumb_paths: Dict[str, str] = {}
        self.raw_deck_text: str = ""
        self.global_prompt: Optional[str] = None
        self.hf_token: str = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN", "")
        self.gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.xai_api_key: str = os.environ.get("XAI_API_KEY", "") or os.environ.get("GROK_API_KEY", "")
        
        env_provider = os.environ.get("GENERATOR_PROVIDER") or os.environ.get("ART_GENERATOR") or os.environ.get("PROVIDER")
        if env_provider:
            self.provider: str = env_provider.strip().lower()
        elif self.hf_token:
            self.provider: str = "janus"
        else:
            self.provider: str = "perchance"
        self.is_generating: bool = False
        self.progress_subscribers: List[asyncio.Queue] = []

    def broadcast_card_update(self, card: CardItem):
        data = {
            "type": "card_update",
            "card": card.model_dump(),
        }
        for q in list(self.progress_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass

    def broadcast_log(self, message: str, level: str = "info"):
        data = {
            "type": "log",
            "message": message,
            "level": level,
        }
        for q in list(self.progress_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass


state = AppState()

# Ensure directories exist
os.makedirs("output/cards", exist_ok=True)
os.makedirs("output/thumbnails", exist_ok=True)
os.makedirs("cache/scryfall", exist_ok=True)
os.makedirs("frontend", exist_ok=True)


class ParseRequest(BaseModel):
    text: str


class RegenerateRequest(BaseModel):
    prompt: str


class SettingsModel(BaseModel):
    provider: str = "janus"
    hf_token: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None



@app.post("/api/parse", response_model=ParseResult)
async def api_parse(req: ParseRequest):
    """Validates and parses deck file content."""
    res = parse_deck_text(req.text)
    if res.valid:
        state.raw_deck_text = req.text
        state.cards = res.cards
        state.global_prompt = res.global_prompt
    return res


@app.post("/api/parse-file", response_model=ParseResult)
async def api_parse_file(file: UploadFile = File(...)):
    """Upload and validate deck file."""
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    res = parse_deck_text(text)
    if res.valid:
        state.raw_deck_text = text
        state.cards = res.cards
        state.global_prompt = res.global_prompt
    return res


@app.get("/api/cards")
async def get_cards():
    """Returns the current deck card items."""
    return {
        "cards": [c.model_dump() for c in state.cards],
        "total_copies": sum(c.copies for c in state.cards),
        "is_generating": state.is_generating,
        "provider": state.provider,
        "global_prompt": state.global_prompt,
    }


async def process_single_card(card: CardItem):
    """Pipeline for a single card: Scryfall -> Generative Art -> Compositor -> 800 DPI PNG."""
    try:
        # 1. Fetch card data and high-res frame from Scryfall
        card.status = "fetching"
        card.status_message = "Retrieving high-resolution card frame from Scryfall..."
        state.broadcast_card_update(card)
        state.broadcast_log(f"Fetching Scryfall frame for {card.card_name} ({card.set_code} #{card.collector_number})...")

        card_data = await scryfall_client.get_card(card.set_code, card.collector_number, card.card_name)
        card.scryfall_id = card_data.id
        card.scryfall_png_url = card_data.png_url
        card.scryfall_art_url = card_data.art_crop_url

        # Load card frame and art crop into Pillow
        card_frame_img = Image.open(card_data.cached_png_path).convert("RGB")
        art_crop_img = Image.open(card_data.cached_art_path).convert("RGB") if card_data.cached_art_path else None

        # 2. Detect exact card boxes (art box, rules text box, statistic box, headers)
        card_boxes = detect_card_boxes(
            card_img=card_frame_img,
            art_crop_img=art_crop_img,
            type_line=card_data.type_line,
            flavor_name=card_data.flavor_name,
            border_color=card_data.border_color,
            frame_effects=card_data.frame_effects,
            layout=card_data.layout,
            full_art=card_data.full_art,
            security_stamp=card_data.security_stamp,
            rarity=card_data.rarity,
        )
        card.art_box = card_boxes.get("art_box")
        card.rules_box = card_boxes.get("rules_box")
        card.stat_box = card_boxes.get("stat_box")
        card.title_box = card_boxes.get("title_box")
        card.type_box = card_boxes.get("type_box")

        cw, ch = card_frame_img.size
        art_box = card_boxes.get("art_box") or (0, 0, cw, ch // 2)
        scale_ox = int((cw - cw * MPC_BLEED_SCALE) // 2)
        scale_oy = int((ch - ch * MPC_BLEED_SCALE) // 2)
        art_cx = int(((art_box[0] + art_box[2]) // 2) * MPC_BLEED_SCALE + scale_ox)
        art_cy = int(((art_box[1] + art_box[3]) // 2) * MPC_BLEED_SCALE + scale_oy)

        # 3. Generate custom full-art background centered on the main art frame
        effective_prompt = (
            f"{state.global_prompt} {card.prompt}".strip()
            if state.global_prompt
            else card.prompt
        )
        card.status = "generating"
        card.status_message = f"Generating full-art card background ({state.provider}): '{(effective_prompt or card.prompt)[:40]}...'"
        state.broadcast_card_update(card)
        state.broadcast_log(f"Generating full-art background for {card.card_name} with prompt: '{effective_prompt}'")

        p = state.provider.lower().strip()
        if p in ["grok", "xai", "grok-2", "grok-imagine", "grok-imagine-image", "grok-imagine-image-2.0", "x-ai"]:
            generator = get_generator(state.provider, xai_api_key=state.xai_api_key)
        elif p.startswith("janus") or p in ["deepseek", "deepseek-ai"]:
            generator = get_generator(state.provider, hf_token=state.hf_token)
        elif p in ["gemini", "imagen", "google"]:
            generator = get_generator(state.provider, api_key=state.gemini_api_key)
        elif p in ["openai", "dalle", "dall-e"]:
            generator = get_generator(state.provider, api_key=state.openai_api_key)
        else:
            generator = get_generator(state.provider)
        t_lower = (card_data.type_line or "").lower()
        l_lower = (card_data.layout or "").lower()
        is_battle = any(k in t_lower for k in ["battle", "siege"]) or (l_lower == "battle")
        is_room = ("room" in t_lower) or (l_lower == "room") or (l_lower == "split" and "room" in t_lower)
        is_saga = ("saga" in t_lower) or (l_lower == "saga")
        is_class_or_case = any(k in t_lower for k in ["class", "case"]) or (l_lower in ["class", "case"])

        if is_battle or is_room:
            # Landscape layout: generate large square canvas, rotate 90° CCW (left), center-crop to (cw, ch)
            gen_w = max(cw, ch)
            gen_h = max(cw, ch)
            focal_pt = (gen_w // 2, gen_h // 2)
        elif is_saga:
            gen_w = cw
            gen_h = ch
            focal_pt = (int(cw * 0.72), ch // 2)
        elif is_class_or_case:
            gen_w = cw
            gen_h = ch
            focal_pt = (int(cw * 0.28), ch // 2)
        else:
            gen_w = cw
            gen_h = ch
            focal_pt = (art_cx, art_cy)

        generated_art = await generator.generate_art(
            prompt=effective_prompt,
            card_name=card.card_name,
            target_width=gen_w,
            target_height=gen_h,
            colors=card_data.colors,
            flavor_name=card_data.flavor_name,
            focal_center=focal_pt,
        )

        if is_battle or is_room:
            # Rotate 90° CCW (left) and center crop to (cw, ch)
            art_rot = generated_art.rotate(90, expand=True)
            crop_left = max(0, (art_rot.width - cw) // 2)
            crop_top = max(0, (art_rot.height - ch) // 2)
            generated_art = art_rot.crop((crop_left, crop_top, crop_left + cw, crop_top + ch))

        # 4. Composite full-art background with masked card text boxes and upscale to 800 DPI MPC dimensions
        card.status = "compositing"
        card.status_message = "Compositing full-art card frame with text box masking and upscaling to 800 DPI..."
        state.broadcast_card_update(card)
        state.broadcast_log(f"Compositing 800 DPI full-art print image for {card.card_name}...")

        final_composite = composite_card(
            card_frame_img=card_frame_img,
            generated_art_img=generated_art,
            card_boxes=card_boxes,
            card_scale=MPC_BLEED_SCALE,
            target_dpi=800,
        )

        # 5. Save outputs
        png_path, thumb_path = save_card_outputs(card.id, final_composite, target_dpi=800)
        state.card_image_paths[card.id] = png_path
        state.card_thumb_paths[card.id] = thumb_path

        card.status = "ready"
        card.status_message = "800 DPI card image ready for MPC."
        card.image_url = f"/api/cards/{card.id}/image"
        state.broadcast_card_update(card)
        state.broadcast_log(f"✅ Card {card.card_name} completed successfully at 800 DPI.")

    except Exception as e:
        card.status = "error"
        card.status_message = f"Error: {str(e)}"
        state.broadcast_card_update(card)
        state.broadcast_log(f"❌ Failed to process {card.card_name}: {str(e)}", level="error")


def get_provider_concurrency(provider: Optional[str] = None) -> int:
    """
    Determines maximum parallel card generation workers based on provider.
    API-based generators (Gemini, OpenAI, Grok) and local Mock procedural generators
    can run concurrently (default: 4 parallel workers).
    Browser-based Perchance and Hugging Face ZeroGPU queues run single-file (concurrency: 1).
    """
    if not provider:
        return 4
    p = provider.lower().strip()
    if p in ["perchance", "perchance-ai", "janus", "janus-pro", "janus-pro-7b", "deepseek", "deepseek-ai", "deepseek-ai/janus-pro-7b"]:
        return 1
    return 4


@app.post("/api/generate")
async def api_generate_deck():
    """Triggers generation for all cards in the parsed deck list."""
    if not state.cards:
        raise HTTPException(status_code=400, detail="No parsed cards available. Please submit a valid deck first.")

    if state.is_generating:
        return {"status": "already_running", "message": "Generation is already in progress."}

    async def run_batch():
        state.is_generating = True
        concurrency = get_provider_concurrency(state.provider)
        state.broadcast_log(f"Starting batch deck generation ({len(state.cards)} cards, concurrency: {concurrency}, provider: {state.provider})...")
        
        sem = asyncio.Semaphore(concurrency)

        async def worker(card_item: CardItem):
            async with sem:
                await process_single_card(card_item)

        await asyncio.gather(*(worker(c) for c in state.cards))
        state.is_generating = False
        state.broadcast_log("🎉 All deck cards generated and ready for MakePlayingCards!")

    asyncio.create_task(run_batch())
    return {"status": "started", "total_cards": len(state.cards), "concurrency": get_provider_concurrency(state.provider)}


@app.post("/api/cards/{card_id}/regenerate")
async def api_regenerate_card(card_id: str, req: RegenerateRequest):
    """Regenerates art and 800 DPI card for a single card with an updated prompt."""
    target_card = next((c for c in state.cards if c.id == card_id), None)
    if not target_card:
        raise HTTPException(status_code=404, detail="Card not found.")

    target_card.prompt = req.prompt.strip()
    target_card.status = "queued"
    target_card.status_message = "Queued for prompt regeneration..."
    state.broadcast_card_update(target_card)

    async def run_single():
        await process_single_card(target_card)

    asyncio.create_task(run_single())
    return {"status": "queued", "card": target_card.model_dump()}


@app.get("/api/cards/{card_id}/image")
async def get_card_image(card_id: str):
    """Serves the print-ready 800 DPI PNG file."""
    path = state.card_image_paths.get(card_id) or f"output/cards/{card_id}.png"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Image not found or not generated yet.")
    return FileResponse(path, media_type="image/png", filename=f"{card_id}.png")


@app.get("/api/cards/{card_id}/thumb")
async def get_card_thumbnail(card_id: str):
    """Serves fast web thumbnail."""
    path = state.card_thumb_paths.get(card_id) or f"output/thumbnails/{card_id}.jpg"
    if not os.path.exists(path):
        # Fallback to full image if thumbnail not generated
        full_path = state.card_image_paths.get(card_id) or f"output/cards/{card_id}.png"
        if os.path.exists(full_path):
            return FileResponse(full_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/export/xml")
async def get_mpc_xml():
    """Exports cards.xml formatted for mpc-autofill."""
    if not state.cards:
        raise HTTPException(status_code=400, detail="No cards available.")
    xml_content = generate_mpc_xml(state.cards, state.card_image_paths)
    return Response(content=xml_content, media_type="application/xml", headers={"Content-Disposition": 'attachment; filename="cards.xml"'})


@app.get("/api/export/zip")
async def get_mpc_zip():
    """Exports full print zip bundle (cards.xml + 800 DPI PNGs)."""
    if not state.cards:
        raise HTTPException(status_code=400, detail="No cards available.")
    zip_bytes = create_mpc_zip_bundle(state.cards, state.card_image_paths)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="MPC_GenerativeArt_Deck.zip"'},
    )


@app.get("/api/mpc/injector.js")
async def get_mpc_injector_script():
    """Serves the in-browser MakePlayingCards session injector script."""
    injector_path = Path("frontend/js/mpc_injector.js")
    if not injector_path.exists():
        raise HTTPException(status_code=404, detail="Injector script not found.")
    content = injector_path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.post("/api/mpc/upload-stream")
async def stream_mpc_upload():
    """Runs automated browser upload to MakePlayingCards order and streams live log messages via SSE."""
    async def event_generator():
        async for log_line in mpc_uploader.upload_deck(state.cards, state.card_image_paths):
            yield f"data: {json.dumps({'message': log_line})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events stream for real-time card generation updates and logs."""
    queue = asyncio.Queue()
    state.progress_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield f": keep-alive\n\n"
        finally:
            if queue in state.progress_subscribers:
                state.progress_subscribers.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/settings")
async def get_settings():
    """Get current configuration and defaults populated from .env."""
    return {
        "provider": state.provider,
        "hf_token": state.hf_token,
        "gemini_api_key": state.gemini_api_key,
        "openai_api_key": state.openai_api_key,
        "xai_api_key": state.xai_api_key,
        "has_hf_token": bool(state.hf_token),
        "has_gemini_key": bool(state.gemini_api_key),
        "has_openai_key": bool(state.openai_api_key),
        "has_xai_key": bool(state.xai_api_key),
    }


@app.post("/api/settings")
async def update_settings(settings: SettingsModel):
    """Update generative art settings and API keys and persist them in .env (if enabled)."""
    state.provider = settings.provider
    os.environ["GENERATOR_PROVIDER"] = settings.provider

    target_env = get_env_file()
    if target_env is not None:
        # Ensure target .env file exists
        if not target_env.exists():
            try:
                target_env.parent.mkdir(parents=True, exist_ok=True)
                target_env.touch()
            except Exception:
                pass

        try:
            set_key(str(target_env), "GENERATOR_PROVIDER", settings.provider)
        except Exception as e:
            print(f"[Settings] Warning: Failed to persist GENERATOR_PROVIDER to {target_env}: {e}")

        if settings.hf_token is not None:
            state.hf_token = settings.hf_token.strip()
            os.environ["HF_TOKEN"] = state.hf_token
            if state.hf_token:
                try:
                    set_key(str(target_env), "HF_TOKEN", state.hf_token)
                except Exception:
                    pass

        if settings.gemini_api_key is not None:
            state.gemini_api_key = settings.gemini_api_key.strip()
            os.environ["GEMINI_API_KEY"] = state.gemini_api_key
            if state.gemini_api_key:
                try:
                    set_key(str(target_env), "GEMINI_API_KEY", state.gemini_api_key)
                except Exception:
                    pass

        if settings.openai_api_key is not None:
            state.openai_api_key = settings.openai_api_key.strip()
            os.environ["OPENAI_API_KEY"] = state.openai_api_key
            if state.openai_api_key:
                try:
                    set_key(str(target_env), "OPENAI_API_KEY", state.openai_api_key)
                except Exception:
                    pass

        if settings.xai_api_key is not None:
            state.xai_api_key = settings.xai_api_key.strip()
            os.environ["XAI_API_KEY"] = state.xai_api_key
            if state.xai_api_key:
                try:
                    set_key(str(target_env), "XAI_API_KEY", state.xai_api_key)
                except Exception:
                    pass
    else:
        if settings.hf_token is not None:
            state.hf_token = settings.hf_token.strip()
            os.environ["HF_TOKEN"] = state.hf_token

        if settings.gemini_api_key is not None:
            state.gemini_api_key = settings.gemini_api_key.strip()
            os.environ["GEMINI_API_KEY"] = state.gemini_api_key

        if settings.openai_api_key is not None:
            state.openai_api_key = settings.openai_api_key.strip()
            os.environ["OPENAI_API_KEY"] = state.openai_api_key

        if settings.xai_api_key is not None:
            state.xai_api_key = settings.xai_api_key.strip()
            os.environ["XAI_API_KEY"] = state.xai_api_key

    return {
        "status": "updated",
        "provider": state.provider,
        "has_hf_token": bool(state.hf_token),
        "has_gemini_key": bool(state.gemini_api_key),
        "has_openai_key": bool(state.openai_api_key),
        "has_xai_key": bool(state.xai_api_key),
    }



# Mount static frontend
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    """Serves the favicon.ico asset."""
    favicon_path = Path("frontend/favicon.ico")
    if favicon_path.exists():
        return FileResponse(str(favicon_path), media_type="image/x-icon")
    return Response(status_code=404)


@app.get("/")
async def serve_index():
    """Serves the main frontend Single Page Application with cache-control headers."""
    index_path = Path("frontend/index.html")
    if index_path.exists():
        return FileResponse(
            str(index_path),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>MPCWithGenerativeArt Frontend is being prepared...</h1>")
