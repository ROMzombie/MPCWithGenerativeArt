"""Scryfall API client and card asset manager."""

import os
import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import httpx
from PIL import Image
import io

CACHE_DIR = Path("cache/scryfall")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SCRYFALL_API_BASE = "https://api.scryfall.com"
HEADERS = {
    "User-Agent": "MPCWithGenerativeArt/1.0 (contact@makeplayingcards.custom)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


class ScryfallCardData:
    def __init__(
        self,
        id: str,
        name: str,
        set_code: str,
        collector_number: str,
        png_url: Optional[str],
        art_crop_url: Optional[str],
        flavor_name: Optional[str] = None,
        colors: Optional[list] = None,
        mana_cost: Optional[str] = None,
        type_line: Optional[str] = None,
        layout: Optional[str] = "normal",
        border_color: Optional[str] = "black",
        frame_effects: Optional[list] = None,
        full_art: Optional[bool] = False,
        promo_types: Optional[list] = None,
        security_stamp: Optional[str] = None,
        rarity: Optional[str] = None,
        cached_png_path: Optional[str] = None,
        cached_art_path: Optional[str] = None,
    ):
        self.id = id
        self.name = name
        self.set_code = set_code.lower()
        self.collector_number = collector_number.lower()
        self.png_url = png_url
        self.art_crop_url = art_crop_url
        self.flavor_name = flavor_name
        self.colors = colors or []
        self.mana_cost = mana_cost or ""
        self.type_line = type_line or ""
        self.layout = layout
        self.border_color = border_color or "black"
        self.frame_effects = frame_effects or []
        self.full_art = bool(full_art)
        self.promo_types = promo_types or []
        self.security_stamp = security_stamp
        self.rarity = rarity or "common"
        self.cached_png_path = cached_png_path
        self.cached_art_path = cached_art_path


class ScryfallClient:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0

    async def _rate_limit(self):
        """Ensure polite Scryfall API interval (at least 100ms between calls)."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            elapsed = now - self._last_request_time
            if elapsed < 0.1:
                await asyncio.sleep(0.1 - elapsed)
            self._last_request_time = loop.time()

    async def get_card(self, set_code: str, collector_number: str, card_name: Optional[str] = None) -> ScryfallCardData:
        """
        Retrieves card data and downloads high-res card PNG and art crop.
        First tries /cards/{set}/{number}, falls back to name search if needed.
        """
        set_clean = set_code.strip().lower()
        num_clean = collector_number.strip().lower()

        # Check local cache first
        png_cache_path = CACHE_DIR / f"{set_clean}_{num_clean}.png"
        art_cache_path = CACHE_DIR / f"{set_clean}_{num_clean}_art.jpg"

        await self._rate_limit()

        async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
            card_json = None
            url = f"{SCRYFALL_API_BASE}/cards/{set_clean}/{num_clean}"
            
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    card_json = resp.json()
            except Exception as e:
                print(f"[Scryfall] Direct lookup failed for {set_clean}/{num_clean}: {e}")

            # Fallback to search by card name if direct set/number not found
            if not card_json and card_name:
                print(f"[Scryfall] Attempting fallback search for '{card_name}' (set: {set_clean})")
                await self._rate_limit()
                search_url = f"{SCRYFALL_API_BASE}/cards/named?fuzzy={httpx.URL(card_name)}"
                try:
                    resp = await client.get(search_url)
                    if resp.status_code == 200:
                        card_json = resp.json()
                except Exception as e:
                    print(f"[Scryfall] Fallback search error: {e}")

            if not card_json:
                raise ValueError(f"Could not find card '{card_name or ''}' ({set_code}) #{collector_number} on Scryfall")

            # Extract image URLs (handle single face or multi-face cards)
            png_url = None
            art_crop_url = None

            if "image_uris" in card_json:
                uris = card_json["image_uris"]
                png_url = uris.get("png") or uris.get("large")
                art_crop_url = uris.get("art_crop")
            elif "card_faces" in card_json and len(card_json["card_faces"]) > 0:
                face = card_json["card_faces"][0]
                if "image_uris" in face:
                    uris = face["image_uris"]
                    png_url = uris.get("png") or uris.get("large")
                    art_crop_url = uris.get("art_crop")

            if not png_url:
                raise ValueError(f"Card {card_json.get('name')} does not contain high-resolution image URIs on Scryfall")

            # Download and cache full PNG
            if not png_cache_path.exists():
                print(f"[Scryfall] Downloading card PNG from {png_url}...")
                png_resp = await client.get(png_url)
                if png_resp.status_code == 200:
                    png_cache_path.write_bytes(png_resp.content)
                else:
                    raise IOError(f"Failed to download card PNG: HTTP {png_resp.status_code}")

            # Download and cache art crop
            if art_crop_url and not art_cache_path.exists():
                print(f"[Scryfall] Downloading art crop from {art_crop_url}...")
                art_resp = await client.get(art_crop_url)
                if art_resp.status_code == 200:
                    art_cache_path.write_bytes(art_resp.content)

            return ScryfallCardData(
                id=card_json.get("id", ""),
                name=card_json.get("name", card_name or ""),
                set_code=card_json.get("set", set_clean),
                collector_number=card_json.get("collector_number", num_clean),
                png_url=png_url,
                art_crop_url=art_crop_url,
                flavor_name=card_json.get("flavor_name"),
                colors=card_json.get("colors", []),
                mana_cost=card_json.get("mana_cost", ""),
                type_line=card_json.get("type_line", ""),
                layout=card_json.get("layout", "normal"),
                border_color=card_json.get("border_color", "black"),
                frame_effects=card_json.get("frame_effects", []),
                full_art=card_json.get("full_art", False),
                promo_types=card_json.get("promo_types", []),
                security_stamp=card_json.get("security_stamp"),
                rarity=card_json.get("rarity", "common"),
                cached_png_path=str(png_cache_path),
                cached_art_path=str(art_cache_path) if art_cache_path.exists() else None,
            )


# Global singleton client
scryfall_client = ScryfallClient()
