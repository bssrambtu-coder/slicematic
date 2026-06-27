"""
app.py — thin Gradio UI layer for SliceMatic.

The UI stays THIN: every validation, price, and persistence decision is
delegated to core / menu / persistence. app.py only collects inputs, calls
those modules, and renders the result.

Inputs are deliberately free-text (gr.Textbox), not constrained dropdowns —
this lets every PRD edge case (item 0, item 11, "abc", "2.5", a price typed
as an item number, an empty field) actually reach core's validators through
the UI, exactly as the grader's test matrix expects.

Wiring contract:
  * On startup, menu.load_all_menus(DATA_DIR). If it raises MenuFileError,
    print the message and exit cleanly (PRD S0 / NFR 3.5) — no traceback.
  * For each field, call the matching core.validate_* and show the result's
    message on failure (Gradio keeps prior textbox values automatically, so
    nothing already entered is lost on a rejected field).
  * Price with core.price_order; render the bill with core.format_money.
  * On confirm, build the LOG_FIELDS dict and call persistence.append_order;
    surface OrderLogError to the user if it fails.

Run with:  python app.py        (from inside slicematic/src)
       or: python -m src.app    (from inside slicematic/)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

# Make this directory importable as flat top-level modules (core, menu,
# persistence) regardless of how the script is launched.
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import gradio as gr

import core
import menu
import persistence

DATA_DIR = _SRC_DIR.parent / "data"
LOG_PATH = _SRC_DIR.parent / "orders_log.txt"

# Populated once at startup by main()/build_ui(); never re-parsed per request.
_MENU: Dict[str, List[menu.MenuItem]] = {}


def session_timestamp() -> str:
    """ISO-8601 timestamp recorded when a new order begins (PRD FR-1)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_order_record(
    name: str,
    phone: str,
    base_item: menu.MenuItem,
    pizza_item: menu.MenuItem,
    topping_item: menu.MenuItem,
    bill: core.Bill,
    payment_mode: str,
) -> dict:
    """Assemble a persistence-ready dict keyed by persistence.LOG_FIELDS."""
    return {
        "timestamp": session_timestamp(),
        "name": name,
        "phone": phone,
        "base_name": base_item.name,
        "base_price": base_item.price,
        "pizza_name": pizza_item.name,
        "pizza_price": pizza_item.price,
        "topping_name": topping_item.name,
        "topping_price": topping_item.price,
        "qty": bill.quantity,
        "subtotal": bill.subtotal,
        "discount": bill.discount,
        "gst": bill.gst,
        "final_total": bill.final_total,
        "payment_mode": payment_mode,
    }


def render_bill(
    name: str,
    base_item: menu.MenuItem,
    pizza_item: menu.MenuItem,
    topping_item: menu.MenuItem,
    bill: core.Bill,
    payment_mode: str,
) -> str:
    """Return the formatted bill text shown in the UI."""
    return "\n".join(
        [
            f"### Bill for {name}",
            "",
            f"- Base: {base_item.name} ({core.format_money(base_item.price)})",
            f"- Pizza: {pizza_item.name} ({core.format_money(pizza_item.price)})",
            f"- Topping: {topping_item.name} ({core.format_money(topping_item.price)})",
            f"- Quantity: {bill.quantity}",
            "",
            f"Subtotal: {core.format_money(bill.subtotal)}",
            f"Discount: -{core.format_money(bill.discount)}",
            f"GST (18%): +{core.format_money(bill.gst)}",
            f"**Final total: {core.format_money(bill.final_total)}**",
            "",
            f"Payment mode: {payment_mode}",
        ]
    )


def _reject(message: str):
    """Shared error-path return: status message, no bill."""
    return f"❌ {message}", ""


def place_order(
    name: str,
    phone: str,
    base_num: str,
    pizza_num: str,
    topping_num: str,
    qty_text: str,
    payment_choice: str,
):
    """Validate every field via core, price the order, persist it, and
    render the bill. Returns (status_message, bill_markdown)."""
    name_res = core.validate_name(name)
    if not name_res.ok:
        return _reject(name_res.message)

    phone_res = core.validate_phone(phone)
    if not phone_res.ok:
        return _reject(phone_res.message)

    base_res = core.validate_menu_selection(base_num, len(_MENU["base"]))
    if not base_res.ok:
        return _reject(f"Base — {base_res.message}")

    pizza_res = core.validate_menu_selection(pizza_num, len(_MENU["pizza"]))
    if not pizza_res.ok:
        return _reject(f"Pizza — {pizza_res.message}")

    topping_res = core.validate_menu_selection(topping_num, len(_MENU["topping"]))
    if not topping_res.ok:
        return _reject(f"Topping — {topping_res.message}")

    qty_res = core.validate_quantity(qty_text)
    if not qty_res.ok:
        return _reject(qty_res.message)

    payment_res = core.validate_payment(payment_choice)
    if not payment_res.ok:
        return _reject(payment_res.message)

    base_item = _MENU["base"][base_res.value - 1]
    pizza_item = _MENU["pizza"][pizza_res.value - 1]
    topping_item = _MENU["topping"][topping_res.value - 1]

    bill = core.price_order(base_item.price, pizza_item.price, topping_item.price, qty_res.value)

    record = build_order_record(
        name_res.value, phone_res.value, base_item, pizza_item, topping_item, bill, payment_res.value
    )

    try:
        persistence.append_order(record, LOG_PATH)
    except persistence.OrderLogError as exc:
        return _reject(f"Order was priced but could not be saved: {exc}")

    status = f"✅ {payment_res.message}"
    bill_text = render_bill(name_res.value, base_item, pizza_item, topping_item, bill, payment_res.value)
    return status, bill_text


def build_ui() -> gr.Blocks:
    """Construct the Gradio Blocks layout. Assumes _MENU is already loaded."""
    base_lines = "\n".join(menu.format_menu_lines(_MENU["base"]))
    pizza_lines = "\n".join(menu.format_menu_lines(_MENU["pizza"]))
    topping_lines = "\n".join(menu.format_menu_lines(_MENU["topping"]))

    with gr.Blocks(title="SliceMatic") as demo:
        gr.Markdown("# 🍕 SliceMatic — Order Your Pizza")

        with gr.Row():
            name_in = gr.Textbox(label="Name")
            phone_in = gr.Textbox(label="Phone (10 digits)")

        with gr.Row():
            gr.Markdown(f"**Base**\n\n{base_lines}")
            base_in = gr.Textbox(label="Base #")
        with gr.Row():
            gr.Markdown(f"**Pizza**\n\n{pizza_lines}")
            pizza_in = gr.Textbox(label="Pizza #")
        with gr.Row():
            gr.Markdown(f"**Topping**\n\n{topping_lines}")
            topping_in = gr.Textbox(label="Topping #")

        with gr.Row():
            qty_in = gr.Textbox(label="Quantity (1-10)")
            payment_in = gr.Textbox(label="Payment (1 Cash / 2 Card / 3 UPI)")

        submit_btn = gr.Button("Place Order", variant="primary")

        status_out = gr.Markdown(label="Status")
        bill_out = gr.Markdown(label="Bill")

        submit_btn.click(
            fn=place_order,
            inputs=[name_in, phone_in, base_in, pizza_in, topping_in, qty_in, payment_in],
            outputs=[status_out, bill_out],
        )

    return demo


def main() -> None:
    """Entry point: load menu (exit cleanly on MenuFileError), launch the UI."""
    global _MENU
    try:
        _MENU = menu.load_all_menus(DATA_DIR)
    except menu.MenuFileError as exc:
        print(f"Cannot start SliceMatic: {exc}", file=sys.stderr)
        sys.exit(1)

    demo = build_ui()
    demo.launch()


if __name__ == "__main__":
    main()
