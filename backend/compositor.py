"""Card image compositor, card box detector, exclusion masking, and 800 DPI MPC exporter."""

import os
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, Union, List
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops, ImageFont, ImageEnhance

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
    security_stamp: Optional[str] = None,
    rarity: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    oracle_text: Optional[str] = None,
    card_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detects individual borders of the card rules and statistic text boxes,
    along with art box, title header (and subtitle banner if present), and type line.
    Specifically detects individual station circle badges for cards with the Station mechanic.
    Adapts dynamically to standard, planeswalker, borderless, showcase, rooms, and split cards (with/without Fuse).
    """
    cw, ch = card_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    # 1. Art Box Detection
    art_box = detect_art_box(card_img, art_crop_img)

    t_lower = (type_line or "").lower()
    l_lower = (layout or "").lower()
    c_lower = (card_name or "").lower()
    effects = [str(e).lower() for e in (frame_effects or [])]
    k_lower = [str(k).lower() for k in (keywords or [])]
    o_lower = (oracle_text or "").lower()

    is_saga = (l_lower == "saga") or ("saga" in t_lower)
    is_class = (l_lower == "class") or ("class" in t_lower)
    is_case = (l_lower == "case") or ("case" in t_lower)
    is_adventure = (l_lower == "adventure") or ("adventure" in t_lower) or ("adventure" in effects)
    is_room = ("room" in t_lower) or (l_lower == "room")
    is_split = (not is_room) and (not is_adventure) and (
        (l_lower == "split")
        or ("//" in c_lower and l_lower != "adventure" and "adventure" not in t_lower and any(kw in t_lower for kw in ["instant", "sorcery", "spell"]))
    )
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
    extra_polygons: List[List[Tuple[int, int]]] = []
    station_circles: List[Tuple[int, int, int, int]] = []
    loyalty_polygons: List[List[Tuple[int, int]]] = []
    stat_polygon = None
    subtitle_polygon = None

    # Holo stamp detection: Sagas, Classes, Cases, Rooms, Split cards, and Battles never mask holofoil space.
    # Standard commons/uncommons do not have a holographic security stamp.
    has_holo = (
        not (is_saga or is_class or is_case or is_room or is_split or is_battle)
        and (
            (security_stamp is not None and security_stamp.lower() not in ["", "none", "arena"])
            or (rarity and rarity.lower() in ["rare", "mythic", "special", "bonus"])
            or ("legendary" in t_lower)
            or ("holofoil" in effects)
            or ("security_stamp" in effects)
        )
    )
    holo_stamp = (int(336 * sx), int(946 * sy), int(408 * sx), int(984 * sy)) if has_holo else None

    stamp_type = "oval"
    if security_stamp:
        s_clean = security_stamp.strip().lower()
        if "triangle" in s_clean:
            stamp_type = "triangle"
        elif "acorn" in s_clean:
            stamp_type = "acorn"
        elif "heart" in s_clean:
            stamp_type = "heart"
        elif s_clean in ["oval", "circle", "arena"]:
            stamp_type = s_clean
    elif any("triangle" in f for f in effects):
        stamp_type = "triangle"
    elif any("acorn" in f for f in effects):
        stamp_type = "acorn"

    if is_saga:
        # Saga vertical chapter layout:
        # 1. Main parchment rules text box: x=54..372, y=120..868 (prevents top & bottom left bleed)
        # 2. Left chapter bookmark ribbon polygon: x=33..90, y=240..842 (preserves chapter hexagon badges)
        # 3. Right art column & bottom type pill
        title_pill = (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
        title_box = title_pill
        rules_box = (int(54 * sx), int(120 * sy), int(372 * sx), int(868 * sy))
        art_box = (int(372 * sx), int(120 * sy), int(694 * sx), int(868 * sy))
        type_box = (int(44 * sx), int(880 * sy), int(700 * sx), int(936 * sy))
        stat_box = None
        extra_polygons = [
            [
                (int(54 * sx), int(260 * sy)),
                (int(33 * sx), int(290 * sy)),
                (int(33 * sx), int(805 * sy)),
                (int(62 * sx), int(842 * sy)),
                (int(90 * sx), int(805 * sy)),
                (int(90 * sx), int(240 * sy)),
            ]
        ]
    elif is_class:
        # Class vertical layout: left art column, right level abilities column (x=372..688 to eliminate right bleed), bottom type pill
        title_pill = (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
        title_box = title_pill
        art_box = (int(50 * sx), int(120 * sy), int(372 * sx), int(868 * sy))
        rules_box = (int(372 * sx), int(120 * sy), int(688 * sx), int(868 * sy))
        type_box = (int(44 * sx), int(880 * sy), int(700 * sx), int(936 * sy))
        stat_box = None
    elif is_case:
        # Case vertical layout: left art column, right case stages column, bottom type pill
        title_pill = (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
        title_box = title_pill
        art_box = (int(50 * sx), int(120 * sy), int(372 * sx), int(868 * sy))
        rules_box = (int(372 * sx), int(120 * sy), int(678 * sx), int(868 * sy))
        type_box = (int(44 * sx), int(880 * sy), int(700 * sx), int(936 * sy))
        stat_box = None
    elif is_room:
        # Room dual-door layout inside standard vertical card:
        # Door B (bottom): vertical title pill at bottom-left, rules box at bottom-right
        # Door A (top): vertical title pill at top-left, rules box at top-right
        # Vertical Type line (Enchantment — Room) at bottom-center. Central reminder text is excluded from mask.
        title_pill = (int(44 * sx), int(515 * sy), int(100 * sx), int(940 * sy))
        title_box = title_pill
        type_box = (int(400 * sx), int(515 * sy), int(448 * sx), int(940 * sy))
        rules_box = (int(538 * sx), int(515 * sy), int(702 * sx), int(940 * sy))
        art_box = (int(100 * sx), int(44 * sy), int(400 * sx), int(940 * sy))
        stat_box = None
        extra_boxes = [
            {"box": (int(44 * sx), int(44 * sy), int(100 * sx), int(490 * sy)), "type": "pill"},
            {"box": (int(400 * sx), int(44 * sy), int(448 * sx), int(100 * sy)), "type": "pill"},
            {"box": (int(538 * sx), int(44 * sy), int(702 * sx), int(490 * sy)), "type": "rect"},
        ]
    elif is_split:
        # Split card layout (Two variants: With Fuse and Without Fuse)
        has_fuse = (
            ("fuse" in k_lower)
            or ("fuse" in (security_stamp or "").lower())
            or ("fuse" in o_lower)
            or any("fuse" in f for f in effects)
        )
        if not has_fuse and card_img is not None:
            # Check right-middle probe on card frame
            probe_p = card_img.getpixel((int(625 * sx), int(505 * sy)))
            if sum(probe_p[:3]) / 3.0 > 80:
                has_fuse = True

        if has_fuse:
            # Split card WITH Fuse:
            title_pill = (int(44 * sx), int(515 * sy), int(100 * sx), int(965 * sy))
            title_box = title_pill
            type_box = (int(415 * sx), int(515 * sy), int(452 * sx), int(965 * sy))
            rules_box = (int(452 * sx), int(515 * sy), int(605 * sx), int(965 * sy))
            art_box = (int(100 * sx), int(44 * sy), int(415 * sx), int(965 * sy))
            extra_boxes = [
                # Top half components
                {"box": (int(44 * sx), int(44 * sy), int(100 * sx), int(490 * sy)), "type": "pill"},
                {"box": (int(415 * sx), int(44 * sy), int(452 * sx), int(490 * sy)), "type": "pill"},
                {"box": (int(452 * sx), int(44 * sy), int(605 * sx), int(490 * sy)), "type": "rect"},
                # Center connection bridges
                {"box": (int(44 * sx), int(485 * sy), int(100 * sx), int(520 * sy)), "type": "rect"},
                {"box": (int(415 * sx), int(485 * sy), int(452 * sx), int(520 * sy)), "type": "rect"},
                # Fuse full-height pill on right
                {"box": (int(605 * sx), int(44 * sy), int(650 * sx), int(965 * sy)), "type": "pill"},
            ]
        else:
            # Split card WITHOUT Fuse:
            title_pill = (int(44 * sx), int(515 * sy), int(100 * sx), int(936 * sy))
            title_box = title_pill
            type_box = (int(400 * sx), int(515 * sy), int(448 * sx), int(936 * sy))
            rules_box = (int(452 * sx), int(515 * sy), int(654 * sx), int(936 * sy))
            art_box = (int(100 * sx), int(44 * sy), int(400 * sx), int(936 * sy))
            extra_boxes = [
                {"box": (int(44 * sx), int(44 * sy), int(100 * sx), int(465 * sy)), "type": "pill"},
                {"box": (int(400 * sx), int(44 * sy), int(448 * sx), int(465 * sy)), "type": "pill"},
                {"box": (int(452 * sx), int(44 * sy), int(654 * sx), int(465 * sy)), "type": "rect"},
            ]
        stat_box = None
    elif is_battle:
        # Battle - Siege landscape format inside standard vertical card
        # Left vertical title column, vertical type line, single continuous rules text box, and 8-pointed defense star
        title_pill = (int(44 * sx), int(52 * sy), int(100 * sx), int(908 * sy))
        title_box = title_pill
        type_box = (int(574 * sx), int(52 * sy), int(632 * sx), int(908 * sy))
        rules_box = (int(636 * sx), int(70 * sy), int(702 * sx), int(890 * sy))
        art_box = (int(100 * sx), int(52 * sy), int(574 * sx), int(908 * sy))
        stat_polygon = [
            (int(671 * sx), int(14 * sy)),
            (int(681 * sx), int(25 * sy)),
            (int(702 * sx), int(21 * sy)),
            (int(695 * sx), int(38 * sy)),
            (int(705 * sx), int(47 * sy)),
            (int(695 * sx), int(57 * sy)),
            (int(702 * sx), int(73 * sy)),
            (int(681 * sx), int(69 * sy)),
            (int(671 * sx), int(80 * sy)),
            (int(661 * sx), int(69 * sy)),
            (int(640 * sx), int(73 * sy)),
            (int(647 * sx), int(57 * sy)),
            (int(637 * sx), int(47 * sy)),
            (int(647 * sx), int(38 * sy)),
            (int(640 * sx), int(21 * sy)),
            (int(661 * sx), int(25 * sy)),
        ]
        stat_box = (int(637 * sx), int(14 * sy), int(705 * sx), int(80 * sy))
    elif is_adventure:
        # Adventure split layout (Left: Adventure Spell Scroll, Right: Creature text box)
        title_pill = (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
        title_box = title_pill
        type_box = (int(46 * sx), int(584 * sy), int(698 * sx), int(644 * sy))
        rules_box = (int(54 * sx), int(650 * sy), int(690 * sx), int(958 * sy))
        stat_polygon = [
            (int(585 * sx), int(918 * sy)),
            (int(695 * sx), int(918 * sy)),
            (int(708 * sx), int(930 * sy)),
            (int(708 * sx), int(970 * sy)),
            (int(695 * sx), int(984 * sy)),
            (int(585 * sx), int(984 * sy)),
            (int(568 * sx), int(966 * sy)),
            (int(566 * sx), int(951 * sy)),
            (int(568 * sx), int(936 * sy)),
            (int(585 * sx), int(918 * sy)),
        ]
        stat_box = (int(566 * sx), int(918 * sy), int(708 * sx), int(984 * sy))
    else:
        # Standard Card Frame (Creature, Planeswalker, Instant, Sorcery, Enchantment, Artifact, Land)
        # Note: Only name pill (and subtitle if present) is masked; legendary crowns are excluded
        title_pill = (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
        if has_flavor_name:
            subtitle_polygon = [
                (int(85 * sx), int(104 * sy)),
                (int(660 * sx), int(104 * sy)),
                (int(636 * sx), int(144 * sy)),
                (int(109 * sx), int(144 * sy)),
            ]
            title_box = (int(46 * sx), int(50 * sy), int(698 * sx), int(144 * sy))
        else:
            title_box = title_pill

        type_box = (int(46 * sx), int(584 * sy), int(698 * sx), int(644 * sy))

        if is_planeswalker:
            # Planeswalker title pill is slightly narrower
            title_pill = (int(46 * sx), int(44 * sy), int(698 * sx), int(98 * sy))
            title_box = title_pill
            rules_box = (int(54 * sx), int(650 * sy), int(690 * sx), int(960 * sy))
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

            # Dynamically detect 1-4 individual loyalty ability shield badges in the rules text box
            badge_rows = []
            for y in range(int(650 * sy), int(935 * sy)):
                has_dark = any(sum(card_img.getpixel((int(x * sx), y))[:3]) < 100 for x in range(60, 95))
                badge_rows.append((y, has_dark))

            clusters = []
            cur_cluster = []
            for y, is_d in badge_rows:
                if is_d:
                    cur_cluster.append(y)
                else:
                    if len(cur_cluster) >= 12:
                        clusters.append((cur_cluster[0], cur_cluster[-1]))
                    cur_cluster = []
            if len(cur_cluster) >= 12:
                clusters.append((cur_cluster[0], cur_cluster[-1]))

            for y_start, y_end in clusters:
                x_left = int(42 * sx)
                x_right = int(114 * sx)
                x_mid = int(78 * sx)
                top_mid = y_start
                for y in range(max(0, y_start - 15), y_start + 5):
                    if sum(card_img.getpixel((x_mid, y))[:3]) < 120:
                        top_mid = y
                        break
                bot_mid = y_end
                for y in range(min(ch - 1, y_end + 15), y_end - 5, -1):
                    if sum(card_img.getpixel((x_mid, y))[:3]) < 120:
                        bot_mid = y
                        break
                is_up = (y_start - top_mid >= bot_mid - y_end)
                if is_up:
                    poly = [
                        (x_mid, top_mid - int(3 * sy)),
                        (x_right, top_mid + int(18 * sy)),
                        (x_right, y_end + int(3 * sy)),
                        (x_mid, y_end + int(5 * sy)),
                        (x_left, y_end + int(3 * sy)),
                        (x_left, top_mid + int(18 * sy)),
                    ]
                else:
                    poly = [
                        (x_left, y_start - int(3 * sy)),
                        (x_mid, y_start - int(5 * sy)),
                        (x_right, y_start - int(3 * sy)),
                        (x_right, bot_mid - int(18 * sy)),
                        (x_mid, bot_mid + int(3 * sy)),
                        (x_left, bot_mid - int(18 * sy)),
                    ]
                loyalty_polygons.append(poly)
        elif is_creature:
            stat_polygon = [
                (int(585 * sx), int(918 * sy)),
                (int(695 * sx), int(918 * sy)),
                (int(708 * sx), int(930 * sy)),
                (int(708 * sx), int(970 * sy)),
                (int(695 * sx), int(984 * sy)),
                (int(585 * sx), int(984 * sy)),
                (int(568 * sx), int(966 * sy)),
                (int(566 * sx), int(951 * sy)),
                (int(568 * sx), int(936 * sy)),
                (int(585 * sx), int(918 * sy)),
            ]
            stat_box = (int(566 * sx), int(918 * sy), int(708 * sx), int(984 * sy))
            if is_borderless:
                rules_box = (int(50 * sx), int(630 * sy), int(694 * sx), int(960 * sy))
            else:
                rules_box = (int(54 * sx), int(650 * sy), int(690 * sx), int(958 * sy))
        else:
            stat_box = None
            stat_polygon = None
            if is_borderless:
                rules_box = (int(50 * sx), int(630 * sy), int(694 * sx), int(960 * sy))
            else:
                rules_box = (int(54 * sx), int(650 * sy), int(690 * sx), int(958 * sy))

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
        "loyalty_polygons": loyalty_polygons,
        "station_circles": station_circles,
        "holo_stamp": holo_stamp,
        "stamp_type": stamp_type,
        "extra_boxes": extra_boxes,
        "extra_polygons": extra_polygons,
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

    pill_radius = max(4, int(29 * sy * s_eff))
    rules_radius = max(4, int(10 * sx * s_eff))

    # 1. Preserve Title Header (Pill + Subtitle Polygon)
    t_pill = boxes.get("title_pill") or (int(46 * sx), int(50 * sy), int(698 * sx), int(110 * sy))
    draw.rounded_rectangle(t_pill, radius=pill_radius, fill=255)
    sub_poly = boxes.get("subtitle_polygon")
    if sub_poly:
        draw.polygon(sub_poly, fill=255)

    # 2. Preserve Type Line
    typ = boxes.get("type_box") or (int(46 * sx), int(584 * sy), int(698 * sx), int(644 * sy))
    draw.rounded_rectangle([typ[0], typ[1], typ[2], typ[3]], radius=pill_radius, fill=255)

    # 3. Preserve Rules Text Box, Station Circles & Holo Stamp Crest
    rb = boxes.get("rules_box") or (int(54 * sx), int(650 * sy), int(690 * sx), int(958 * sy))
    draw.rounded_rectangle([rb[0], rb[1], rb[2], rb[3]], radius=rules_radius, fill=255)
    for circ in boxes.get("station_circles", []):
        draw.ellipse([circ[0], circ[1], circ[2], circ[3]], fill=255)
    for lpoly in boxes.get("loyalty_polygons", []):
        draw.polygon(lpoly, fill=255)
    for epoly in boxes.get("extra_polygons", []):
        draw.polygon(epoly, fill=255)
    holo = boxes.get("holo_stamp")
    if holo:
        draw.ellipse([holo[0], holo[1], holo[2], holo[3]], fill=255)

    # 4. Preserve Extra Boxes (e.g. Room Door 2 / Dual Spells)
    for eb in boxes.get("extra_boxes", []):
        b = eb.get("box")
        if b:
            if eb.get("type") == "pill":
                draw.rounded_rectangle(b, radius=max(4, int(29 * sy * s_eff)), fill=255)
            else:
                draw.rounded_rectangle(b, radius=max(4, int(10 * sx * s_eff)), fill=255)

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
        int(46 * scale_x + ox),
        int(50 * scale_y + oy),
        int(698 * scale_x + ox),
        int(110 * scale_y + oy),
    )
    sub_poly = map_poly(card_boxes.get("subtitle_polygon"))
    typ = map_box(card_boxes.get("type_box")) or (
        int(46 * scale_x + ox),
        int(584 * scale_y + oy),
        int(698 * scale_x + ox),
        int(644 * scale_y + oy),
    )
    rb = map_box(card_boxes.get("rules_box")) or (
        int(54 * scale_x + ox),
        int(650 * scale_y + oy),
        int(690 * scale_x + ox),
        int(958 * scale_y + oy),
    )
    sb = map_box(card_boxes.get("stat_box"))
    stat_poly = map_poly(card_boxes.get("stat_polygon"))
    loyalty_polys = [map_poly(lp) for lp in card_boxes.get("loyalty_polygons", []) if lp]
    extra_polys = [map_poly(ep) for ep in card_boxes.get("extra_polygons", []) if ep]
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
    pill_radius = max(4, int(29 * (eff_card_h / 1040.0)))
    rules_radius = max(4, int(10 * (eff_card_w / 745.0)))
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
        if stat_poly or sb:
            pt_left = stat_poly[6][0] if (stat_poly and len(stat_poly) > 6) else (sb[0] if sb else rb[2])
            pt_top = stat_poly[0][1] if stat_poly else (sb[1] if sb else rb[3])
            notch_offset = int(6 * (eff_card_h / 1040.0))
            rb_poly = [
                (rb[0], rb[1]),
                (rb[2], rb[1]),
                (rb[2], pt_top + notch_offset),
                (pt_left, pt_top + notch_offset),
                (pt_left, rb[3]),
                (rb[0], rb[3]),
            ]
            cdraw.polygon(rb_poly, fill=(16, 18, 22, 235))
            cdraw.line([
                (rb[0], rb[3]),
                (rb[0], rb[1]),
                (rb[2], rb[1]),
                (rb[2], pt_top + notch_offset),
            ], fill=(60, 65, 75, 255), width=2)
            cdraw.line([
                (rb[0], rb[3]),
                (pt_left, rb[3]),
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
        for lp in loyalty_polys:
            rbd.polygon(lp, fill=255)
        for ep in extra_polys:
            rbd.polygon(ep, fill=255)
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


def get_bold_arial_font(size: int) -> ImageFont.ImageFont:
    """
    Attempts to load bold Arial font from local system font locations,
    falling back to standard Arial or default bitmap/TrueType font.
    """
    font_candidates = [
        "arialbd.ttf",
        "Arial-Bold.ttf",
        "Arial_Bold.ttf",
        "Arial Bold.ttf",
        "arial.ttf",
        "Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def sample_border_background_color(card_img: Image.Image, sx: float, sy: float) -> Tuple[int, int, int]:
    """
    Samples the card's native border/background color from unprinted margins
    in the bottom border area to match the exact underlying frame color
    instead of assuming pure #000000.
    """
    cw, ch = card_img.size
    sample_points = [
        (int(18 * sx), int(990 * sy)),
        (int(18 * sx), int(1010 * sy)),
        (int(18 * sx), int(1025 * sy)),
        (int(727 * sx), int(990 * sy)),
        (int(727 * sx), int(1010 * sy)),
        (int(727 * sx), int(1025 * sy)),
        (int(80 * sx), int(1030 * sy)),
        (int(150 * sx), int(1030 * sy)),
        (int(580 * sx), int(1030 * sy)),
        (int(660 * sx), int(1030 * sy)),
    ]
    rgb_samples = []
    for x, y in sample_points:
        if 0 <= x < cw and 0 <= y < ch:
            p = card_img.getpixel((x, y))
            rgb_samples.append(p[:3])

    if not rgb_samples:
        return (14, 16, 20)

    # Use median across sample points to reject outliers and stray text pixels
    r = int(sorted(s[0] for s in rgb_samples)[len(rgb_samples) // 2])
    g = int(sorted(s[1] for s in rgb_samples)[len(rgb_samples) // 2])
    b = int(sorted(s[2] for s in rgb_samples)[len(rgb_samples) // 2])
    return (r, g, b)


def mask_holo_stamp(
    draw: ImageDraw.ImageDraw,
    stamp_type: str,
    holo_box: Tuple[int, int, int, int],
    bg_color: Tuple[int, int, int],
    sx: float,
    sy: float,
) -> None:
    """
    Masks the holographic security stamp using the exact geometry for its type:
    - 'triangle': Inverted triangle for Universes Beyond cards (flat top, downward pointing apex).
    - 'acorn': Acorn contour for Un-set cards (top cap with center stem, tapering rounded body).
    - 'heart': Heart contour for promotional charity cards.
    - 'oval' (default): Standard M15 rounded oval stamp.
    """
    fill_color = (*bg_color, 255)
    st = (stamp_type or "oval").lower()

    if "triangle" in st:
        # Inverted triangle: flat top at y ~= 944*sy, downward apex at x=372*sx, y ~= 988*sy
        tri_poly = [
            (int(334 * sx), int(944 * sy)),
            (int(410 * sx), int(944 * sy)),
            (int(372 * sx), int(988 * sy)),
        ]
        draw.polygon(tri_poly, fill=fill_color)
    elif "acorn" in st:
        # Acorn: Cap with center stem and tapering rounded nut
        acorn_poly = [
            (int(369 * sx), int(941 * sy)),
            (int(375 * sx), int(941 * sy)),
            (int(375 * sx), int(945 * sy)),
            (int(408 * sx), int(948 * sy)),
            (int(411 * sx), int(956 * sy)),
            (int(402 * sx), int(962 * sy)),
            (int(388 * sx), int(978 * sy)),
            (int(372 * sx), int(988 * sy)),
            (int(356 * sx), int(978 * sy)),
            (int(342 * sx), int(962 * sy)),
            (int(333 * sx), int(956 * sy)),
            (int(336 * sx), int(948 * sy)),
            (int(369 * sx), int(945 * sy)),
        ]
        draw.polygon(acorn_poly, fill=fill_color)
    elif "heart" in st:
        heart_poly = [
            (int(372 * sx), int(952 * sy)),
            (int(390 * sx), int(944 * sy)),
            (int(408 * sx), int(950 * sy)),
            (int(410 * sx), int(962 * sy)),
            (int(372 * sx), int(987 * sy)),
            (int(334 * sx), int(962 * sy)),
            (int(336 * sx), int(950 * sy)),
            (int(354 * sx), int(944 * sy)),
        ]
        draw.polygon(heart_poly, fill=fill_color)
    else:
        # Standard oval stamp (M15)
        pad_x = max(1, int(2 * sx))
        pad_y = max(1, int(2 * sy))
        holo_ellipse = [holo_box[0] - pad_x, holo_box[1] - pad_y, holo_box[2] + pad_x, holo_box[3] + pad_y]
        draw.ellipse(holo_ellipse, fill=fill_color)


def clean_card_corner_artifacts(
    card_img: Image.Image,
    bg_color: Tuple[int, int, int],
    sx: float,
    sy: float,
) -> Image.Image:
    """
    Cleans scanner crop marks, registration ticks, and white corner artifacts
    from the 4 outer corner margins of the card frame, replacing them with bg_color.
    """
    w, h = card_img.size
    img_work = card_img.convert("RGBA").copy()
    fill_col = (*bg_color, 255)

    corner_r = int(32 * sx)
    c_w = int(55 * sx)
    c_h = int(55 * sy)

    corners = [
        # (name, x_range, y_range, orig_x, orig_y)
        ("TL", range(0, c_w), range(0, c_h), 0, 0),
        ("TR", range(w - c_w, w), range(0, c_h), w, 0),
        ("BL", range(0, c_w), range(h - c_h, h), 0, h),
        ("BR", range(w - c_w, w), range(h - c_h, h), w, h),
    ]

    bg_brightness = sum(bg_color[:3]) / 3.0
    for name, xr, yr, orig_x, orig_y in corners:
        arc_cx = corner_r if orig_x == 0 else (w - corner_r)
        arc_cy = corner_r if orig_y == 0 else (h - corner_r)
        for y in yr:
            for x in xr:
                in_corner_quad = (x < corner_r if orig_x == 0 else x >= w - corner_r) and \
                                 (y < corner_r if orig_y == 0 else y >= h - corner_r)

                if in_corner_quad:
                    dist_to_center = ((x - arc_cx)**2 + (y - arc_cy)**2)**0.5
                    # If outside the rounded card arc:
                    if dist_to_center > corner_r - 1:
                        img_work.putpixel((x, y), fill_col)
                        continue

                # Also check for stray white/light crop lines in the outer 28px border margin
                in_outer_margin = (
                    x < int(28 * sx) or x >= w - int(28 * sx) or 
                    y < int(28 * sy) or y >= h - int(28 * sy)
                )
                if in_outer_margin:
                    p = img_work.getpixel((x, y))
                    p_bright = sum(p[:3]) / 3.0
                    # If significantly brighter than background (e.g. white cut line)
                    if p_bright > max(75, bg_brightness + 40):
                        img_work.putpixel((x, y), fill_col)

    return img_work


def create_proxy_card(
    card_frame_img: Image.Image,
    card_boxes: Optional[Dict[str, Any]] = None,
    target_dpi: int = 800,
    target_width: int = MPC_800DPI_WIDTH,
    target_height: int = MPC_800DPI_HEIGHT,
) -> Image.Image:
    """
    Transforms a high-resolution Scryfall card scan into a print-ready MakePlayingCards proxy:
    1. Removes the copyright, set code, artist, and collector number bar at the bottom,
       matching the underlying card frame background color.
    2. Cleans white corner registration marks and scanner cut artifacts with the background color.
    3. Removes the holofoil security stamp using proper masking geometry (oval, inverted triangle, acorn).
    4. Adds 'PROXY' in bold dark grey Arial font centered in the bottom bar space.
    5. Upscales the image to 800 DPI MakePlayingCards canvas dimensions (2184x2968)
       with 1/8" (100px) bleed margins and AI edge-preserving sharpness filters.
    """
    cw, ch = card_frame_img.size
    sx = cw / 745.0
    sy = ch / 1040.0

    boxes = card_boxes if card_boxes is not None else detect_card_boxes(card_frame_img)

    # Sample underlying background/border color
    bg_color = sample_border_background_color(card_frame_img, sx, sy)
    fill_bg = (*bg_color, 255)

    # Clean corner scanner marks, cut registration lines, and corner artifacts
    card_work = clean_card_corner_artifacts(card_frame_img, bg_color, sx, sy)
    draw = ImageDraw.Draw(card_work)

    # 1. Remove Holofoil Stamp if present with proper geometry
    holo = boxes.get("holo_stamp")
    stamp_type = boxes.get("stamp_type", "oval")

    if not holo and not boxes.get("is_borderless"):
        # Probe center-bottom region for metallic/silver security stamp
        probe_x = int(372 * sx)
        probe_y = int(965 * sy)
        try:
            p = card_frame_img.getpixel((probe_x, probe_y))
            if sum(p[:3]) / 3.0 > 75:
                holo = (int(336 * sx), int(946 * sy), int(408 * sx), int(984 * sy))
        except Exception:
            pass

    if holo:
        mask_holo_stamp(draw, stamp_type, holo, bg_color, sx, sy)

    # 2. Remove Copyright / Set Number / Artist bar at the bottom with matching background color
    stat_box = boxes.get("stat_box")
    stat_poly = boxes.get("stat_polygon")

    bar_bottom = int(1032 * sy)
    bar_left = int(30 * sx)
    bar_right = int(715 * sx)

    if stat_box or stat_poly:
        stat_left = stat_box[0] if stat_box else (min(pt[0] for pt in stat_poly) if stat_poly else int(560 * sx))
        stat_bottom = stat_box[3] if stat_box else (max(pt[1] for pt in stat_poly) if stat_poly else int(984 * sy))
        # Left of stat box: blackout from below rules box (~968*sy) down to bottom
        draw.rectangle([bar_left, int(968 * sy), stat_left, bar_bottom], fill=fill_bg)
        # Below stat box across full width: blackout down to bottom
        draw.rectangle([bar_left, max(int(978 * sy), stat_bottom), bar_right, bar_bottom], fill=fill_bg)
    else:
        # Full width blackout below rules box
        draw.rectangle([bar_left, int(968 * sy), bar_right, bar_bottom], fill=fill_bg)

    # 3. Add 'PROXY' text in bold Arial font, dark grey color
    font_size_card = max(14, int(20 * sy))
    font_card = get_bold_arial_font(font_size_card)

    text = "PROXY"
    dark_grey = (120, 120, 120, 255)

    try:
        bbox = draw.textbbox((0, 0), text, font=font_card)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw = int(font_size_card * 3.5)
        th = font_size_card

    bar_mid_y = int(998 * sy)
    text_x = (cw - tw) // 2
    text_y = bar_mid_y - th // 2 - (bbox[1] if 'bbox' in locals() else 0)
    draw.text((text_x, text_y), text, fill=dark_grey, font=font_card)

    # 4. Upscale image to MakePlayingCards 800 DPI dimensions with 1/8" bleed margin
    # Physical card cut dimensions: 1984 x 2768 (at 800 DPI)
    base_card_w = int(target_width * (MPC_CUT_WIDTH / MPC_800DPI_WIDTH))
    base_card_h = int(target_height * (MPC_CUT_HEIGHT / MPC_800DPI_HEIGHT))

    # Upscale the card frame using high-fidelity Lanczos resampling
    card_upscaled = card_work.resize((base_card_w, base_card_h), Image.Resampling.LANCZOS)

    # Apply AI edge sharpening / unsharp mask filter to maintain crisp typography and art detail
    card_rgb = card_upscaled.convert("RGB")
    card_enhanced = card_rgb.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
    sharpness_enhancer = ImageEnhance.Sharpness(card_enhanced)
    card_enhanced = sharpness_enhancer.enhance(1.10)

    # Render ultra-crisp 'PROXY' text at full 800 DPI target resolution in the bottom bar space
    draw_enhanced = ImageDraw.Draw(card_enhanced)
    font_size_800 = max(36, int(56 * (base_card_h / 2768.0)))
    font_800 = get_bold_arial_font(font_size_800)

    try:
        bbox_800 = draw_enhanced.textbbox((0, 0), text, font=font_800)
        tw_800 = bbox_800[2] - bbox_800[0]
        th_800 = bbox_800[3] - bbox_800[1]
    except Exception:
        tw_800 = int(font_size_800 * 3.5)
        th_800 = font_size_800

    bar_mid_y_800 = int(bar_mid_y * (base_card_h / ch))
    t800_x = (base_card_w - tw_800) // 2
    t800_y = bar_mid_y_800 - th_800 // 2 - (bbox_800[1] if 'bbox_800' in locals() else 0)
    draw_enhanced.text((t800_x, t800_y), text, fill=(120, 120, 120), font=font_800)

    # 5. Place card onto full 2184x2968 canvas with 100px (1/8") bleed margins matching frame color
    ox = (target_width - base_card_w) // 2
    oy = (target_height - base_card_h) // 2

    # Bleed canvas matching card frame border
    canvas = Image.new("RGB", (target_width, target_height), bg_color)
    canvas.paste(card_enhanced, (ox, oy))

    return canvas


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

