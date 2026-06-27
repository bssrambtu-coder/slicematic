"""
menu.py — defensive parser for the three menu .txt files.

OWNER: data-model teammate. This is a SKELETON — signatures + contract only.
Implement the bodies (replace `raise NotImplementedError`) and make
tests/test_menu.py pass.

The grader WILL SWAP the data files, so NOTHING about the menu may be
hardcoded — no item names, counts, or prices. Everything is loaded at runtime
from:
    data/Types_of_Base.txt
    data/Types_of_Pizza.txt
    data/Types_of_Toppings.txt
Each line is formatted:  ID;Name;Price   (semicolon-separated, INR integer).

Defensive-parsing contract (PRD FR-3, NFR 3.5):
  * Strip leading/trailing whitespace and tolerate inconsistent spacing
    around the ';' delimiter.
  * Skip blank lines.
  * Skip/flag malformed lines (wrong field count, missing/non-numeric price)
    with a clear warning; the rest of the menu still loads (edge case 8).
  * Validate that price is numeric; route prices through core.to_money.
  * Missing file  -> raise MenuFileError naming the file (app exits cleanly,
    no traceback — PRD S0 / NFR 3.5).
  * Empty menu after parsing -> raise MenuFileError so ordering refuses to
    start and explains why.

This module MAY do file I/O (that is its job) but MUST NOT import Gradio or
prompt the user. Keep money handling delegated to core.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import List


# Default filenames the grader swaps. Resolve against the data dir at call time;
# never embed item data here.
BASE_FILE = "Types_of_Base.txt"
PIZZA_FILE = "Types_of_Pizza.txt"
TOPPINGS_FILE = "Types_of_Toppings.txt"

FIELD_DELIMITER = ";"


class MenuFileError(Exception):
    """Raised for a missing file or an empty-after-parse menu (caught by app)."""


@dataclass(frozen=True)
class MenuItem:
    """One parsed menu row: ID;Name;Price."""

    item_id: str
    name: str
    price: Decimal


def parse_line(raw: str) -> MenuItem | None:
    """Parse one raw line into a MenuItem, or return None if it should be skipped.

    Must: strip whitespace, tolerate spacing around ';', skip blanks, and
    reject lines that don't have exactly 3 fields or whose price is non-numeric
    (return None for those — caller logs the warning).
    """
    raise NotImplementedError


def load_menu_file(path: str | Path) -> List[MenuItem]:
    """Load and defensively parse one menu file into a list of MenuItem.

    Raises MenuFileError if the file is missing or if zero valid items remain
    after parsing. Malformed individual lines are skipped (with a warning),
    not fatal.
    """
    raise NotImplementedError


def load_all_menus(data_dir: str | Path) -> dict[str, List[MenuItem]]:
    """Load all three categories.

    Returns {"base": [...], "pizza": [...], "topping": [...]}. Raises
    MenuFileError (naming the offending file) if any file is missing or empty.
    """
    raise NotImplementedError


def format_menu_lines(items: List[MenuItem]) -> List[str]:
    """Return display lines, numbered 1..N: e.g. '1. Thin Crust — ₹149.00'.

    Numbering is 1-based and pairs with core.validate_menu_selection. Uses
    core.format_money for the INR rendering.
    """
    raise NotImplementedError
