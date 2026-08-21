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
ENV_FILE = Path(".env")
load_dotenv(dotenv_path=ENV_FILE)

from backend.parser import parse_deck_text, CardItem, ParseResult
from backend.scryfall import scryfall_client
from backend.generator import get_generator, MockProceduralGenerator
from backend.compositor import detect_card_boxes, detect_art_box, composite_card, composite_full_art_card, save_card_outputs
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
    return res


@app.get("/api/cards")
async def get_cards():
    """Returns the current deck card items."""
    return {
        "cards": [c.model_dump() for c in state.cards],
        "total_copies": sum(c.copies for c in state.cards),
        "is_generating": state.is_generating,
        "provider": state.provider,
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
        card_boxes = detect_card_boxes(card_frame_img, art_crop_img, type_line=card_data.type_line)
        card.art_box = card_boxes.get("art_box")
        card.rules_box = card_boxes.get("rules_box")
        card.stat_box = card_boxes.get("stat_box")
        card.title_box = card_boxes.get("title_box")
        card.type_box = card_boxes.get("type_box")

        cw, ch = card_frame_img.size
        art_box = card_boxes.get("art_box") or (0, 0, cw, ch // 2)
        art_cx = (art_box[0] + art_box[2]) // 2
        art_cy = (art_box[1] + art_box[3]) // 2

        # 3. Generate custom full-art background centered on the main art frame
        card.status = "generating"
        card.status_message = f"Generating full-art card background ({state.provider}): '{card.prompt[:40]}...'"
        state.broadcast_card_update(card)
        state.broadcast_log(f"Generating full-art background for {card.card_name} with prompt: '{card.prompt}'")

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

        generated_art = await generator.generate_art(
            prompt=card.prompt,
            card_name=card.card_name,
            target_width=cw,
            target_height=ch,
            colors=card_data.colors,
            flavor_name=card_data.flavor_name,
            focal_center=(art_cx, art_cy),
        )

        # 4. Composite full-art background with masked card text boxes and upscale to 800 DPI MPC dimensions
        card.status = "compositing"
        card.status_message = "Compositing full-art card frame with text box masking and upscaling to 800 DPI..."
        state.broadcast_card_update(card)
        state.broadcast_log(f"Compositing 800 DPI full-art print image for {card.card_name}...")

        final_composite = composite_card(
            card_frame_img=card_frame_img,
            generated_art_img=generated_art,
            card_boxes=card_boxes,
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


@app.post("/api/generate")
async def api_generate_deck():
    """Triggers generation for all cards in the parsed deck list."""
    if not state.cards:
        raise HTTPException(status_code=400, detail="No parsed cards available. Please submit a valid deck first.")

    if state.is_generating:
        return {"status": "already_running", "message": "Generation is already in progress."}

    async def run_batch():
        state.is_generating = True
        state.broadcast_log("Starting batch deck generation...")
        for card in state.cards:
            await process_single_card(card)
        state.is_generating = False
        state.broadcast_log("🎉 All deck cards generated and ready for MakePlayingCards!")

    asyncio.create_task(run_batch())
    return {"status": "started", "total_cards": len(state.cards)}


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
    """Update generative art settings and API keys and persist them in .env."""
    state.provider = settings.provider
    os.environ["GENERATOR_PROVIDER"] = settings.provider

    # Ensure .env file exists
    if not ENV_FILE.exists():
        ENV_FILE.touch()

    try:
        set_key(str(ENV_FILE), "GENERATOR_PROVIDER", settings.provider)
    except Exception as e:
        print(f"[Settings] Warning: Failed to persist GENERATOR_PROVIDER to .env: {e}")

    if settings.hf_token is not None:
        state.hf_token = settings.hf_token.strip()
        os.environ["HF_TOKEN"] = state.hf_token
        if state.hf_token:
            try:
                set_key(str(ENV_FILE), "HF_TOKEN", state.hf_token)
            except Exception:
                pass

    if settings.gemini_api_key is not None:
        state.gemini_api_key = settings.gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = state.gemini_api_key
        if state.gemini_api_key:
            try:
                set_key(str(ENV_FILE), "GEMINI_API_KEY", state.gemini_api_key)
            except Exception:
                pass

    if settings.openai_api_key is not None:
        state.openai_api_key = settings.openai_api_key.strip()
        os.environ["OPENAI_API_KEY"] = state.openai_api_key
        if state.openai_api_key:
            try:
                set_key(str(ENV_FILE), "OPENAI_API_KEY", state.openai_api_key)
            except Exception:
                pass

    if settings.xai_api_key is not None:
        state.xai_api_key = settings.xai_api_key.strip()
        os.environ["XAI_API_KEY"] = state.xai_api_key
        if state.xai_api_key:
            try:
                set_key(str(ENV_FILE), "XAI_API_KEY", state.xai_api_key)
            except Exception:
                pass

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


@app.get("/")
async def serve_index():
    """Serves the main frontend Single Page Application."""
    index_path = Path("frontend/index.html")
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>MPCWithGenerativeArt Frontend is being prepared...</h1>")
