"""
app.py — SliceMatic Gradio UI (root entry point for Hugging Face Spaces).

Stays THIN: every validation, price, and quota decision is delegated to
src/core.py, src/menu.py, src/persistence.py, src/quota.py. This file only
collects input, calls those modules, and renders the result as a
state-driven, one-step-at-a-time order flow with Back/Start-Over on every
step (prior input is never lost — it lives in the gr.State dict).

Run with:  python app.py   (from the slicematic/ root)
"""

from __future__ import annotations

import html
import sys
from datetime import datetime, timezone
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

STEPS = ["name", "phone", "qty", "base", "pizza", "topping", "bill", "payment", "confirmation"]

# Populated once at startup by main(); never re-parsed per request.
_MENU: Dict[str, List[menu.MenuItem]] = {}
_QUOTA: Optional[quota.QuotaManager] = None


def fresh_state() -> dict:
    """A brand-new, empty order — the shape held in gr.State for one session."""
    return {
        "step": "name",
        "name": None,
        "phone": None,
        "qty": None,
        "base_id": None,
        "pizza_id": None,
        "topping_id": None,
        "payment_mode": None,
        "bill": None,
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

    Sold-out items are excluded from `choices` entirely — Gradio's Radio has
    no per-option disabled flag, so the only faithful way to make a sold-out
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


def _sold_out_markdown(names: List[str]) -> str:
    if not names:
        return ""
    escaped = ", ".join(html.escape(n) for n in names)
    return f"<span style='color:#999;'>Sold out today: {escaped}</span>"


def _bill_html(state: dict) -> str:
    base_item = _item_by_id("base", state["base_id"])
    pizza_item = _item_by_id("pizza", state["pizza_id"])
    topping_item = _item_by_id("topping", state["topping_id"])
    bill: core.Bill = state["bill"]
    if not (base_item and pizza_item and topping_item and bill):
        return ""

    discount_row = ""
    if bill.discount > 0:
        discount_row = (
            "<tr style='background:#fff3cd;'><td>Discount</td>"
            f"<td style='text-align:right;'>-{core.format_money(bill.discount)}</td></tr>"
        )

    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:16px;max-width:440px;font-family:sans-serif;">
      <h3 style="color:#c1121f;margin-top:0;">🍕 SliceMatic Bill</h3>
      <table style="width:100%;border-collapse:collapse;">
        <tr><td>{html.escape(base_item.name)}</td><td style="text-align:right;">{core.format_money(base_item.price)}</td></tr>
        <tr><td>{html.escape(pizza_item.name)}</td><td style="text-align:right;">{core.format_money(pizza_item.price)}</td></tr>
        <tr><td>{html.escape(topping_item.name)}</td><td style="text-align:right;">{core.format_money(topping_item.price)}</td></tr>
        <tr><td>Unit price</td><td style="text-align:right;">{core.format_money(bill.unit_price)}</td></tr>
        <tr><td>Subtotal &times; {bill.quantity}</td><td style="text-align:right;">{core.format_money(bill.subtotal)}</td></tr>
        {discount_row}
        <tr><td>GST (18%)</td><td style="text-align:right;">+{core.format_money(bill.gst)}</td></tr>
        <tr style="border-top:2px solid #c1121f;"><td><b>Total Payable</b></td>
            <td style="text-align:right;color:#c1121f;"><b>{core.format_money(bill.final_total)}</b></td></tr>
      </table>
    </div>
    """


def _confirmation_html(state: dict, confirmation_message: str) -> str:
    bill: core.Bill = state["bill"]
    return f"""
    <div style="border:2px solid #2a9d8f;border-radius:8px;padding:16px;max-width:440px;font-family:sans-serif;">
      <h3 style="color:#2a9d8f;margin-top:0;">✅ Order Confirmed!</h3>
      <p>Thanks, {html.escape(state['name'])} — your order is on its way.</p>
      <p><b>Total paid:</b> {core.format_money(bill.final_total)}</p>
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
# field values, live menu/quota, bill/confirmation HTML, kitchen view, and
# any error banner) re-renders consistently from one source of truth: state.
# --------------------------------------------------------------------------- #
def render(state: dict, error: Optional[str] = None) -> list:
    step = state["step"]

    def vis(name: str):
        return gr.update(visible=(step == name))

    base_choices, base_label_to_id, base_sold_out = _radio_choices_for("base")
    pizza_choices, pizza_label_to_id, pizza_sold_out = _radio_choices_for("pizza")
    topping_choices, topping_label_to_id, topping_sold_out = _radio_choices_for("topping")

    bill_html_value = _bill_html(state) if step in ("bill", "payment", "confirmation") else ""
    confirmation_html_value = state.get("confirmation_html", "") if step == "confirmation" else ""
    status_value = f"⚠️ {error}" if error else ""

    return [
        vis("name"), vis("phone"), vis("qty"),
        vis("base"), vis("pizza"), vis("topping"),
        vis("bill"), vis("payment"), vis("confirmation"),
        gr.update(value=state.get("name") or ""),
        gr.update(value=state.get("phone") or ""),
        gr.update(value=state.get("qty")),
        gr.update(choices=base_choices, value=_id_to_label(state.get("base_id"), base_label_to_id)),
        gr.update(value=_sold_out_markdown(base_sold_out)),
        gr.update(choices=pizza_choices, value=_id_to_label(state.get("pizza_id"), pizza_label_to_id)),
        gr.update(value=_sold_out_markdown(pizza_sold_out)),
        gr.update(choices=topping_choices, value=_id_to_label(state.get("topping_id"), topping_label_to_id)),
        gr.update(value=_sold_out_markdown(topping_sold_out)),
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
    state["step"] = "qty"
    return [state, *render(state)]


def submit_qty(state: dict, value):
    res = core.validate_quantity(value)
    if not res.ok:
        return [state, *render(state, error=res.message)]
    state["qty"] = res.value
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


def submit_topping(state: dict, radio_value: Optional[str]):
    _, label_to_id, _sold_out = _radio_choices_for("topping")
    item_id = label_to_id.get(radio_value) if radio_value else None
    if item_id is None:
        return [state, *render(state, error="Choose a topping from the list.")]
    if not _QUOTA.is_available(item_id):
        return [state, *render(state, error="That topping just sold out — please choose another.")]
    state["topping_id"] = item_id

    base_item = _item_by_id("base", state["base_id"])
    pizza_item = _item_by_id("pizza", state["pizza_id"])
    topping_item = _item_by_id("topping", item_id)
    state["bill"] = core.price_order(base_item.price, pizza_item.price, topping_item.price, state["qty"])
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

    base_item = _item_by_id("base", state["base_id"])
    pizza_item = _item_by_id("pizza", state["pizza_id"])
    topping_item = _item_by_id("topping", state["topping_id"])
    bill: core.Bill = state["bill"]

    record = {
        "timestamp": _session_timestamp(),
        "name": state["name"],
        "phone": state["phone"],
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
        "payment_mode": state["payment_mode"],
    }
    try:
        persistence.append_order(record, LOG_PATH)
    except persistence.OrderLogError as exc:
        return [state, *render(state, error=f"Order was priced but could not be saved: {exc}")]

    # Decrement base and pizza stock; toppings are effectively unlimited (999).
    _QUOTA.consume(state["base_id"])
    _QUOTA.consume(state["pizza_id"])

    state["confirmation_html"] = _confirmation_html(state, res.message)
    state["step"] = "confirmation"
    return [state, *render(state)]


def go_back(state: dict):
    idx = STEPS.index(state["step"])
    if idx > 0:
        state["step"] = STEPS[idx - 1]
    return [state, *render(state)]


def start_over(_state: dict):
    new_state = fresh_state()
    return [new_state, *render(new_state)]


# --------------------------------------------------------------------------- #
# UI construction.
# --------------------------------------------------------------------------- #
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

            with gr.Group(visible=False) as grp_qty:
                gr.Markdown("### Step 3 — Quantity")
                qty_box = gr.Number(label="Quantity (1-10)", precision=0)
                with gr.Row():
                    back_qty = gr.Button("Back")
                    cancel_qty = gr.Button("Start Over")
                    next_qty = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_base:
                gr.Markdown("### Step 4 — Choose Your Base")
                base_sold_out_md = gr.Markdown()
                base_radio = gr.Radio(label="Base", choices=[])
                with gr.Row():
                    back_base = gr.Button("Back")
                    cancel_base = gr.Button("Start Over")
                    next_base = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_pizza:
                gr.Markdown("### Step 5 — Choose Your Pizza")
                pizza_sold_out_md = gr.Markdown()
                pizza_radio = gr.Radio(label="Pizza", choices=[])
                with gr.Row():
                    back_pizza = gr.Button("Back")
                    cancel_pizza = gr.Button("Start Over")
                    next_pizza = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_topping:
                gr.Markdown("### Step 6 — Choose Your Topping")
                topping_sold_out_md = gr.Markdown()
                topping_radio = gr.Radio(label="Topping", choices=[])
                with gr.Row():
                    back_topping = gr.Button("Back")
                    cancel_topping = gr.Button("Start Over")
                    next_topping = gr.Button("Next", variant="primary")

            with gr.Group(visible=False) as grp_bill:
                gr.Markdown("### Step 7 — Your Bill")
                bill_html_box = gr.HTML()
                with gr.Row():
                    back_bill = gr.Button("Back")
                    cancel_bill = gr.Button("Start Over")
                    next_bill = gr.Button("Continue to Payment", variant="primary")

            with gr.Group(visible=False) as grp_payment:
                gr.Markdown("### Step 8 — Payment")
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
            grp_name, grp_phone, grp_qty, grp_base, grp_pizza, grp_topping, grp_bill, grp_payment, grp_confirmation,
            name_box, phone_box, qty_box,
            base_radio, base_sold_out_md,
            pizza_radio, pizza_sold_out_md,
            topping_radio, topping_sold_out_md,
            payment_radio,
            bill_html_box, confirmation_html_box,
            status_md, kitchen_html_box,
        ]

        next_name.click(submit_name, inputs=[state, name_box], outputs=[state, *all_outputs])
        cancel_name.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_phone.click(submit_phone, inputs=[state, phone_box], outputs=[state, *all_outputs])
        back_phone.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_phone.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_qty.click(submit_qty, inputs=[state, qty_box], outputs=[state, *all_outputs])
        back_qty.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_qty.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_base.click(submit_base, inputs=[state, base_radio], outputs=[state, *all_outputs])
        back_base.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_base.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_pizza.click(submit_pizza, inputs=[state, pizza_radio], outputs=[state, *all_outputs])
        back_pizza.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_pizza.click(start_over, inputs=[state], outputs=[state, *all_outputs])

        next_topping.click(submit_topping, inputs=[state, topping_radio], outputs=[state, *all_outputs])
        back_topping.click(go_back, inputs=[state], outputs=[state, *all_outputs])
        cancel_topping.click(start_over, inputs=[state], outputs=[state, *all_outputs])

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
    demo.launch(theme=gr.themes.Soft(primary_hue="red"))


if __name__ == "__main__":
    main()
