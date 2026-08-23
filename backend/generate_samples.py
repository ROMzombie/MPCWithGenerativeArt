"""
Sample generation script and documentation builder for standard MTG card frame variants.

Generates 800 DPI print-ready MakePlayingCards images and web thumbnails for each
supported card layout type/variant, and renders docs/samples/README.md.
"""

import os
import sys
import asyncio
from pathlib import Path

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import List, Dict, Any, Optional
from PIL import Image

from backend.scryfall import scryfall_client
from backend.generator import MockProceduralGenerator
from backend.compositor import detect_card_boxes, composite_card, save_card_outputs

DOCS_DIR = Path("docs/samples")
DOCS_IMAGES_DIR = DOCS_DIR / "images"

# Comprehensive list of standard MTG card variants (excluding full-art/secret lair textbox modifiers)
SAMPLE_CARD_VARIANTS: List[Dict[str, Any]] = [
    {
        "id": "creature_standard",
        "set_code": "fdn",
        "collector_number": "227",
        "card_name": "Llanowar Elves",
        "category": "Standard Creature",
        "description": "Standard non-legendary creature frame with Power/Toughness badge in bottom-right corner.",
        "prompt": "Vibrant ancient elven druid channeled with glowing emerald forest magic in sunlit grove",
        "key_elements": [
            "Standard rounded title pill",
            "Type line box",
            "Text box with rules & flavor text",
            "Bottom-right Power/Toughness stat box (1/1)",
        ],
    },
    {
        "id": "creature_legendary",
        "set_code": "mbc",
        "collector_number": "1",
        "card_name": "Ekthi, Contaminator Priest",
        "category": "Legendary Creature",
        "description": "Legendary creature frame with rounded title pill, Power/Toughness box, and rare holographic security stamp.",
        "prompt": "Phyrexian mechanical horror priest with bio-mechanical armor and porcelain skin",
        "key_elements": [
            "Rounded title pill with mana cost",
            "Type line box",
            "Rules box with full flavor text",
            "Bottom-center holographic security stamp oval",
            "Bottom-right Power/Toughness stat box (3/3)",
        ],
    },
    {
        "id": "artifact_equipment",
        "set_code": "drc",
        "collector_number": "16",
        "card_name": "Adaptive Omnitool",
        "category": "Artifact / Equipment",
        "description": "Standard artifact frame without Power/Toughness box, featuring full ability rules text, equip cost, and bottom frame crest.",
        "prompt": "Ancient intricate glowing artifact device with neon circuits and chrome plating",
        "key_elements": [
            "Metallic artifact title pill",
            "Type line box",
            "Complete text box with 'Equip 3' cost line",
            "Bottom center frame crest",
        ],
    },
    {
        "id": "artifact_creature",
        "set_code": "cmm",
        "collector_number": "393",
        "card_name": "Solemn Simulacrum",
        "category": "Artifact Creature",
        "description": "Artifact creature frame combining metallic border treatment with bottom-right Power/Toughness box and rare holographic stamp.",
        "prompt": "Melancholy ornate clockwork brass automaton walking through misty ancient ruins",
        "key_elements": [
            "Artifact title pill",
            "Artifact Creature type line",
            "Rules text box with triggered abilities",
            "Bottom-center holographic security stamp oval",
            "Bottom-right Power/Toughness stat box (2/2)",
        ],
    },
    {
        "id": "enchantment_global",
        "set_code": "rna",
        "collector_number": "22",
        "card_name": "Smothering Tithe",
        "category": "Enchantment (Global)",
        "description": "Non-creature enchantment card layout with full rules box and rare holofoil stamp.",
        "prompt": "Grand gilded cathedral vault with floating golden coins and ornate celestial stained glass",
        "key_elements": [
            "White enchantment title pill",
            "Enchantment type line",
            "Rules text box with triggered ability",
            "Bottom center holographic security stamp oval",
        ],
    },
    {
        "id": "enchantment_aura",
        "set_code": "2x2",
        "collector_number": "156",
        "card_name": "Rancor",
        "category": "Enchantment (Aura)",
        "description": "Aura enchantment frame with target enchantment type line and recursive aura return rules text.",
        "prompt": "Feral glowing primal beast spirit roaring with fierce green ethereal energy",
        "key_elements": [
            "Green enchantment title pill",
            "Enchantment — Aura type line",
            "Rules text box with static and death trigger abilities",
            "Bottom center frame crest",
        ],
    },
    {
        "id": "enchantment_saga",
        "set_code": "thb",
        "collector_number": "13",
        "card_name": "Elspeth Conquers Death",
        "category": "Enchantment (Saga)",
        "description": "Saga enchantment frame with left-side vertical chapter ability column, right-side art column, bottom type line, and holofoil stamp.",
        "prompt": "Ornate mythological mosaic artwork depicting victorious celestial knight banishing shadows",
        "key_elements": [
            "Top title pill with 3WW mana cost",
            "Left vertical chapter column with Roman numeral badges (I, II, III)",
            "Bottom type line pill (Enchantment — Saga)",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "enchantment_class",
        "set_code": "afr",
        "collector_number": "29",
        "card_name": "Paladin Class",
        "category": "Enchantment (Class)",
        "description": "Class enchantment frame with left-side vertical art column, right-side multi-tier level ability boxes, and bottom type line.",
        "prompt": "Heroic holy warrior shining plate armor helmet bathed in divine dawn sunlight",
        "key_elements": [
            "Top title pill with W mana cost",
            "Right vertical level advancement rules boxes (Level 2, Level 3)",
            "Bottom type line pill (Enchantment — Class)",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "enchantment_case",
        "set_code": "mkm",
        "collector_number": "114",
        "card_name": "Case of the Crimson Pulse",
        "category": "Enchantment (Case)",
        "description": "Case enchantment frame with left-side art window, right-side progression rules box ('To solve', 'Solved'), and bottom type line.",
        "prompt": "Mysterious detective investigation map in victorian steampunk manor glowing with neon lines",
        "key_elements": [
            "Top title pill with 2R mana cost",
            "Right vertical Case progression rules box (Initial, To solve, Solved)",
            "Bottom type line pill (Enchantment — Case)",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "enchantment_room",
        "set_code": "dsk",
        "collector_number": "4",
        "card_name": "Dollmaker's Shop // Porcelain Gallery",
        "category": "Enchantment (Room)",
        "description": "Room enchantment frame with dual split door layouts (left and right doors), center door-unlock banner, and holofoil stamp.",
        "prompt": "Eerie haunted chamber lined with cracked antique porcelain dolls and moonlit shadows",
        "key_elements": [
            "Dual title pills (Dollmaker's Shop 1W and Porcelain Gallery 4WW)",
            "Center door unlocking banner (Enchantment — Room)",
            "Dual independent door rules text boxes",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "instant",
        "set_code": "mh2",
        "collector_number": "267",
        "card_name": "Counterspell",
        "category": "Instant",
        "description": "Standard instant spell layout featuring clean text box with rules and flavor text.",
        "prompt": "Mystic glowing sapphire spell runes dispersing swirling temporal energy rift in cosmos",
        "key_elements": [
            "Instant title pill with UU mana cost",
            "Instant type line",
            "Rules text box with centered flavor text",
            "Bottom center frame crest",
        ],
    },
    {
        "id": "sorcery",
        "set_code": "cmm",
        "collector_number": "70",
        "card_name": "Wrath of God",
        "category": "Sorcery",
        "description": "Standard sorcery spell layout with full rules box, flavor text, and rare holofoil stamp.",
        "prompt": "Cataclysmic pillar of blinding divine light descending from heavenly clouds annihilating battlefield",
        "key_elements": [
            "Sorcery title pill with 2WW mana cost",
            "Sorcery type line",
            "Rules text box with board wipe effect and flavor text",
            "Bottom center holographic security stamp oval",
        ],
    },
    {
        "id": "battle_siege",
        "set_code": "mom",
        "collector_number": "22",
        "card_name": "Invasion of Gobakhan",
        "category": "Battle (Siege)",
        "description": "Battle siege layout featuring horizontal frame structure, left-side title column, rules box, type line, and defense counter badge.",
        "prompt": "Epic sci-fi planetary invasion with celestial shield barrier deflecting particle orbital bombardments",
        "key_elements": [
            "Left vertical title column with 1W mana cost",
            "Battle — Siege type line box",
            "Rules text box with trigger effects",
            "Top-right polygonal Defense counter badge (3)",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "land_nonbasic",
        "set_code": "cmm",
        "collector_number": "420",
        "card_name": "Command Tower",
        "category": "Land (Non-Basic)",
        "description": "Standard non-basic land frame without mana cost, with full rules box and rare holofoil stamp.",
        "prompt": "Monolithic towering obsidian citadel glowing with prismatic planar beacons over mystical landscape",
        "key_elements": [
            "Land title pill without mana cost",
            "Land type line",
            "Rules text box with mana ability",
            "Bottom center holographic security stamp oval",
        ],
    },
    {
        "id": "land_basic",
        "set_code": "fdn",
        "collector_number": "276",
        "card_name": "Island",
        "category": "Land (Basic)",
        "description": "Standard basic land layout featuring centered large mana symbol watermark in text box.",
        "prompt": "Serene tropical azure island with crystalline lagoons and lush glowing palm groves",
        "key_elements": [
            "Basic Land title pill",
            "Basic Land — Island type line",
            "Text box with basic mana tap ability",
            "Bottom center frame crest",
        ],
    },
    {
        "id": "planeswalker",
        "set_code": "ph21",
        "collector_number": "3",
        "card_name": "Byode, Inverse Sun",
        "category": "Planeswalker",
        "description": "Planeswalker layout featuring multi-loyalty ability text box with irregular polygonal loyalty shield at bottom-right.",
        "prompt": "Celestial radiant universewalker deity floating among cosmic star clusters and solar nebulae",
        "key_elements": [
            "Planeswalker title pill",
            "Legendary Planeswalker type line",
            "Loyalty ability rules box",
            "8-point polygonal starting loyalty shield (3)",
        ],
    },
    {
        "id": "vehicle",
        "set_code": "kld",
        "collector_number": "235",
        "card_name": "Smuggler's Copter",
        "category": "Vehicle / Spacecraft",
        "description": "Vehicle artifact frame with crew ability rules text and Power/Toughness box.",
        "prompt": "Sleek brass aetherpunk rotorcraft soaring over sunlit spires and cloudscapes",
        "key_elements": [
            "Artifact vehicle title pill",
            "Artifact — Vehicle type line",
            "Rules text box with Crew ability",
            "Bottom-right Power/Toughness box (3/3)",
        ],
    },
    {
        "id": "station_1_badge",
        "set_code": "eoe",
        "collector_number": "250",
        "card_name": "Adagia, Windswept Bastion",
        "category": "Station Card (1 Circle Badge)",
        "description": "Station card featuring a single circular Station activation badge protruding from the left rules box border.",
        "prompt": "Massive ancient orbital planetary fortress with glowing ring reactors above stormy clouds",
        "key_elements": [
            "Land title pill",
            "Land — Planet type line",
            "Targeted circular Station badge (12+) on left margin",
            "Rules text box with station mechanics",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "station_2_badges",
        "set_code": "eoe",
        "collector_number": "238",
        "card_name": "Dawnsire, Sunstar Dreadnought",
        "category": "Station Card (2 Circle Badges)",
        "description": "Legendary Spacecraft Station card featuring two edge-protruding Station badges (10+ and 20+) and Power/Toughness box.",
        "prompt": "Colossal golden starship dreadnought flying through supernova plasma flare",
        "key_elements": [
            "Rounded title pill with mana cost",
            "Legendary Artifact — Spacecraft type line",
            "Dual targeted circular Station badges (10+ and 20+) on left margin",
            "Rules text box with Station levels",
            "Bottom-right Power/Toughness box (20/20)",
            "Bottom holographic security stamp oval",
        ],
    },
    {
        "id": "station_3_badges",
        "set_code": "eoe",
        "collector_number": "239",
        "card_name": "Entropic Battlecruiser",
        "category": "Station Card (3 Circle Badges)",
        "description": "Spacecraft Station card featuring three edge-protruding Station badges (8+, 14+, and 20+) and Power/Toughness box.",
        "prompt": "Ominous dark matter battlecruiser charging catastrophic vortex beams across nebulas",
        "key_elements": [
            "Artifact vehicle title pill",
            "Artifact — Spacecraft type line",
            "Triple targeted circular Station badges (8+, 14+, and 20+) on left margin",
            "Rules text box with 3 station ability tiers",
            "Bottom-right Power/Toughness box (10/10)",
            "Bottom holographic security stamp oval",
        ],
    },
]


async def generate_all_samples(
    output_dir: Path = DOCS_IMAGES_DIR,
    regenerate: bool = True,
) -> List[Dict[str, Any]]:
    """
    Generates print-ready 800 DPI cards and web previews for all card variants,
    saving them into docs/samples/images/.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    generator = MockProceduralGenerator()
    results = []

    for variant in SAMPLE_CARD_VARIANTS:
        v_id = variant["id"]
        s = variant["set_code"]
        c = variant["collector_number"]
        name = variant["card_name"]
        prompt = variant["prompt"]

        thumb_file = output_dir / f"{v_id}_thumb.jpg"
        png_file = output_dir / f"{v_id}_800dpi.png"

        # Fetch card data from Scryfall cache
        card_data = await scryfall_client.get_card(s, c, name)
        card_frame_img = Image.open(card_data.cached_png_path).convert("RGB")
        art_crop_img = Image.open(card_data.cached_art_path).convert("RGB") if card_data.cached_art_path else None

        # Detect card bounding boxes
        card_boxes = detect_card_boxes(
            card_img=card_frame_img,
            art_crop_img=art_crop_img,
            type_line=card_data.type_line,
            flavor_name=card_data.flavor_name,
            border_color=card_data.border_color,
            frame_effects=card_data.frame_effects,
            layout=card_data.layout,
            full_art=card_data.full_art,
        )

        # Generate custom background art
        art_img = await generator.generate_art(
            prompt=prompt,
            card_name=name,
            target_width=2184,
            target_height=2968,
            colors=card_data.colors,
        )

        # Composite print-ready 800 DPI card
        composite_800dpi = composite_card(
            card_frame_img=card_frame_img,
            generated_art_img=art_img,
            card_boxes=card_boxes,
            target_dpi=800,
        )

        # Save 800 DPI PNG
        composite_800dpi.save(
            png_file,
            format="PNG",
            dpi=(800, 800),
            compress_level=6,
        )

        # Save web preview thumbnail (480px width)
        thumb_w = 480
        thumb_h = int(composite_800dpi.height * (thumb_w / composite_800dpi.width))
        thumb_img = composite_800dpi.resize((thumb_w, thumb_h), Image.Resampling.BICUBIC).convert("RGB")
        thumb_img.save(thumb_file, format="JPEG", quality=90, optimize=True)

        res_item = dict(variant)
        res_item["thumb_rel_path"] = f"images/{v_id}_thumb.jpg"
        res_item["png_rel_path"] = f"images/{v_id}_800dpi.png"
        res_item["thumb_abs_path"] = str(thumb_file)
        res_item["png_abs_path"] = str(png_file)
        results.append(res_item)
        print(f"[Sample Generated] {variant['category']}: {name} -> {thumb_file}")

    return results


def build_samples_readme(
    samples: List[Dict[str, Any]],
    output_readme: Path = DOCS_DIR / "README.md",
) -> str:
    """
    Renders docs/samples/README.md containing embedded images, descriptions,
    and mechanical details for each standard card variant.
    """
    output_readme.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# MTG Card Layout Variants & Sample Gallery",
        "",
        "This document showcases full-art generative card compositing across all supported **standard Magic: The Gathering card layouts and frame variants**.",
        "",
        "> [!NOTE]",
        "> These samples cover all structural card frame variants (standard creatures, legendary crowns, planeswalkers, battles, vehicles, and multi-tier station cards).",
        "> They do not include non-standard full-art or Secret Lair promotional treatments that alter text box geometries.",
        "",
        "## Table of Contents",
        "",
    ]

    for item in samples:
        anchor = item["category"].lower().replace(" ", "-").replace("(", "").replace(")", "").replace("—", "-").replace("/", "")
        lines.append(f"- [{item['category']} — {item['card_name']}](#{anchor})")

    lines.extend([
        "",
        "---",
        "",
        "## Sample Card Gallery",
        "",
    ])

    for item in samples:
        thumb_rel = item.get("thumb_rel_path", f"images/{item['id']}_thumb.jpg")
        lines.extend([
            f"### {item['category']}",
            "",
            f"**Card:** `{item['card_name']}` (`{item['set_code'].upper()}` #{item['collector_number']})  ",
            f"**Description:** {item['description']}  ",
            f"**Sample Prompt:** *\"{item['prompt']}\"*",
            "",
            f"<p align=\"center\">",
            f"  <img src=\"{thumb_rel}\" alt=\"{item['card_name']} Sample\" width=\"400\" />",
            f"</p>",
            "",
            "**Key Frame Elements Preserved:**",
        ])
        for elem in item["key_elements"]:
            lines.append(f"- {elem}")
        lines.extend([
            "",
            "---",
            "",
        ])

    lines.extend([
        "## Regenerating Samples",
        "",
        "To regenerate all sample card outputs and update the documentation gallery, execute:",
        "",
        "```bash",
        "python backend/generate_samples.py",
        "```",
        "",
        "To verify all sample variants via automated unit testing:",
        "",
        "```bash",
        "python -m unittest tests/test_samples.py",
        "```",
        "",
    ])

    content = "\n".join(lines)
    output_readme.write_text(content, encoding="utf-8")
    print(f"[Documentation] Successfully wrote documentation to {output_readme}")
    return content


async def main():
    print("[Samples] Starting sample card generation for documentation...")
    samples = await generate_all_samples()
    build_samples_readme(samples)
    print("[Samples] All sample cards and documentation successfully built!")


if __name__ == "__main__":
    asyncio.run(main())
