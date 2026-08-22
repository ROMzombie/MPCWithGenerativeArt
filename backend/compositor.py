"""Card image compositor, card box detector, exclusion masking, and 800 DPI MPC exporter."""

import os
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, Union, List
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops

OUTPUT_DIR = Path("output/cards")
THUMB_DIR = Path("output/thumbnails")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# MakePlayingCards standard poker card dimensions at 800 DPI with 1/8" (0.125") bleed:
# Physical dimensions: 2.73 in x 3.71 in (69.3 mm x 94.2 mm)
MPC_800DPI_WIDTH = 2184
MPC_800DPI_HEIGHT = 2968

# Default bleed scale factor for Scryfall card frame assets.
# Scaling by 0.90 provides ~5% bleed margin on all four sides, ensuring that
# the 1/8" MPC cut area and safe zone contain only full-bleed generative art,
# with all card frame elements (title bar, type line, rules box, badges) comfortably inside.
MPC_BLEED_SCALE = 0.90


def scale_card_frame_and_boxes(
    card_frame_img: Image.Image,
    card_boxes: Dict[str, Any],
    scale_factor: float = MPC_BLEED_SCALE,
    target_canvas_size: Optional[Tuple[int, int]] = None,
) -> Tuple[Image.Image, Dict[str, Any]]:
    """
    Scales the Scryfall card frame down by scale_factor and centers it on a transparent
    canvas of target_canvas_size (defaulting to the original card size).
    Transforms all bounding boxes and polygon coordinate arrays accordingly.
    """
    cw, ch = card_frame_img.size
    canvas_w, canvas_h = target_canvas_size if target_canvas_size else (cw, ch)

    if scale_factor >= 1.0:
        return card_frame_img.convert("RGBA"), card_boxes

    sw = int(cw * scale_factor)
    sh = int(ch * scale_factor)
    ox = (canvas_w - sw) // 2
    oy = (canvas_h - sh) // 2

    scaled_card = card_frame_img.resize((sw, sh), Image.Resampling.LANCZOS)
    padded_card = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    padded_card.paste(scaled_card.convert("RGBA"), (ox, oy))

    def scale_box(b: Optional[Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
        if not b:
            return None
        return (
            int(b[0] * scale_factor + ox),
            int(b[1] * scale_factor + oy),
            int(b[2] * scale_factor + ox),
            int(b[3] * scale_factor + oy),
        )

    def scale_poly(poly: Optional[List[Tuple[int, int]]]) -> Optional[List[Tuple[int, int]]]:
        if not poly:
            return None
        return [
            (int(x * scale_factor + ox), int(y * scale_factor + oy))
            for (x, y) in poly
        ]

    scaled_boxes = {
        "art_box": scale_box(card_boxes.get("art_box")),
        "rules_box": scale_box(card_boxes.get("rules_box")),
        "stat_box": scale_box(card_boxes.get("stat_box")),
        "stat_polygon": scale_poly(card_boxes.get("stat_polygon")),
        "title_box": scale_box(card_boxes.get("title_box")),
        "title_pill": scale_box(card_boxes.get("title_pill")),
        "subtitle_polygon": scale_poly(card_boxes.get("subtitle_polygon")),
        "type_box": scale_box(card_boxes.get("type_box")),
        "is_borderless": card_boxes.get("is_borderless", False),
        "scale_factor": scale_factor,
        "offset": (ox, oy),
    }

    return padded_card, scaled_boxes


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
    flavor_name: Optional[str] = None,
    border_color: Optional[str] = "black",
    frame_effects: Optional[List[str]] = None,
    layout: Optional[str] = "normal",
    full_art: Optional[bool] = False,
) -> Dict[str, Any]:
    """
    Detects individual borders of the card rules and statistic text boxes,
    along with art box, title header (and subtitle banner if present), and type line.
    Adapts dynamically to standard, planeswalker, borderless, showcase, and inverted card layouts.
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    # 1. Art Box Detection
    art_box = detect_art_box(card_img, art_crop_img)

    t_lower = (type_line or "").lower()
    is_planeswalker = "walker" in t_lower
    is_creature = any(k in t_lower for k in ["creature", "vehicle"])
    is_battle = any(k in t_lower for k in ["battle", "siege"])
    
    effects = [str(e).lower() for e in (frame_effects or [])]
    is_borderless = (
        (border_color == "borderless")
        or ("inverted" in effects)
        or ("showcase" in effects)
        or ("extendedart" in effects)
        or bool(full_art)
        or (layout == "art_series")
    )
    has_flavor_name = bool(flavor_name)

    # 2. Title Box Detection (exact pill + subtitle polygon if present)
    title_pill = (int(40 * sx), int(44 * sy), int(705 * sx), int(96 * sy))
    subtitle_polygon = None
    if has_flavor_name:
        subtitle_polygon = [
            (int(85 * sx), int(94 * sy)),
            (int(660 * sx), int(94 * sy)),
            (int(636 * sx), int(138 * sy)),
            (int(109 * sx), int(138 * sy)),
        ]
        title_box = (int(40 * sx), int(44 * sy), int(705 * sx), int(138 * sy))
    else:
        title_box = title_pill

    # 3. Type Line Box Detection
    type_box = (int(40 * sx), int(578 * sy), int(705 * sx), int(628 * sy))

    # 4. Statistic Box & Rules Text Box Detection
    stat_box = None
    stat_polygon = None

    if is_planeswalker:
        # Planeswalker / Universewalker layout
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))
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
    elif is_creature:
        # Creature / Vehicle layout with Power & Toughness box
        if is_borderless:
            rules_box = (int(46 * sx), int(626 * sy), int(699 * sx), int(934 * sy))
            stat_box = (int(574 * sx), int(918 * sy), int(705 * sx), int(984 * sy))
        else:
            rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(930 * sy))
            stat_box = (int(574 * sx), int(918 * sy), int(705 * sx), int(984 * sy))
    elif is_battle:
        # Battle layout with Defense box
        rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(930 * sy))
        stat_box = (int(574 * sx), int(918 * sy), int(705 * sx), int(984 * sy))
    else:
        # Standard non-creature layout (Enchantment, Instant, Sorcery, Artifact, Land)
        if is_borderless:
            rules_box = (int(46 * sx), int(626 * sy), int(699 * sx), int(942 * sy))
        else:
            rules_box = (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))

    return {
        "art_box": art_box,
        "rules_box": rules_box,
        "stat_box": stat_box,
        "stat_polygon": stat_polygon,
        "title_box": title_box,
        "title_pill": title_pill,
        "subtitle_polygon": subtitle_polygon,
        "type_box": type_box,
        "is_borderless": is_borderless,
    }


def create_card_exclusion_mask(
    card_img: Image.Image,
    card_boxes: Dict[str, Any],
    card_scale: float = 1.0,
    feather_radius: float = 0.3,
) -> Image.Image:
    """
    Constructs an alpha mask that excludes (preserves) the card rules text box,
    statistic text box/polygons (such as Planeswalker loyalty shields), title bar, and type line
    with smooth beveled corners. Supports optional card scaling.
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    if card_scale < 1.0:
        _, boxes = scale_card_frame_and_boxes(card_img, card_boxes, scale_factor=card_scale)
        s_eff = card_scale
    else:
        boxes = card_boxes
        s_eff = 1.0

    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)

    # 1. Preserve Title Header
    t_pill = boxes.get("title_pill") or (int(40 * sx), int(44 * sy), int(705 * sx), int(96 * sy))
    draw.rounded_rectangle(t_pill, radius=max(4, int(24 * sy * s_eff)), fill=255)
    sub_poly = boxes.get("subtitle_polygon")
    if sub_poly:
        draw.polygon(sub_poly, fill=255)

    # 2. Preserve Type Line
    typ = boxes.get("type_box") or (int(40 * sx), int(578 * sy), int(705 * sx), int(628 * sy))
    draw.rounded_rectangle([typ[0], typ[1], typ[2], typ[3]], radius=max(4, int(24 * sy * s_eff)), fill=255)

    # 3. Preserve Rules Text Box
    rb = boxes.get("rules_box") or (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))
    draw.rounded_rectangle([rb[0], rb[1], rb[2], rb[3]], radius=max(4, int(10 * sx * s_eff)), fill=255)

    # 4. Preserve Statistic Text Box / Polygonal Shield if present
    stat_poly = boxes.get("stat_polygon")
    if stat_poly:
        draw.polygon(stat_poly, fill=255)
    else:
        sb = boxes.get("stat_box")
        if sb:
            draw.rounded_rectangle([sb[0], sb[1], sb[2], sb[3]], radius=max(4, int(22 * sy * s_eff)), fill=255)

    # Apply slight feathering for clean seamless integration
    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_radius))

    return mask


def composite_full_art_card(
    card_frame_img: Image.Image,
    generated_art_img: Image.Image,
    card_boxes: Dict[str, Any],
    card_scale: float = MPC_BLEED_SCALE,
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Composites a full-art background image with individually masked card rules and statistic text boxes,
    scaling the Scryfall card frame down slightly to ensure the 1/8" MPC bleed margin contains purely
    generative art. Upscales seamlessly to 800 DPI target print dimensions.
    """
    cw, ch = card_frame_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    if card_scale < 1.0:
        card_rgba, boxes = scale_card_frame_and_boxes(card_frame_img, card_boxes, scale_factor=card_scale)
        s_eff = card_scale
    else:
        card_rgba = card_frame_img.convert("RGBA")
        boxes = card_boxes
        s_eff = 1.0

    # Fit full-art generated image across the entire canvas preserving aspect ratio
    art_full = ImageOps.fit(
        generated_art_img.convert("RGBA"),
        (cw, ch),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.33),
    )

    composite = art_full.copy()
    is_borderless = boxes.get("is_borderless", False)

    # 1. Composite Title Header (Pill + Subtitle Polygon if present)
    t_pill = boxes.get("title_pill") or (int(40 * sx), int(44 * sy), int(705 * sx), int(96 * sy))
    t_mask = Image.new("L", (cw, ch), 0)
    td = ImageDraw.Draw(t_mask)
    td.rounded_rectangle(t_pill, radius=max(4, int(24 * sy * s_eff)), fill=255)
    sub_poly = boxes.get("subtitle_polygon")
    if sub_poly:
        td.polygon(sub_poly, fill=255)
    t_mask = t_mask.filter(ImageFilter.GaussianBlur(radius=0.3))
    composite.paste(card_rgba, (0, 0), t_mask)

    # 2. Composite Type Line Box
    typ = boxes.get("type_box") or (int(40 * sx), int(578 * sy), int(705 * sx), int(628 * sy))
    typ_mask = Image.new("L", (cw, ch), 0)
    typd = ImageDraw.Draw(typ_mask)
    typd.rounded_rectangle(typ, radius=max(4, int(24 * sy * s_eff)), fill=255)
    typ_mask = typ_mask.filter(ImageFilter.GaussianBlur(radius=0.3))
    composite.paste(card_rgba, (0, 0), typ_mask)

    # 3. Composite Rules Text Box
    rb = boxes.get("rules_box") or (int(46 * sx), int(646 * sy), int(699 * sx), int(940 * sy))
    sb = boxes.get("stat_box")
    stat_poly = boxes.get("stat_polygon")

    if is_borderless:
        # For borderless/translucent cards:
        # Draw clean dark tinted backing to eliminate old art from the text box
        cdraw = ImageDraw.Draw(composite)
        if sb and not stat_poly:
            # Notched backing for creature cards to seamlessly meet the P/T box
            notch_offset = int(6 * sy * s_eff)
            rb_poly = [
                (rb[0], rb[1]),
                (rb[2], rb[1]),
                (rb[2], sb[1] + notch_offset),
                (sb[0], sb[1] + notch_offset),
                (sb[0], rb[3]),
                (rb[0], rb[3]),
            ]
            cdraw.polygon(rb_poly, fill=(16, 18, 22, 235))
            cdraw.line([
                (rb[0], rb[3]),
                (rb[0], rb[1]),
                (rb[2], rb[1]),
                (rb[2], sb[1] + notch_offset),
            ], fill=(60, 65, 75, 255), width=2)
            cdraw.line([
                (rb[0], rb[3]),
                (sb[0], rb[3]),
            ], fill=(60, 65, 75, 255), width=2)
        else:
            cdraw.rounded_rectangle(rb, radius=max(4, int(10 * sx * s_eff)), fill=(16, 18, 22, 235), outline=(60, 65, 75, 255), width=2)

        # Crop rules box region from card
        rules_crop = card_rgba.crop(rb)
        gray = rules_crop.convert("L")
        # Extract text / symbols / border (bright pixels & high contrast)
        text_mask = gray.point(lambda p: 255 if p > 130 else int(max(0, (p - 75) * 4.5)))
        composite.paste(rules_crop, (rb[0], rb[1]), text_mask)
    else:
        # Standard opaque rules box
        rb_mask = Image.new("L", (cw, ch), 0)
        rbd = ImageDraw.Draw(rb_mask)
        rbd.rounded_rectangle(rb, radius=max(4, int(10 * sx * s_eff)), fill=255)
        rb_mask = rb_mask.filter(ImageFilter.GaussianBlur(radius=0.3))
        composite.paste(card_rgba, (0, 0), rb_mask)

    # 4. Composite Statistic Box (Power/Toughness, Loyalty Shield, or Defense Badge)
    if stat_poly:
        sp_mask = Image.new("L", (cw, ch), 0)
        spd = ImageDraw.Draw(sp_mask)
        spd.polygon(stat_poly, fill=255)
        sp_mask = sp_mask.filter(ImageFilter.GaussianBlur(radius=0.3))
        composite.paste(card_rgba, (0, 0), sp_mask)
    elif sb:
        sb_mask = Image.new("L", (cw, ch), 0)
        sbd = ImageDraw.Draw(sb_mask)
        sbd.rounded_rectangle(sb, radius=max(4, int(26 * sy * s_eff)), fill=255)
        sb_mask = sb_mask.filter(ImageFilter.GaussianBlur(radius=0.3))
        composite.paste(card_rgba, (0, 0), sb_mask)

    # Upscale composite to 800 DPI target MPC dimensions without black letterboxing bars
    final_canvas = ImageOps.fit(
        composite.convert("RGB"),
        (target_width, target_height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    return final_canvas


def composite_card(
    card_frame_img: Image.Image,
    generated_art_img: Image.Image,
    art_box: Optional[Union[Tuple[int, int, int, int], Dict[str, Any]]] = None,
    card_boxes: Optional[Dict[str, Any]] = None,
    card_scale: float = MPC_BLEED_SCALE,
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Unified card compositor that performs full-art background placement
    with card rules and statistic text box exclusion masking and MPC bleed margin scaling.
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
        card_scale=card_scale,
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

    # Save 800 DPI PNG (compress_level=6 gives fast zlib deflation without exhaustive multi-pass filter search)
    final_image.save(
        png_path,
        format="PNG",
        dpi=(target_dpi, target_dpi),
        compress_level=6,
    )

    # Save web thumbnail (e.g. 500px width)
    thumb_w = 480
    thumb_h = int(final_image.height * (thumb_w / final_image.width))
    thumb_img = final_image.resize((thumb_w, thumb_h), Image.Resampling.BICUBIC).convert("RGB")
    thumb_img.save(thumb_path, format="JPEG", quality=88, optimize=True)

    return str(png_path), str(thumb_path)
