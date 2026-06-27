"""
app.py — SliceMatic Gradio UI (root entry point for Hugging Face Spaces).

Stays THIN: every validation, price, and quota decision is delegated to
src/core.py, src/menu.py, src/persistence.py, src/quota.py. This file only
collects input, calls those modules, and renders the result.

Cart-style ordering flow: a customer can add MULTIPLE base+pizza+topping(s)
combos to one order, each with its own quantity, before checking out once for
the whole order. Toppings are optional (zero, one, or many per combo — there's
an explicit "Skip" as well as "Next" with nothing checked). Discount and GST
apply at the ORDER level (core.price_cart), keyed on the combined quantity
across every combo in the cart, not any single combo — this is what
"order-level discount" means once an order can hold more than one combo.

State-driven, one step visible at a time, with Back/Start-Over on every step
(prior input is never lost — it lives in the gr.State dict).

Run with:  python app.py   (from the slicematic/ root)
"""

from __future__ import annotations

import html
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gradio as gr

import core
import menu
import persistence
import quota

DATA_DIR = ROOT_DIR / "data"
LOG_PATH = ROOT_DIR / "orders_log.txt"
QUOTA_CONFIG_PATH = DATA_DIR / "quota_config.json"

STEPS = ["name", "phone", "base", "pizza", "topping", "qty", "cart", "bill", "payment", "confirmation"]

# Populated once at startup by main(); never re-parsed per request.
_MENU: Dict[str, List[menu.MenuItem]] = {}
_QUOTA: Optional[quota.QuotaManager] = None


def fresh_state() -> dict:
    """A brand-new, empty order — the shape held in gr.State for one session.

    `cart` accumulates committed combos: [{base_id, pizza_id, topping_ids, qty}, ...].
    base_id/pizza_id/topping_ids/qty (top-level) hold the COMBO currently being
    built, separate from anything already added to the cart.
    """
    return {
        "step": "name",
        "name": None,
        "phone": None,
        "base_id": None,
        "pizza_id": None,
        "topping_ids": [],
        "qty": None,
        "cart": [],
        "payment_mode": None,
        "confirmation_html": "",
    }


def _session_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _item_by_id(category: str, item_id: Optional[str]) -> Optional[menu.MenuItem]:
    if item_id is None:
        return None
    for item in _MENU[category]:
        if item.item_id == item_id:
            return item
    return None


def _radio_choices_for(category: str):
    """Build (choices, label_to_id, sold_out_names) from live quota state.

    Used for base/pizza (gr.Radio, single pick) and toppings (gr.CheckboxGroup,
    multi pick) alike — both widgets take the same flat choices list. Sold-out
    items are excluded from `choices` entirely: neither widget has a
    per-option disabled flag, so the only faithful way to make a sold-out
    item "non-selectable" is to not offer it as a choice. They're still shown
    to the customer via a separate greyed-out note (sold_out_names).
    """
    items = _MENU[category]
    choices: List[str] = []
    label_to_id: Dict[str, str] = {}
    sold_out_names: List[str] = []
    for item in items:
        if _QUOTA.is_available(item.item_id):
            label = f"{item.name} — {core.format_money(item.price)}"
            choices.append(label)
            label_to_id[label] = item.item_id
        else:
            sold_out_names.append(item.name)
    return choices, label_to_id, sold_out_names


def _id_to_label(item_id: Optional[str], label_to_id: Dict[str, str]) -> Optional[str]:
    if not item_id:
        return None
    for label, iid in label_to_id.items():
        if iid == item_id:
            return label
    return None


def _ids_to_labels(item_ids: List[str], label_to_id: Dict[str, str]) -> List[str]:
    """Inverse of _id_to_label, for restoring a CheckboxGroup's selection."""
    id_to_label = {iid: label for label, iid in label_to_id.items()}
    return [id_to_label[i] for i in item_ids if i in id_to_label]


def _sold_out_markdown(names: List[str]) -> str:
    if not names:
        return ""
    escaped = ", ".join(html.escape(n) for n in names)
    return f"<span style='color:#999;'>Sold out today: {escaped}</span>"


def _combo_description(line: dict) -> str:
    base_item = _item_by_id("base", line["base_id"])
    pizza_item = _item_by_id("pizza", line["pizza_id"])
    topping_items = [_item_by_id("topping", tid) for tid in line["topping_ids"]]
    topping_text = ", ".join(t.name for t in topping_items) if topping_items else "No toppings"
    return f"{html.escape(base_item.name)} + {html.escape(pizza_item.name)} + {html.escape(topping_text)}"


def _cart_bill(state: dict) -> Optional[core.CartBill]:
    """Price the whole cart (order-level discount/GST). None if cart is empty."""
    if not state["cart"]:
        return None
    line_items = []
    for line in state["cart"]:
        base_item = _item_by_id("base", line["base_id"])
        pizza_item = _item_by_id("pizza", line["pizza_id"])
        topping_items = [_item_by_id("topping", tid) for tid in line["topping_ids"]]
        line_items.append((base_item.price, pizza_item.price, [t.price for t in topping_items], line["qty"]))
    return core.price_cart(line_items)


def _cart_html(state: dict) -> str:
    cart = state["cart"]
    if not cart:
        return "<p style='color:#999;'>Your cart is empty. Add a combo to get started.</p>"

    cart_bill = _cart_bill(state)
    rows = "".join(
        f"<tr><td>{_combo_description(line)} &times; {line_bill.quantity}</td>"
        f"<td style='text-align:right;'>{core.format_money(line_bill.subtotal)}</td></tr>"
        for line, line_bill in zip(cart, cart_bill.lines)
    )
    item_word = "item" if cart_bill.total_quantity == 1 else "items"
    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:16px;max-width:520px;font-family:sans-serif;">
      <h3 style="color:#c1121f;margin-top:0;">🛒 Your Cart</h3>
      <table style="width:100%;border-collapse:collapse;">
        {rows}
        <tr style="border-top:1px solid #ddd;">
          <td><b>Running subtotal ({cart_bill.total_quantity} {item_word})</b></td>
          <td style="text-align:right;"><b>{core.format_money(cart_bill.subtotal)}</b></td>
        </tr>
      </table>
      <p style="color:#777;font-size:0.9em;">Discount and GST are calculated at checkout, based on your full order.</p>
    </div>
    """


def _bill_html(state: dict) -> str:
    cart_bill = _cart_bill(state)
    if not cart_bill:
        return ""

    rows = "".join(
        f"<tr><td>{_combo_description(line)} &times; {line_bill.quantity}</td>"
        f"<td style='text-align:right;'>{core.format_money(line_bill.subtotal)}</td></tr>"
        for line, line_bill in zip(state["cart"], cart_bill.lines)
    )

    discount_row = ""
    if cart_bill.discount > 0:
        # Explicit text color (not just background) — without it, this row
        # inherits Gradio's theme default text color, which can be white and
        # invisible against a light highlight background in dark mode.
        discount_row = (
            "<tr style='background:#d4edda;color:#155724;'>"
            "<td style='color:#155724;'>Discount</td>"
            f"<td style='text-align:right;color:#155724;'>-{core.format_money(cart_bill.discount)}</td></tr>"
        )

    item_word = "item" if cart_bill.total_quantity == 1 else "items"
    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:16px;max-width:520px;font-family:sans-serif;">
      <h3 style="color:#c1121f;margin-top:0;">🍕 SliceMatic Bill</h3>
      <table style="width:100%;border-collapse:collapse;">
        {rows}
        <tr><td>Subtotal ({cart_bill.total_quantity} {item_word})</td>
            <td style="text-align:right;">{core.format_money(cart_bill.subtotal)}</td></tr>
        {discount_row}
        <tr><td>GST (18%)</td><td style="text-align:right;">+{core.format_money(cart_bill.gst)}</td></tr>
        <tr style="border-top:2px solid #c1121f;"><td><b>Total Payable</b></td>
            <td style="text-align:right;color:#c1121f;"><b>{core.format_money(cart_bill.final_total)}</b></td></tr>
      </table>
    </div>
    """


def _confirmation_html(state: dict, confirmation_message: str) -> str:
    cart_bill = _cart_bill(state)
    return f"""
    <div style="border:2px solid #2a9d8f;border-radius:8px;padding:16px;max-width:440px;font-family:sans-serif;">
      <h3 style="color:#2a9d8f;margin-top:0;">✅ Order Confirmed!</h3>
      <p>Thanks, {html.escape(state['name'])} — your order is on its way.</p>
      <p><b>Total paid:</b> {core.format_money(cart_bill.final_total)}</p>
      <p>{html.escape(confirmation_message)}</p>
    </div>
    """


def _kitchen_html() -> str:
    """Stage 2: reads QuotaManager's in-memory, single-process state — fine
    for demonstrating sold-out behavior within one Gradio process. The real
    cross-app kitchen sync (multiple instances/devices staying consistent)
    arrives in Stage 3 via Supabase realtime."""
    rows = []
    for category in ("base", "pizza", "topping"):
        for item in _MENU[category]:
            remaining = _QUOTA.remaining(item.item_id)
            sold_out = remaining <= 0
            color = "#c1121f" if sold_out else "#2a9d8f"
            status = "SOLD OUT" if sold_out else str(remaining)
            rows.append(
                "<tr>"
                f"<td>{html.escape(item.item_id)}</td>"
                f"<td>{html.escape(item.name)}</td>"
                f"<td style='color:{color};font-weight:bold;'>{status}</td>"
                "</tr>"
            )
    return f"""
    <table style="width:100%;border-collapse:collapse;">
      <tr><th style="text-align:left;">ID</th><th style="text-align:left;">Item</th><th style="text-align:left;">Remaining Today</th></tr>
      {''.join(rows)}
    </table>
    """


# --------------------------------------------------------------------------- #
# render(state) -> list of gr.update(...) in ALL_OUTPUTS order. Every step
# handler ends by calling this so the whole page (visible step, restored
# field values, live menu/quota, cart/bill/confirmation HTML, kitchen view,
# and any error banner) re-renders consistently from one source of truth.
# --------------------------------------------------------------------------- #
def render(state: dict, error: Optional[str] = None) -> list:
    step = state["step"]

    def vis(name: str):
        return gr.update(visible=(step == name))

    base_choices, base_label_to_id, base_sold_out = _radio_choices_for("base")
    pizza_choices, pizza_label_to_id, pizza_sold_out = _radio_choices_for("pizza")
    topping_choices, topping_label_to_id, topping_sold_out = _radio_choices_for("topping")

    cart_html_value = _cart_html(state) if step == "cart" else ""
    bill_html_value = _bill_html(state) if step in ("bill", "payment", "confirmation") else ""
    confirmation_html_value = state.get("confirmation_html", "") if step == "confirmation" else ""
    status_value = f"⚠️ {error}" if error else ""

    return [
        vis("name"), vis("phone"),
        vis("base"), vis("pizza"), vis("topping"), vis("qty"),
        vis("cart"), vis("bill"), vis("payment"), vis("confirmation"),
        gr.update(value=state.get("name") or ""),
        gr.update(value=state.get("phone") or ""),
        gr.update(choices=base_choices, value=_id_to_label(state.get("base_id"), base_label_to_id)),
        gr.update(value=_sold_out_markdown(base_sold_out)),
        gr.update(choices=pizza_choices, value=_id_to_label(state.get("pizza_id"), pizza_label_to_id)),
        gr.update(value=_sold_out_markdown(pizza_sold_out)),
        gr.update(choices=topping_choices, value=_ids_to_labels(state.get("topping_ids", []), topping_label_to_id)),
        gr.update(value=_sold_out_markdown(topping_sold_out)),
        gr.update(value=state.get("qty")),
        gr.update(value=cart_html_value),
        gr.update(value=state.get("payment_mode")),
        gr.update(value=bill_html_value),
        gr.update(value=confirmation_html_value),
        gr.update(value=status_value),
        gr.update(value=_kitchen_html()),
    ]


# --------------------------------------------------------------------------- #
# Step handlers. Each validates via core (never re-deriving a rule itself),
# mutates `state`, and returns [state, *render(state, error)].
# --------------------------------------------------------------------------- #
def submit_name(state: dict, value: str):
    res = core.validate_name(value)
    if not res.ok:
        return [state, *render(state, error=res.message)]
    state["name"] = res.value
    state["step"] = "phone"
    return [state, *render(state)]


def submit_phone(state: dict, value: str):
    res = core.validate_phone(value)
    if not res.ok:
        return [state, *render(state, error=res.message)]
    state["phone"] = res.value
    state["step"] = "base"
    return [state, *render(state)]


def submit_base(state: dict, radio_value: Optional[str]):
    _, label_to_id, _sold_out = _radio_choices_for("base")
    item_id = label_to_id.get(radio_value) if radio_value else None
    if item_id is None:
        return [state, *render(state, error="Choose a base from the list.")]
    if not _QUOTA.is_available(item_id):
        return [state, *render(state, error="That base just sold out — please choose another.")]
    state["base_id"] = item_id
    state["step"] = "pizza"
    return [state, *render(state)]


def submit_pizza(state: dict, radio_value: Optional[str]):
    _, label_to_id, _sold_out = _radio_choices_for("pizza")
    item_id = label_to_id.get(radio_value) if radio_value else None
    if item_id is None:
        return [state, *render(state, error="Choose a pizza from the list.")]
    if not _QUOTA.is_available(item_id):
        return [state, *render(state, error="That pizza just sold out — please choose another.")]
    state["pizza_id"] = item_id
    state["step"] = "topping"
    return [state, *render(state)]


def submit_topping(state: dict, selected_labels: Optional[List[str]]):
    _, label_to_id, _sold_out = _radio_choices_for("topping")
    selected_labels = selected_labels or []
    topping_ids = [label_to_id[v] for v in selected_labels if v in label_to_id]

    res = core.validate_toppings_selection(topping_ids)
    if not res.ok:
        return [state, *render(state, error=res.message)]
    if any(not _QUOTA.is_available(tid) for tid in topping_ids):
        return [state, *render(state, error="One of those toppings just sold out — please reselect.")]

    state["topping_ids"] = topping_ids
    state["step"] = "qty"
    return [state, *render(state)]


def skip_toppings(state: dict):
    """Explicit 'no toppings for this combo' — proceeds the same as Next
    with nothing checked (toppings are optional; MIN_TOPPINGS == 0)."""
    state["topping_ids"] = []
    state["step"] = "qty"
    return [state, *render(state)]


def submit_qty(state: dict, value):
    """Validate quantity, commit the in-progress combo as a new cart line,
    then clear the in-progress fields so the next combo starts fresh."""
    res = core.validate_quantity(value)
    if not res.ok:
        return [state, *render(state, error=res.message)]

    state["cart"].append(
        {
            "base_id": state["base_id"],
            "pizza_id": state["pizza_id"],
            "topping_ids": list(state["topping_ids"]),
            "qty": res.value,
        }
    )
    state["base_id"] = None
    state["pizza_id"] = None
    state["topping_ids"] = []
    state["qty"] = None
    state["step"] = "cart"
    return [state, *render(state)]


def add_another_item(state: dict):
    state["step"] = "base"
    return [state, *render(state)]


def remove_last_item(state: dict):
    if state["cart"]:
        state["cart"].pop()
    if not state["cart"]:
        return [state, *render(state, error="Cart is now empty — add an item to continue.")]
    return [state, *render(state)]


def checkout(state: dict):
    if not state["cart"]:
        return [state, *render(state, error="Add at least one item to your cart before checking out.")]
    state["step"] = "bill"
    return [state, *render(state)]


def continue_to_payment(state: dict):
    state["step"] = "payment"
    return [state, *render(state)]


def submit_payment(state: dict, choice: Optional[str]):
    res = core.validate_payment(choice)
    if not res.ok:
        return [state, *render(state, error=res.message)]
    state["payment_mode"] = res.value

    cart_bill = _cart_bill(state)
    timestamp = _session_timestamp()

    # orders_log.txt keeps its fixed 15-column shape (Stage 3 importer maps
    # this one-to-one onto "orders + order_line_items"): one row per cart
    # combo (own base/pizza/topping/qty/subtotal), sharing the same
    # timestamp+name+phone, with the ORDER-level discount/gst/final_total
    # repeated identically on every row of that order.
    records = []
    for line, line_bill in zip(state["cart"], cart_bill.lines):
        base_item = _item_by_id("base", line["base_id"])
        pizza_item = _item_by_id("pizza", line["pizza_id"])
        topping_items = [_item_by_id("topping", tid) for tid in line["topping_ids"]]
        records.append(
            {
                "timestamp": timestamp,
                "name": state["name"],
                "phone": state["phone"],
                "base_name": base_item.name,
                "base_price": base_item.price,
                "pizza_name": pizza_item.name,
                "pizza_price": pizza_item.price,
                "topping_name": "; ".join(t.name for t in topping_items) if topping_items else "None",
                "topping_price": sum((t.price for t in topping_items), start=Decimal("0")),
                "qty": line_bill.quantity,
                "subtotal": line_bill.subtotal,
                "discount": cart_bill.discount,
                "gst": cart_bill.gst,
                "final_total": cart_bill.final_total,
                "payment_mode": state["payment_mode"],
            }
        )

    try:
        for record in records:
            persistence.append_order(record, LOG_PATH)
    except persistence.OrderLogError as exc:
        return [state, *render(state, error=f"Order was priced but could not be saved: {exc}")]

    # Decrement base/pizza stock for every combo; toppings are effectively
    # unlimited (999) so they're never consumed.
    for line in state["cart"]:
        _QUOTA.consume(line["base_id"])
        _QUOTA.consume(line["pizza_id"])

    state["confirmation_html"] = _confirmation_html(state, res.message)
    state["step"] = "confirmation"
    return [state, *render(state)]


def go_back(state: dict):
    step = state["step"]
    if step == "base" and state["cart"]:
        # Reached "base" via "Add Another Item" from the cart (not from
        # phone) — Back should return to reviewing the cart, not walk
        # backwards into a different, already-committed combo's fields.
        state["step"] = "cart"
        return [state, *render(state)]
    idx = STEPS.index(step)
    if idx > 0:
        state["step"] = STEPS[idx - 1]
    return [state, *render(state)]


def start_over(_state: dict):
    new_state = fresh_state()
    return [new_state, *render(new_state)]


# --------------------------------------------------------------------------- #
# UI construction.
# --------------------------------------------------------------------------- #
# Radio/CheckboxGroup lay their options out horizontally (flex-wrap) by
# default. Base/Pizza/Toppings read better as one item per line, so this
# forces a vertical stack for any widget tagged "vertical-options".
_VERTICAL_OPTIONS_CSS = """
.vertical-options .wrap {
    flex-direction: column !important;
}
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="SliceMatic") as demo:
        gr.Markdown("# 🍕 SliceMatic — Order Your Pizza")
        state = gr.State(fresh_state())

        with gr.Tab("Order"):
            status_md = gr.Markdown()

            with gr.Group(visible=True) as grp_name:
                gr.Markdown("### Step 1 — Your Name")
                name_box = gr.Textbox(label="Name")
                with gr.Row():
                    cancel_name = gr.Button("Start Over")
                    next_name = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_phone:
                gr.Markdown("### Step 2 — Phone Number")
                phone_box = gr.Textbox(label="Phone (10 digits)")
                with gr.Row():
                    back_phone = gr.Button("Back")
                    cancel_phone = gr.Button("Start Over")
                    next_phone = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_base:
                gr.Markdown("### Choose a Base")
                base_sold_out_md = gr.Markdown()
                base_radio = gr.Radio(label="Base", choices=[], elem_classes="vertical-options")
                with gr.Row():
                    back_base = gr.Button("Back")
                    cancel_base = gr.Button("Start Over")
                    next_base = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_pizza:
                gr.Markdown("### Choose a Pizza")
                pizza_sold_out_md = gr.Markdown()
                pizza_radio = gr.Radio(label="Pizza", choices=[], elem_classes="vertical-options")
                with gr.Row():
                    back_pizza = gr.Button("Back")
                    cancel_pizza = gr.Button("Start Over")
                    next_pizza = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_topping:
                gr.Markdown("### Choose Toppings (optional — pick any number, or none)")
                topping_sold_out_md = gr.Markdown()
                topping_checkboxes = gr.CheckboxGroup(label="Toppings", choices=[], elem_classes="vertical-options")
                with gr.Row():
                    back_topping = gr.Button("Back")
                    cancel_topping = gr.Button("Start Over")
                    skip_topping_btn = gr.Button("Skip (No Toppings)")
                    next_topping = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_qty:
                gr.Markdown("### Quantity for This Combo")
                qty_box = gr.Number(label="Quantity (1-10)", precision=0)
                with gr.Row():
                    back_qty = gr.Button("Back")
                    cancel_qty = gr.Button("Start Over")
                    next_qty = gr.Button("Add to Cart", variant="primary")

            with gr.Group(visible=False) as grp_cart:
                gr.Markdown("### Your Cart")
                cart_html_box = gr.HTML()
                with gr.Row():
                    remove_last_btn = gr.Button("Remove Last Item")
                    cancel_cart = gr.Button("Start Over")
                with gr.Row():
                    add_another_btn = gr.Button("Add Another Item")
                    checkout_btn = gr.Button("Checkout", variant="primary")

            with gr.Group(visible=False) as grp_bill:
                gr.Markdown("### Your Bill")
                bill_html_box = gr.HTML()
                with gr.Row():
                    back_bill = gr.Button("Back")
                    cancel_bill = gr.Button("Start Over")
                    next_bill = gr.Button("Continue to Payment", variant="primary")

            with gr.Group(visible=False) as grp_payment:
                gr.Markdown("### Payment")
                payment_radio = gr.Radio(label="Payment Mode", choices=["Cash", "Card", "UPI"])
                with gr.Row():
                    back_payment = gr.Button("Back")
                    cancel_payment = gr.Button("Start Over")
                    next_payment = gr.Button("Place Order", variant="primary")

            with gr.Group(visible=False) as grp_confirmation:
                gr.Markdown("### Order Confirmed")
                confirmation_html_box = gr.HTML()
                start_new_btn = gr.Button("Start New Order", variant="primary")

        with gr.Tab("Kitchen (Admin)"):
            # Stage 2: single-process, in-memory shared state for demonstration.
            # Cross-app kitchen sync arrives in Stage 3 via Supabase realtime.
            gr.Markdown("### Kitchen view — remaining stock today")
            kitchen_html_box = gr.HTML()
            kitchen_refresh_btn = gr.Button("Refresh")

        all_outputs = [
            grp_name, grp_phone,
            grp_base, grp_pizza, grp_topping, grp_qty,
            grp_cart, grp_bill, grp_payment, grp_confirmation,
            name_box, phone_box,
            base_radio, base_sold_out_md,
            pizza_radio, pizza_sold_out_md,
            topping_checkboxes, topping_sold_out_md,
            qty_box,
            cart_html_box,
            payment_radio,
            bill_html_box, confirmation_html_box,
            status_md, kitchen_html_box,
        ]

        next_name.click(submit_name, inputs=[state, name_box], outputs=[state, *all_outputs])
        cancel_name.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_phone.click(submit_phone, inputs=[state, phone_box], outputs=[state, *all_outputs])
        back_phone.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_phone.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_base.click(submit_base, inputs=[state, base_radio], outputs=[state, *all_outputs])
        back_base.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_base.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_pizza.click(submit_pizza, inputs=[state, pizza_radio], outputs=[state, *all_outputs])
        back_pizza.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_pizza.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_topping.click(submit_topping, inputs=[state, topping_checkboxes], outputs=[state, *all_outputs])
        skip_topping_btn.click(skip_toppings, inputs=[state], outputs=[state, *all_outputs])
        back_topping.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_topping.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_qty.click(submit_qty, inputs=[state, qty_box], outputs=[state, *all_outputs])
        back_qty.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_qty.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        add_another_btn.click(add_another_item, inputs=[state], outputs=[state, *all_outputs])
        remove_last_btn.click(remove_last_item, inputs=[state], outputs=[state, *all_outputs])
        checkout_btn.click(checkout, inputs=[state], outputs=[state, *all_outputs])
        cancel_cart.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_bill.click(continue_to_payment, inputs=[state], outputs=[state, *all_outputs])
        back_bill.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_bill.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_payment.click(submit_payment, inputs=[state, payment_radio], outputs=[state, *all_outputs])
        back_payment.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_payment.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        start_new_btn.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        kitchen_refresh_btn.click(lambda: gr.update(value=_kitchen_html()), inputs=None, outputs=[kitchen_html_box])

        demo.load(
            lambda: [fresh_state(), *render(fresh_state())],
            inputs=None,
            outputs=[state, *all_outputs],
        )

    return demo


def main() -> None:
    """Entry point: load menu + quota (exit cleanly on failure), launch the UI."""
    global _MENU, _QUOTA
    try:
        _MENU = menu.load_all_menus(DATA_DIR)
    except menu.MenuFileError as exc:
        print(f"Cannot start SliceMatic: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        quota_config = quota.load_quota_config(QUOTA_CONFIG_PATH)
    except quota.QuotaConfigError as exc:
        print(f"Cannot start SliceMatic: {exc}", file=sys.stderr)
        sys.exit(1)

    _QUOTA = quota.QuotaManager(quota_config, auto_reset=True)

    demo = build_ui()
    demo.launch(theme=gr.themes.Soft(primary_hue="red"), css=_VERTICAL_OPTIONS_CSS)


if __name__ == "__main__":
    main()
