"""
app.py — thin Gradio UI layer for SliceMatic.

OWNER: frontend teammate. This is a SKELETON. The UI must stay THIN: every
validation, price, and persistence decision is delegated to core / menu /
persistence. app.py only collects inputs, calls those modules, and renders.

Wiring contract:
  * On startup, menu.load_all_menus(DATA_DIR). If it raises MenuFileError,
    show the message and exit cleanly (PRD S0 / NFR 3.5) — no traceback.
  * For each field, call the matching core.validate_* and show result.message
    on failure (re-prompt the same field, keep prior valid input — PRD FR-1).
  * Price with core.price_order; render the bill with core.format_money and a
    ₹ symbol, 2 dp (PRD 3.6).
  * On confirm, build the LOG_FIELDS dict and call persistence.append_order;
    surface OrderLogError to the user if it fails.

Keep ALL business rules in core — do not re-derive discount/GST/validation here.
Run with:  python -m src.app   (from the slicematic/ directory)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# import gradio as gr            # uncomment when implementing the UI
# from . import core, menu, persistence   # or: import core, menu, persistence

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def session_timestamp() -> str:
    """ISO-8601 timestamp recorded when a new order begins (PRD FR-1)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_order_record(*args, **kwargs) -> dict:
    """Assemble a persistence-ready dict keyed by persistence.LOG_FIELDS.

    Pulls names/prices from the chosen MenuItems and the core.Bill fields
    (subtotal/discount/gst/final_total) plus timestamp, name, phone, qty,
    payment_mode. Implement once the UI inputs are wired.
    """
    raise NotImplementedError


def render_bill(*args, **kwargs) -> str:
    """Return the formatted bill text shown in the UI (uses core.format_money)."""
    raise NotImplementedError


def build_ui():
    """Construct and return the Gradio Blocks/Interface. Implement the layout
    and event handlers here; load the menu first and fail gracefully."""
    raise NotImplementedError


def main() -> None:
    """Entry point: load menu (exit cleanly on MenuFileError), launch the UI."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
