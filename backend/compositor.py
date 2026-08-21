"""Card image compositor, card box detector, exclusion masking, and 800 DPI MPC exporter."""

import os
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, Union
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


def detect_card_boxes(
    card_img: Image.Image,
    art_crop_img: Optional[Image.Image] = None,
    type_line: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detects the exact borders of the card rules and statistic text boxes,
    along with art box, title header, type line, and polygonal badges (e.g. loyalty shields).
    Returns a dict containing detected bounding boxes and polygonal shapes.
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    # 1. Art Box Detection
    art_box = detect_art_box(card_img, art_crop_img)

    # 2. Title Box and Type Line Box (precise pill bounds)
    title_box = (int(44 * sx), int(38 * sy), int(701 * sx), int(88 * sy))
    type_box = (int(44 * sx), int(584 * sy), int(701 * sx), int(638 * sy))

    # 3. Rules Text Box and Statistic Elements
    t_lower = (type_line or "").lower()
    stat_box = None
    stat_polygon = None

    if "walker" in t_lower:
        # Planeswalker / Universewalker layout
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(948 * sy))
        # Irregular polygonal loyalty shield badge (notched top, vertical sides, chevron pointed tip)
        stat_polygon = [
            (int(604 * sx), int(928 * sy)),
            (int(654 * sx), int(934 * sy)),
            (int(704 * sx), int(928 * sy)),
            (int(709 * sx), int(946 * sy)),
            (int(709 * sx), int(968 * sy)),
            (int(654 * sx), int(990 * sy)),
            (int(599 * sx), int(968 * sy)),
            (int(599 * sx), int(946 * sy)),
        ]
        stat_box = (int(599 * sx), int(928 * sy), int(709 * sx), int(990 * sy))
    elif any(k in t_lower for k in ["creature", "vehicle"]):
        # Creature / Vehicle layout with Power & Toughness box
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(930 * sy))
        stat_box = (int(560 * sx), int(884 * sy), int(700 * sx), int(960 * sy))
    elif any(k in t_lower for k in ["battle", "siege"]):
        # Battle layout with Defense box
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(930 * sy))
        stat_box = (int(565 * sx), int(884 * sy), int(700 * sx), int(960 * sy))
    else:
        # Standard non-creature layout (Enchantment, Instant, Sorcery, Artifact, Land)
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))

    return {
        "art_box": art_box,
        "rules_box": rules_box,
        "stat_box": stat_box,
        "stat_polygon": stat_polygon,
        "title_box": title_box,
        "type_box": type_box,
    }


def create_card_exclusion_mask(
    card_img: Image.Image,
    card_boxes: Dict[str, Any],
    feather_radius: float = 0.5,
) -> Image.Image:
    """
    Constructs an alpha mask that excludes (preserves) the card rules text box,
    statistic text box/polygons (such as Planeswalker loyalty shields), title bar, and type line
    with smooth beveled corners, while opening the art frame and card backgrounds to reveal
    the full-art generative background.
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0
    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)

    # 1. Preserve Title Header (Card name & mana cost)
    tb = card_boxes.get("title_box") or (int(44 * sx), int(38 * sy), int(701 * sx), int(88 * sy))
    draw.rounded_rectangle([tb[0], tb[1], tb[2], tb[3]], radius=max(4, int(14 * sx)), fill=255)

    # 2. Preserve Type Line
    typ = card_boxes.get("type_box") or (int(44 * sx), int(584 * sy), int(701 * sx), int(638 * sy))
    draw.rounded_rectangle([typ[0], typ[1], typ[2], typ[3]], radius=max(4, int(14 * sx)), fill=255)

    # 3. Preserve Rules Text Box
    rb = card_boxes.get("rules_box") or (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))
    draw.rounded_rectangle([rb[0], rb[1], rb[2], rb[3]], radius=max(6, int(14 * sx)), fill=255)

    # 4. Preserve Statistic Text Box / Polygonal Shield if present
    stat_poly = card_boxes.get("stat_polygon")
    if stat_poly:
        draw.polygon(stat_poly, fill=255)
    else:
        sb = card_boxes.get("stat_box")
        if sb:
            draw.rounded_rectangle([sb[0], sb[1], sb[2], sb[3]], radius=max(4, int(12 * sx)), fill=255)

    # Apply slight feathering for clean seamless integration
    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_radius))

    return mask


def composite_full_art_card(
    card_frame_img: Image.Image,
    generated_art_img: Image.Image,
    card_boxes: Dict[str, Any],
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Composites a full-art background image with masked card rules and statistic text boxes,
    upscales to 800 DPI print dimensions, and embeds print resolution.
    The generative art is fitted preserving aspect ratio, centered on the main art frame.
    """
    card_rgba = card_frame_img.convert("RGBA")
    cw, ch = card_rgba.size

    # Fit full-art generated image preserving aspect ratio centered on the art frame
    art_full = ImageOps.fit(
        generated_art_img.convert("RGBA"),
        (cw, ch),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.33),
    )

    # Generate exclusion mask for preserved card elements
    mask = create_card_exclusion_mask(card_rgba, card_boxes, feather_radius=0.5)

    # Start with full art background and overlay preserved card elements
    composite = art_full.copy()
    composite.paste(card_rgba, (0, 0), mask)

    # Upscale composite card to 800 DPI target MPC dimensions
    scale_factor = min(target_width / cw, target_height / ch)
    scaled_w = int(cw * scale_factor)
    scaled_h = int(ch * scale_factor)

    scaled_card = composite.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

    # Create full canvas with MPC bleed border
    final_canvas = Image.new("RGB", (target_width, target_height), (12, 12, 12))

    # Center scaled card on bleed canvas
    offset_x = (target_width - scaled_w) // 2
    offset_y = (target_height - scaled_h) // 2
    final_canvas.paste(scaled_card.convert("RGB"), (offset_x, offset_y))

    return final_canvas


def composite_card(
    card_frame_img: Image.Image,
    generated_art_img: Image.Image,
    art_box: Optional[Union[Tuple[int, int, int, int], Dict[str, Any]]] = None,
    card_boxes: Optional[Dict[str, Any]] = None,
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Unified card compositor that performs full-art background placement
    with card rules and statistic text box exclusion masking.
    """
    # If card_boxes is provided or passed via art_box dict
    if isinstance(art_box, dict):
        boxes = art_box
    elif card_boxes is not None:
        boxes = card_boxes
    else:
        # Auto-detect boxes if not explicitly provided
        boxes = detect_card_boxes(card_frame_img)
        if isinstance(art_box, tuple) and len(art_box) == 4:
            boxes["art_box"] = art_box

    return composite_full_art_card(
        card_frame_img=card_frame_img,
        generated_art_img=generated_art_img,
        card_boxes=boxes,
        target_dpi=target_dpi,
        target_width=target_width,
        target_height=target_height,
    )


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
