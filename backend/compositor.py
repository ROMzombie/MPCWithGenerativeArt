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
# Physical canvas with bleed: 2.73 in x 3.71 in (69.3 mm x 94.2 mm) -> 2184 x 2968 pixels
MPC_800DPI_WIDTH = 2184
MPC_800DPI_HEIGHT = 2968

# Standard MTG physical poker card cut dimensions at 800 DPI (2.48" x 3.46" / 63mm x 88mm):
MPC_CUT_WIDTH = 1984
MPC_CUT_HEIGHT = 2768

# Default bleed scale factor for Scryfall card frame assets.
# 1.0 places the card frame at standard 1:1 scale within the physical cut area (1984x2768),
# while generative art fills the full 2184x2968 canvas (100px / 1/8" bleed margin on all four sides).
MPC_BLEED_SCALE = 1.0


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

    if scale_factor >= 1.0 and (canvas_w, canvas_h) == (cw, ch):
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

    def scale_circles(circles: Optional[List[Tuple[int, int, int, int]]]) -> List[Tuple[int, int, int, int]]:
        if not circles:
            return []
        return [
            (
                int(c[0] * scale_factor + ox),
                int(c[1] * scale_factor + oy),
                int(c[2] * scale_factor + ox),
                int(c[3] * scale_factor + oy),
            )
            for c in circles
        ]

    def scale_extra(extras: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if not extras:
            return []
        res = []
        for e in extras:
            b = e.get("box")
            if b:
                res.append({
                    "box": scale_box(b),
                    "type": e.get("type", "rect"),
                })
        return res

    scaled_boxes = {
        "art_box": scale_box(card_boxes.get("art_box")),
        "rules_box": scale_box(card_boxes.get("rules_box")),
        "stat_box": scale_box(card_boxes.get("stat_box")),
        "stat_polygon": scale_poly(card_boxes.get("stat_polygon")),
        "station_circles": scale_circles(card_boxes.get("station_circles")),
        "holo_stamp": scale_box(card_boxes.get("holo_stamp")),
        "extra_boxes": scale_extra(card_boxes.get("extra_boxes")),
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
    Specifically detects individual station circle badges for cards with the Station mechanic.
    Adapts dynamically to standard, planeswalker, borderless, showcase, and inverted card layouts.
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    # 1. Art Box Detection
    art_box = detect_art_box(card_img, art_crop_img)

    t_lower = (type_line or "").lower()
    l_lower = (layout or "").lower()
    effects = [str(e).lower() for e in (frame_effects or [])]

    is_saga = (l_lower == "saga") or ("saga" in t_lower)
    is_class = (l_lower == "class") or ("class" in t_lower)
    is_case = (l_lower == "case") or ("case" in t_lower)
    is_room = ("room" in t_lower) or (l_lower == "room") or (l_lower == "split" and "room" in t_lower)
    is_battle = any(k in t_lower for k in ["battle", "siege"]) or (l_lower == "battle")
    is_planeswalker = "walker" in t_lower
    is_creature = any(k in t_lower for k in ["creature", "vehicle", "spacecraft"])
    is_station = any(k in t_lower for k in ["planet", "station", "spacecraft"]) or "station" in l_lower

    is_borderless = (
        (border_color == "borderless")
        or ("inverted" in effects)
        or ("showcase" in effects)
        or ("extendedart" in effects)
        or bool(full_art)
        or (l_lower == "art_series")
    )
    has_flavor_name = bool(flavor_name)

    # 2. Specialized Frame Geometry Detection
    extra_boxes: List[Dict[str, Any]] = []
    station_circles: List[Tuple[int, int, int, int]] = []
    stat_polygon = None
    subtitle_polygon = None

    if is_saga:
        # Saga vertical chapter layout: left chapters column, right art column, bottom type pill
        title_pill = (int(42 * sx), int(44 * sy), int(702 * sx), int(100 * sy))
        title_box = title_pill
        rules_box = (int(40 * sx), int(108 * sy), int(372 * sx), int(868 * sy))
        art_box = (int(372 * sx), int(108 * sy), int(704 * sx), int(868 * sy))
        type_box = (int(42 * sx), int(876 * sy), int(702 * sx), int(932 * sy))
        stat_box = None
        holo_stamp = (int(336 * sx), int(946 * sy), int(408 * sx), int(984 * sy))
    elif is_class or is_case:
        # Class / Case vertical layout: left art column, right level abilities column, bottom type pill
        title_pill = (int(42 * sx), int(44 * sy), int(702 * sx), int(100 * sy))
        title_box = title_pill
        art_box = (int(40 * sx), int(108 * sy), int(372 * sx), int(868 * sy))
        rules_box = (int(372 * sx), int(108 * sy), int(704 * sx), int(868 * sy))
        type_box = (int(42 * sx), int(876 * sy), int(702 * sx), int(932 * sy))
        stat_box = None
        holo_stamp = (int(336 * sx), int(946 * sy), int(408 * sx), int(984 * sy))
    elif is_room:
        # Room horizontal dual-door layout inside standard vertical card
        title_pill = (int(42 * sx), int(488 * sy), int(130 * sx), int(950 * sy))
        title_box_2 = (int(42 * sx), int(50 * sy), int(130 * sx), int(484 * sy))
        title_box = title_pill
        rules_box = (int(540 * sx), int(488 * sy), int(704 * sx), int(950 * sy))
        rules_box_2 = (int(540 * sx), int(50 * sy), int(704 * sx), int(484 * sy))
        type_box = (int(450 * sx), int(50 * sy), int(530 * sx), int(950 * sy))
        art_box = (int(130 * sx), int(50 * sy), int(450 * sx), int(950 * sy))
        stat_box = None
        holo_stamp = (int(450 * sx), int(914 * sy), int(530 * sx), int(954 * sy))
        extra_boxes = [
            {"box": title_box_2, "type": "pill"},
            {"box": rules_box_2, "type": "rect"},
        ]
    elif is_battle:
        # Battle - Siege landscape format inside standard vertical card
        title_pill = (int(42 * sx), int(50 * sy), int(130 * sx), int(896 * sy))
        title_box = title_pill
        type_box = (int(570 * sx), int(590 * sy), int(704 * sx), int(896 * sy))
        rules_box = (int(570 * sx), int(50 * sy), int(704 * sx), int(586 * sy))
        art_box = (int(130 * sx), int(50 * sy), int(570 * sx), int(950 * sy))
        stat_polygon = [
            (int(640 * sx), int(30 * sy)),
            (int(730 * sx), int(20 * sy)),
            (int(730 * sx), int(100 * sy)),
            (int(640 * sx), int(70 * sy)),
        ]
        stat_box = (int(640 * sx), int(20 * sy), int(730 * sx), int(100 * sy))
        holo_stamp = (int(450 * sx), int(914 * sy), int(536 * sx), int(954 * sy))
    else:
        # Standard Card Frame (Creature, Planeswalker, Instant, Sorcery, Enchantment, Artifact, Land)
        title_pill = (int(42 * sx), int(44 * sy), int(702 * sx), int(100 * sy))
        if has_flavor_name:
            subtitle_polygon = [
                (int(85 * sx), int(94 * sy)),
                (int(660 * sx), int(94 * sy)),
                (int(636 * sx), int(138 * sy)),
                (int(109 * sx), int(138 * sy)),
            ]
            title_box = (int(42 * sx), int(44 * sy), int(702 * sx), int(138 * sy))
        else:
            title_box = title_pill

        type_box = (int(42 * sx), int(576 * sy), int(702 * sx), int(632 * sy))
        holo_stamp = (int(336 * sx), int(946 * sy), int(408 * sx), int(984 * sy))

        if is_planeswalker:
            rules_box = (int(40 * sx), int(646 * sy), int(704 * sx), int(964 * sy))
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
            stat_box = (int(570 * sx), int(918 * sy), int(708 * sx), int(984 * sy))
            if is_borderless:
                rules_box = (int(40 * sx), int(626 * sy), int(704 * sx), int(964 * sy))
            else:
                rules_box = (int(40 * sx), int(646 * sy), int(704 * sx), int(964 * sy))
        else:
            stat_box = None
            if is_borderless:
                rules_box = (int(40 * sx), int(626 * sy), int(704 * sx), int(964 * sy))
            else:
                rules_box = (int(40 * sx), int(646 * sy), int(704 * sx), int(964 * sy))

        if is_station:
            probe_x = int(24 * sx)
            found_segments = []
            in_seg = False
            seg_start = 0
            for y in range(int(650 * sy), int(950 * sy)):
                p = card_img.getpixel((probe_x, y))
                b = sum(p[:3]) / 3.0
                if b > 28:
                    if not in_seg:
                        in_seg = True
                        seg_start = y
                else:
                    if in_seg:
                        in_seg = False
                        if y - seg_start >= int(14 * sy):
                            found_segments.append((seg_start, y))
            if in_seg and (int(950 * sy) - seg_start >= int(14 * sy)):
                found_segments.append((seg_start, int(950 * sy)))

            circ_cx = int(47 * sx)
            circ_r = int(27 * sx)
            for s_y, e_y in found_segments:
                circ_cy = (s_y + e_y) // 2
                station_circles.append((circ_cx - circ_r, circ_cy - circ_r, circ_cx + circ_r, circ_cy + circ_r))

    return {
        "art_box": art_box,
        "rules_box": rules_box,
        "stat_box": stat_box,
        "stat_polygon": stat_polygon,
        "station_circles": station_circles,
        "holo_stamp": holo_stamp,
        "extra_boxes": extra_boxes,
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
    with smooth beveled corners. Supports optional card scaling and targeted station circle masking.
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

    # 1. Preserve Title Header (Pill + Subtitle Polygon)
    t_pill = boxes.get("title_pill") or (int(42 * sx), int(44 * sy), int(702 * sx), int(100 * sy))
    draw.rounded_rectangle(t_pill, radius=max(4, int(24 * sy * s_eff)), fill=255)
    sub_poly = boxes.get("subtitle_polygon")
    if sub_poly:
        draw.polygon(sub_poly, fill=255)

    # 2. Preserve Type Line
    typ = boxes.get("type_box") or (int(42 * sx), int(576 * sy), int(702 * sx), int(632 * sy))
    draw.rounded_rectangle([typ[0], typ[1], typ[2], typ[3]], radius=max(4, int(24 * sy * s_eff)), fill=255)

    # 3. Preserve Rules Text Box, Station Circles & Holo Stamp Crest
    rb = boxes.get("rules_box") or (int(40 * sx), int(646 * sy), int(704 * sx), int(964 * sy))
    draw.rounded_rectangle([rb[0], rb[1], rb[2], rb[3]], radius=max(4, int(8 * sx * s_eff)), fill=255)
    for circ in boxes.get("station_circles", []):
        draw.ellipse([circ[0], circ[1], circ[2], circ[3]], fill=255)
    holo = boxes.get("holo_stamp")
    if holo:
        draw.ellipse([holo[0], holo[1], holo[2], holo[3]], fill=255)

    # 4. Preserve Extra Boxes (e.g. Room Door 2 / Dual Spells)
    for eb in boxes.get("extra_boxes", []):
        b = eb.get("box")
        if b:
            if eb.get("type") == "pill":
                draw.rounded_rectangle(b, radius=max(4, int(22 * sx * s_eff)), fill=255)
            else:
                draw.rounded_rectangle(b, radius=max(4, int(8 * sx * s_eff)), fill=255)

    # 5. Preserve Statistic Text Box / Polygonal Shield if present
    stat_poly = boxes.get("stat_polygon")
    if stat_poly:
        draw.polygon(stat_poly, fill=255)
    else:
        sb = boxes.get("stat_box")
        if sb:
            draw.rounded_rectangle([sb[0], sb[1], sb[2], sb[3]], radius=max(4, int(26 * sy * s_eff)), fill=255)

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
    Composites a full-art background image with individually masked card rules, title bar,
    type line, and statistic text boxes. Places the physical MTG card frame at 1:1 scale
    within the physical cut dimensions (1984x2768), with generative art extending across the
    full 2184x2968 canvas for 1/8" MakePlayingCards bleed margin.
    """
    cw, ch = card_frame_img.size

    # Calculate physical card cut dimensions inside target canvas (e.g. 1984x2768 at 800 DPI)
    base_card_w = int(target_width * (MPC_CUT_WIDTH / MPC_800DPI_WIDTH))
    base_card_h = int(target_height * (MPC_CUT_HEIGHT / MPC_800DPI_HEIGHT))

    eff_card_w = int(base_card_w * card_scale)
    eff_card_h = int(base_card_h * card_scale)

    ox = (target_width - eff_card_w) // 2
    oy = (target_height - eff_card_h) // 2

    # Scale card frame to fit physical card bounds on target canvas
    card_scaled = card_frame_img.resize((eff_card_w, eff_card_h), Image.Resampling.LANCZOS)
    card_canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
    card_canvas.paste(card_scaled.convert("RGBA"), (ox, oy))

    # Scale factors from card frame coordinates to target canvas coordinates
    scale_x = eff_card_w / cw
    scale_y = eff_card_h / ch

    def map_box(b: Optional[Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
        if not b:
            return None
        return (
            int(b[0] * scale_x + ox),
            int(b[1] * scale_y + oy),
            int(b[2] * scale_x + ox),
            int(b[3] * scale_y + oy),
        )

    def map_poly(poly: Optional[List[Tuple[int, int]]]) -> Optional[List[Tuple[int, int]]]:
        if not poly:
            return None
        return [(int(px * scale_x + ox), int(py * scale_y + oy)) for (px, py) in poly]

    def map_circles(circles: Optional[List[Tuple[int, int, int, int]]]) -> List[Tuple[int, int, int, int]]:
        if not circles:
            return []
        return [
            (
                int(c[0] * scale_x + ox),
                int(c[1] * scale_y + oy),
                int(c[2] * scale_x + ox),
                int(c[3] * scale_y + oy),
            )
            for c in circles
        ]

    # Map all detected boxes to 800 DPI canvas coordinates
    t_pill = map_box(card_boxes.get("title_pill")) or (
        int(42 * scale_x + ox),
        int(44 * scale_y + oy),
        int(702 * scale_x + ox),
        int(100 * scale_y + oy),
    )
    sub_poly = map_poly(card_boxes.get("subtitle_polygon"))
    typ = map_box(card_boxes.get("type_box")) or (
        int(42 * scale_x + ox),
        int(576 * scale_y + oy),
        int(702 * scale_x + ox),
        int(632 * scale_y + oy),
    )
    rb = map_box(card_boxes.get("rules_box")) or (
        int(40 * scale_x + ox),
        int(646 * scale_y + oy),
        int(704 * scale_x + ox),
        int(964 * scale_y + oy),
    )
    sb = map_box(card_boxes.get("stat_box"))
    stat_poly = map_poly(card_boxes.get("stat_polygon"))
    station_circles = map_circles(card_boxes.get("station_circles"))
    holo_stamp = map_box(card_boxes.get("holo_stamp"))
    is_borderless = card_boxes.get("is_borderless", False)

    extra_boxes = []
    for eb in card_boxes.get("extra_boxes", []):
        b = map_box(eb.get("box"))
        if b:
            extra_boxes.append({"box": b, "type": eb.get("type", "rect")})

    # Fit full-art generated image across the entire 800 DPI canvas
    art_full = ImageOps.fit(
        generated_art_img.convert("RGBA"),
        (target_width, target_height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.33),
    )

    composite = art_full.copy()
    pill_radius = max(4, int(24 * (eff_card_h / 1040.0)))
    rules_radius = max(4, int(8 * (eff_card_w / 745.0)))
    stat_radius = max(4, int(26 * (eff_card_h / 1040.0)))

    # 1. Composite Title Header (Pill + Subtitle Polygon)
    t_mask = Image.new("L", (target_width, target_height), 0)
    td = ImageDraw.Draw(t_mask)
    td.rounded_rectangle(t_pill, radius=pill_radius, fill=255)
    if sub_poly:
        td.polygon(sub_poly, fill=255)
    t_mask = t_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
    composite.paste(card_canvas, (0, 0), t_mask)

    # 2. Composite Type Line Box
    typ_mask = Image.new("L", (target_width, target_height), 0)
    typd = ImageDraw.Draw(typ_mask)
    typd.rounded_rectangle(typ, radius=pill_radius, fill=255)
    typ_mask = typ_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
    composite.paste(card_canvas, (0, 0), typ_mask)

    # 3. Composite Rules Text Box & Station Circles & Holo Stamp Crest
    if is_borderless:
        cdraw = ImageDraw.Draw(composite)
        if sb and not stat_poly:
            notch_offset = int(6 * (eff_card_h / 1040.0))
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
            cdraw.rounded_rectangle(rb, radius=rules_radius, fill=(16, 18, 22, 235), outline=(60, 65, 75, 255), width=2)

        for circ in station_circles:
            cdraw.ellipse([circ[0], circ[1], circ[2], circ[3]], fill=(16, 18, 22, 235), outline=(60, 65, 75, 255), width=2)

        if holo_stamp:
            cdraw.ellipse([holo_stamp[0], holo_stamp[1], holo_stamp[2], holo_stamp[3]], fill=(16, 18, 22, 235), outline=(60, 65, 75, 255), width=2)

        # Crop rules box region from card canvas
        rules_crop = card_canvas.crop(rb)
        gray = rules_crop.convert("L")
        text_mask = gray.point(lambda p: 255 if p > 130 else int(max(0, (p - 75) * 4.5)))
        composite.paste(rules_crop, (rb[0], rb[1]), text_mask)

        for circ in station_circles:
            circ_crop = card_canvas.crop(circ)
            circ_gray = circ_crop.convert("L")
            circ_mask = circ_gray.point(lambda p: 255 if p > 130 else int(max(0, (p - 75) * 4.5)))
            composite.paste(circ_crop, (circ[0], circ[1]), circ_mask)

        if holo_stamp:
            holo_crop = card_canvas.crop(holo_stamp)
            holo_gray = holo_crop.convert("L")
            holo_mask = holo_gray.point(lambda p: 255 if p > 130 else int(max(0, (p - 75) * 4.5)))
            composite.paste(holo_crop, (holo_stamp[0], holo_stamp[1]), holo_mask)
    else:
        # Standard opaque rules box + station circle badges + holo stamp crest
        rb_mask = Image.new("L", (target_width, target_height), 0)
        rbd = ImageDraw.Draw(rb_mask)
        rbd.rounded_rectangle(rb, radius=rules_radius, fill=255)
        for circ in station_circles:
            rbd.ellipse([circ[0], circ[1], circ[2], circ[3]], fill=255)
        if holo_stamp:
            rbd.ellipse([holo_stamp[0], holo_stamp[1], holo_stamp[2], holo_stamp[3]], fill=255)
        rb_mask = rb_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
        composite.paste(card_canvas, (0, 0), rb_mask)

    # 4. Composite Extra Boxes (e.g. Room Door 2 / Dual Spells)
    for eb in extra_boxes:
        b = eb["box"]
        eb_mask = Image.new("L", (target_width, target_height), 0)
        ebd = ImageDraw.Draw(eb_mask)
        if eb["type"] == "pill":
            ebd.rounded_rectangle(b, radius=pill_radius, fill=255)
        else:
            ebd.rounded_rectangle(b, radius=rules_radius, fill=255)
        eb_mask = eb_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
        composite.paste(card_canvas, (0, 0), eb_mask)

    # 5. Composite Statistic Box (Power/Toughness, Loyalty Shield, or Defense Badge)
    if stat_poly:
        sp_mask = Image.new("L", (target_width, target_height), 0)
        spd = ImageDraw.Draw(sp_mask)
        spd.polygon(stat_poly, fill=255)
        sp_mask = sp_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
        composite.paste(card_canvas, (0, 0), sp_mask)
    elif sb:
        sb_mask = Image.new("L", (target_width, target_height), 0)
        sbd = ImageDraw.Draw(sb_mask)
        sbd.rounded_rectangle(sb, radius=stat_radius, fill=255)
        sb_mask = sb_mask.filter(ImageFilter.GaussianBlur(radius=1.0))
        composite.paste(card_canvas, (0, 0), sb_mask)

    return composite.convert("RGB")


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
    with card rules, station circle badges, and statistic text box exclusion masking
    and MakePlayingCards 800 DPI bleed canvas dimensions.
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
