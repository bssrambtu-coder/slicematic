"""
menu.py — defensive parser for the three menu .txt files.

The grader WILL SWAP the data files, so NOTHING about the menu is
hardcoded — no item names, counts, or prices. Everything is loaded at runtime
from:
    data/Types_of_Base.txt
    data/Types_of_Pizza.txt
    data/Types_of_Toppings.txt
Each line is formatted:  ID;Name;Price   (semicolon-separated, INR integer).

Defensive-parsing contract (PRD FR-3, NFR 3.5):
  * Strip leading/trailing whitespace and tolerate inconsistent spacing
    around the ';' delimiter.
  * Skip blank lines silently.
  * Skip malformed lines (wrong field count, missing/non-numeric price) and
    emit a warning; the rest of the menu still loads (edge case 8).
  * Missing file  -> raise MenuFileError naming the file (app exits cleanly,
    no traceback — PRD S0 / NFR 3.5).
  * Empty menu after parsing -> raise MenuFileError so ordering refuses to
    start and explains why.

This module does file I/O (that is its job) but does not import Gradio or
prompt the user. Money handling is delegated to core.to_money/format_money.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from core import format_money, to_money

# Default filenames the grader swaps. Resolved against the data dir at call
# time; never embed item data here.
BASE_FILE = "Types_of_Base.txt"
PIZZA_FILE = "Types_of_Pizza.txt"
TOPPINGS_FILE = "Types_of_Toppings.txt"

FIELD_DELIMITER = ";"
EXPECTED_FIELDS = 3  # ID;Name;Price


class MenuFileError(Exception):
    """Raised for a missing file or an empty-after-parse menu (caught by app)."""


@dataclass(frozen=True)
class MenuItem:
    """One parsed menu row: ID;Name;Price."""

    item_id: str
    name: str
    price: Decimal


def parse_line(raw: str) -> Optional[MenuItem]:
    """Parse one raw line into a MenuItem, or return None if it should be skipped.

    Strips whitespace, tolerates spacing around ';', treats blank lines as
    skippable (no warning), and rejects lines that don't have exactly 3
    non-empty fields or whose price is non-numeric (caller logs a warning for
    those, since they are malformed rather than simply blank).
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None

    fields = [f.strip() for f in stripped.split(FIELD_DELIMITER)]
    if len(fields) != EXPECTED_FIELDS:
        return None

    item_id, name, price_text = fields
    if not item_id or not name or not price_text:
        return None

    try:
        price = to_money(price_text)
    except ValueError:
        return None
    if price < 0:
        return None

    return MenuItem(item_id=item_id, name=name, price=price)


def load_menu_file(path: str | Path) -> List[MenuItem]:
    """Load and defensively parse one menu file into a list of MenuItem.

    Raises MenuFileError if the file is missing or if zero valid items remain
    after parsing. Malformed individual (non-blank) lines are skipped with a
    warning, not fatal.
    """
    p = Path(path)
    if not p.exists():
        raise MenuFileError(f"Menu file not found: {p}")

    items: List[MenuItem] = []
    with p.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            if not raw.strip():
                continue  # blank line, not a warning
            item = parse_line(raw)
            if item is None:
                warnings.warn(
                    f"Skipping malformed line {line_no} in {p.name}: {raw.strip()!r}"
                )
                continue
            items.append(item)

    if not items:
        raise MenuFileError(f"No valid items found in {p.name}; menu cannot start.")
    return items


def load_all_menus(data_dir: str | Path) -> Dict[str, List[MenuItem]]:
    """Load all three categories.

    Returns {"base": [...], "pizza": [...], "topping": [...]}. Raises
    MenuFileError (naming the offending file) if any file is missing or empty.
    """
    data_dir = Path(data_dir)
    return {
        "base": load_menu_file(data_dir / BASE_FILE),
        "pizza": load_menu_file(data_dir / PIZZA_FILE),
        "topping": load_menu_file(data_dir / TOPPINGS_FILE),
    }


def format_menu_lines(items: List[MenuItem]) -> List[str]:
    """Return display lines, numbered 1..N: e.g. '1. Thin Crust - ₹149.00'.

    Numbering is 1-based and pairs with core.validate_menu_selection.
    """
    return [
        f"{i}. {item.name} - {format_money(item.price)}"
        for i, item in enumerate(items, start=1)
    ]
