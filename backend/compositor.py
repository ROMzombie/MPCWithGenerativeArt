"""Card image compositor, art box detector, and 800 DPI MPC exporter."""

import os
from pathlib import Path
from typing import Tuple, Optional
from PIL import Image, ImageDraw, ImageFilter, ImageOps

OUTPUT_DIR = Path("output/cards")
THUMB_DIR = Path("output/thumbnails")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# MakePlayingCards standard poker card dimensions at 800 DPI with 1/8" (0.125") bleed:
# Physical dimensions: 2.73 in x 3.71 in (69.3 mm x 94.2 mm)
MPC_800DPI_WIDTH = 2184
MPC_800DPI_HEIGHT = 2968


def detect_art_box(card_img: Image.Image, art_crop_img: Optional[Image.Image] = None) -> Tuple[int, int, int, int]:
    """
    Finds the (x1, y1, x2, y2) bounding box of the card's art box within the card image.
    Uses multi-scale sliding window template match if art_crop is provided,
    otherwise falls back to MTG frame standard proportions.
    """
    cw, ch = card_img.size

    # Standard MTG proportions on normal card
    default_box = (
        int(cw * 0.0805),  # ~60 on 745
        int(ch * 0.1154),  # ~120 on 1040
        int(cw * 0.9208),  # ~686 on 745
        int(ch * 0.5548),  # ~577 on 1040
    )

    if not art_crop_img:
        return default_box

    aw, ah = art_crop_img.size

    # If art_crop has similar aspect ratio to card, use template search
    scale = 4
    sw, sh = max(1, cw // scale), max(1, ch // scale)
    pw, ph = max(1, aw // scale), max(1, ah // scale)

    if pw >= sw or ph >= sh:
        return default_box

    c_small = card_img.resize((sw, sh), Image.Resampling.BOX).convert("L")
    a_small = art_crop_img.resize((pw, ph), Image.Resampling.BOX).convert("L")

    c_bytes = c_small.tobytes()
    a_bytes = a_small.tobytes()

    min_diff = float("inf")
    best_x, best_y = 0, 0

    # Search in top 70% of card (where art sits)
    max_search_y = min(sh - ph, int(sh * 0.65))
    step = 2

    for y in range(0, max_search_y + 1, step):
        for x in range(0, sw - pw + 1, step):
            diff = 0
            sample_count = 0
            # Sample subset of pixels for high speed
            for py in range(0, ph, 4):
                c_row_offset = (y + py) * sw + x
                a_row_offset = py * pw
                for px in range(0, pw, 4):
                    diff += abs(c_bytes[c_row_offset + px] - a_bytes[a_row_offset + px])
                    sample_count += 1

            avg_diff = diff / max(1, sample_count)
            if avg_diff < min_diff:
                min_diff = avg_diff
                best_x = x * scale
                best_y = y * scale

    # If match score is solid (avg diff < 25), return detected bounding box
    if min_diff < 25:
        return (best_x, best_y, min(cw, best_x + aw), min(ch, best_y + ah))

    return default_box


def composite_card(
    card_frame_img: Image.Image,
    generated_art_img: Image.Image,
    art_box: Tuple[int, int, int, int],
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Composites generated art into the card frame art box,
    upscales the card to 800 DPI print dimensions, and embeds print resolution.
    """
    x1, y1, x2, y2 = art_box
    box_w = max(10, x2 - x1)
    box_h = max(10, y2 - y1)

    # 1. Resize generated art to fit the art box perfectly
    art_resized = generated_art_img.resize((box_w, box_h), Image.Resampling.LANCZOS).convert("RGBA")

    # 2. Convert base card image to RGBA
    card_composite = card_frame_img.convert("RGBA")

    # 3. Create a rounded-corner / feathered mask for smooth frame blending
    mask = Image.new("L", (box_w, box_h), 255)
    draw_mask = ImageDraw.Draw(mask)
    corner_radius = max(2, int(box_w * 0.015))
    # Beveled rounded rectangle for clean frame insertion
    draw_mask.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=corner_radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.5))

    # 4. Paste generated art into art box region
    card_composite.paste(art_resized, (x1, y1), mask)

    # 5. Upscale composite card to 800 DPI target MPC dimensions
    # If the aspect ratio slightly differs from MPC bleed poker card, add bleed border
    card_w, card_h = card_composite.size
    scale_factor = min(target_width / card_w, target_height / card_h)

    scaled_w = int(card_w * scale_factor)
    scaled_h = int(card_h * scale_factor)

    scaled_card = card_composite.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

    # Create full canvas with MPC bleed border (using black / dark card edge)
    final_canvas = Image.new("RGB", (target_width, target_height), (12, 12, 12))
    
    # Center scaled card on bleed canvas
    offset_x = (target_width - scaled_w) // 2
    offset_y = (target_height - scaled_h) // 2
    final_canvas.paste(scaled_card.convert("RGB"), (offset_x, offset_y))

    return final_canvas


def save_card_outputs(
    card_id: str,
    final_image: Image.Image,
    target_dpi: int = 800,
) -> Tuple[str, str]:
    """
    Saves the final 800 DPI PNG with embedded DPI metadata
    and creates a fast web preview thumbnail.
    Returns (png_path, thumb_path).
    """
    png_path = OUTPUT_DIR / f"{card_id}.png"
    thumb_path = THUMB_DIR / f"{card_id}.jpg"

    # Save 800 DPI PNG
    final_image.save(
        png_path,
        format="PNG",
        dpi=(target_dpi, target_dpi),
        optimize=True,
    )

    # Save web thumbnail (e.g. 500px width)
    thumb_w = 480
    thumb_h = int(final_image.height * (thumb_w / final_image.width))
    thumb_img = final_image.resize((thumb_w, thumb_h), Image.Resampling.BICUBIC).convert("RGB")
    thumb_img.save(thumb_path, format="JPEG", quality=88, optimize=True)

    return str(png_path), str(thumb_path)
