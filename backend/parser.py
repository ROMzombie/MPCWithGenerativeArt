"""Deck file parser and format validator for MPCWithGenerativeArt."""

import re
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field


class CardItem(BaseModel):
    id: str = Field(..., description="Unique ID for this card entry in the session")
    line_number: int = Field(..., description="Line number in the input file (1-indexed)")
    copies: int = Field(1, description="Number of copies of the card to print")
    card_name: str = Field(..., description="The name of the card")
    set_code: str = Field(..., description="The set code (e.g. PH21, SLD, MH3)")
    collector_number: str = Field(..., description="The collector number (e.g. 3, 2695, 2189)")
    prompt: str = Field(..., description="The prompt used for generative card art")
    status: str = Field("queued", description="Status: queued, fetching, generating, compositing, ready, error")
    status_message: str = Field("", description="Detailed progress or error message")
    image_url: Optional[str] = Field(None, description="URL or relative path to the generated 800 DPI card image")
    scryfall_id: Optional[str] = Field(None, description="Scryfall card ID")
    scryfall_png_url: Optional[str] = Field(None, description="Original Scryfall card PNG URL")
    scryfall_art_url: Optional[str] = Field(None, description="Original Scryfall art crop URL")
    art_box: Optional[Tuple[int, int, int, int]] = Field(None, description="Detected bounding box for art (x1, y1, x2, y2)")
    created_at: Optional[str] = None


class ParseResult(BaseModel):
    valid: bool
    cards: List[CardItem] = []
    errors: List[str] = []
    total_copies: int = 0


# Regex pattern to match: Copies CardName (set) CollectorNumber\tprompt
# Also supports multiple spaces if tab was replaced by spaces
LINE_PATTERN = re.compile(
    r"^\s*(?P<copies>\d+)\s+(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9_\-]+)\)\s+(?P<number>[A-Za-z0-9_\-\*]+)(?:[\t]+|\s{2,}|\s*[\t]\s*)(?P<prompt>.+?)\s*$"
)

# Alternative regex if single tab separates card info and prompt
TAB_SPLIT_PATTERN = re.compile(
    r"^\s*(?P<copies>\d+)\s+(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9_\-]+)\)\s+(?P<number>[A-Za-z0-9_\-\*]+)\s*$"
)


def parse_deck_text(text: str) -> ParseResult:
    """
    Parses deck lines formatted as:
    Copies CardName (set) CollectorNumber\tprompt

    Returns a ParseResult with structured CardItems or validation errors.
    """
    lines = text.strip().splitlines()
    cards: List[CardItem] = []
    errors: List[str] = []
    total_copies = 0

    if not text.strip():
        return ParseResult(valid=False, cards=[], errors=["Deck input is empty. Please provide at least one card line."], total_copies=0)

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            # Skip empty lines and comment lines
            continue

        # Try standard pattern first
        match = LINE_PATTERN.match(line)
        if match:
            copies = int(match.group("copies"))
            card_name = match.group("name").strip()
            set_code = match.group("set").strip().upper()
            collector_number = match.group("number").strip()
            prompt = match.group("prompt").strip()

            if copies <= 0:
                errors.append(f"Line {idx}: Number of copies must be at least 1 (found {copies})")
                continue

            if not prompt:
                errors.append(f"Line {idx}: Missing prompt for card '{card_name}'")
                continue

            card_id = f"card_{idx}_{set_code}_{collector_number}".lower()
            cards.append(
                CardItem(
                    id=card_id,
                    line_number=idx,
                    copies=copies,
                    card_name=card_name,
                    set_code=set_code,
                    collector_number=collector_number,
                    prompt=prompt,
                )
            )
            total_copies += copies
            continue

        # Check if line contains a tab separator
        if "\t" in line:
            parts = line.split("\t", 1)
            card_part = parts[0].strip()
            prompt_part = parts[1].strip()

            tab_match = TAB_SPLIT_PATTERN.match(card_part)
            if tab_match:
                copies = int(tab_match.group("copies"))
                card_name = tab_match.group("name").strip()
                set_code = tab_match.group("set").strip().upper()
                collector_number = tab_match.group("number").strip()

                if copies <= 0:
                    errors.append(f"Line {idx}: Number of copies must be at least 1 (found {copies})")
                    continue
                if not prompt_part:
                    errors.append(f"Line {idx}: Missing prompt for card '{card_name}'")
                    continue

                card_id = f"card_{idx}_{set_code}_{collector_number}".lower()
                cards.append(
                    CardItem(
                        id=card_id,
                        line_number=idx,
                        copies=copies,
                        card_name=card_name,
                        set_code=set_code,
                        collector_number=collector_number,
                        prompt=prompt_part,
                    )
                )
                total_copies += copies
                continue

        # If we reached here, the line failed to match the required format
        errors.append(
            f"Line {idx}: Invalid line format '{line}'. Expected format: 'Copies CardName (set) CollectorNumber\\tprompt' (e.g. '1 Byode, Inverse Sun (PH21) 3\\tAn anime girl dressed like a pixie')"
        )

    if errors:
        return ParseResult(valid=False, cards=cards, errors=errors, total_copies=total_copies)

    if not cards:
        return ParseResult(valid=False, cards=[], errors=["No valid card entries found in input."], total_copies=0)

    return ParseResult(valid=True, cards=cards, errors=[], total_copies=total_copies)
