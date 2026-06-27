"""
core.py — SliceMatic pure business logic.

This module is the SHARED CONTRACT for the whole project. It contains:
  * input validators (name, phone, quantity, menu selection, toppings, payment)
  * the pricing engine (unit price -> subtotal -> discount -> GST -> final)
    where unit price = base + pizza + sum of one-or-more chosen toppings

DESIGN RULES (do not break — Stage 3 depends on them):
  * NO Gradio, NO file I/O, NO input()/print() in this module.
  * Every validator and the pricing engine is callable with plain arguments
    and returns a STRUCTURED result, never raises on bad *user* input.
  * All money uses decimal.Decimal — never float.
  * Tunable business rules (discount threshold, discount rate, GST rate) are
    NAMED CONSTANTS so the grader can change the discount threshold from 5 to 3
    live without hunting through the code (PRD FR-5).

Stage 3 forward-compatibility:
  * Option B (conversational LLM agent) calls these exact validators and
    `price_order` with plain args and reads the (ok, message, value) result.
    Keep them UI-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Iterable, List, NamedTuple, Optional


# --------------------------------------------------------------------------- #
# Business-rule constants (PRD FR-2, FR-4, FR-5, FR-6).
# The grader WILL change DISCOUNT_THRESHOLD (e.g. 5 -> 3) at demo time.
# Keep every tunable rule here; never inline these literals elsewhere.
# --------------------------------------------------------------------------- #
GST_RATE = Decimal("0.18")            # 18% GST on post-discount subtotal
DISCOUNT_RATE = Decimal("0.10")       # 10% order-level discount
DISCOUNT_THRESHOLD = 5                # qty >= threshold => discount applies

MIN_QTY = 1
MAX_QTY = 10                          # outlet capacity per order (PRD FR-2)

MIN_TOPPINGS = 1                      # at least one topping; multiple allowed

NAME_MIN_LEN = 2
NAME_MAX_LEN = 40

# Payment modes: code -> canonical name (PRD FR-7).
PAYMENT_MODES = {
    "1": "Cash",
    "2": "Card",
    "3": "UPI",
}

_TWO_PLACES = Decimal("0.01")


# --------------------------------------------------------------------------- #
# Structured result types.
# --------------------------------------------------------------------------- #
class Result(NamedTuple):
    """Structured outcome of a validation/operation.

    Attributes:
        ok:      True if the operation succeeded.
        message: Human-readable message. On failure this states *what was
                 wrong and what is acceptable* (PRD 3.2) — never a bare
                 "invalid input". On success it may be a confirmation string.
        value:   The cleaned/typed value on success (e.g. int qty, canonical
                 name, payment mode), else None.
    """

    ok: bool
    message: str
    value: Any = None


@dataclass(frozen=True)
class Bill:
    """A fully priced order line. All monetary fields are Decimal, 2 dp.

    Field names map one-to-one onto the orders_log columns (PRD 3.4) so the
    persistence layer and the Stage 3 importer can consume this directly.
    """

    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    discount: Decimal
    gst: Decimal
    final_total: Decimal

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Money helpers.
# --------------------------------------------------------------------------- #
def to_money(value: Any) -> Decimal:
    """Coerce a price-like value to a Decimal.

    Accepts int/str/Decimal. Raises ValueError on anything non-numeric so the
    MENU loader (not user input) fails loudly on a bad price field. User-facing
    quantity/selection parsing lives in the validators below and never raises.
    """
    if isinstance(value, Decimal):
        return value
    try:
        # Route through str() so a float like 0.1 doesn't smuggle in binary
        # rounding error; menu prices are integers/strings anyway.
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Not a valid price: {value!r}") from exc


def quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to two places using banker-safe HALF_UP for display."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Validators (PRD FR-1, FR-2, FR-3, FR-7 / NFR 3.1, 3.3).
# Each returns a Result; none raises on bad user input.
# --------------------------------------------------------------------------- #
def validate_name(name: Any) -> Result:
    """Validate a customer name.

    Rule: alphabetic characters and spaces only; 2-40 chars; reject empty,
    whitespace-only, or anything containing digits/symbols (PRD FR-1).

    Returns Result(ok, message, value=trimmed_name).
    """
    if name is None:
        return Result(False, "Name must be 2-40 letters.", None)
    text = str(name)
    if text.strip() == "":
        return Result(False, "Name must be 2-40 letters (cannot be blank).", None)
    if not re.fullmatch(r"[A-Za-z ]+", text):
        return Result(False, "Name must contain letters and spaces only.", None)
    trimmed = text.strip()
    if not (NAME_MIN_LEN <= len(trimmed) <= NAME_MAX_LEN):
        return Result(
            False,
            f"Name must be {NAME_MIN_LEN}-{NAME_MAX_LEN} letters.",
            None,
        )
    return Result(True, "Name accepted.", trimmed)


def validate_phone(phone: Any) -> Result:
    """Validate an Indian mobile number.

    Rule: exactly 10 digits; first digit 6/7/8/9 (PRD FR-1). The cleaned value
    is the canonical key used by orders_log and the Stage 3 recommendation
    engine's phone lookup, so it is returned verbatim (10-digit string).

    Returns Result(ok, message, value=phone_str).
    """
    if phone is None:
        return Result(False, "Enter a valid 10-digit mobile.", None)
    text = str(phone).strip()
    if not re.fullmatch(r"[6-9]\d{9}", text):
        return Result(False, "Enter a valid 10-digit mobile (starts 6-9).", None)
    return Result(True, "Phone accepted.", text)


def validate_quantity(qty: Any) -> Result:
    """Validate order quantity.

    Rule: integer 1-10 inclusive. Reject 0, negatives, >10, decimals
    ("2.5"), and non-numeric text ("three"), and blanks (PRD FR-2, edge
    cases 3 & 7). Booleans are rejected (True/False are not quantities).

    Returns Result(ok, message, value=int_qty).
    """
    range_msg = f"Quantity must be a whole number from {MIN_QTY} to {MAX_QTY}."

    if isinstance(qty, bool):
        return Result(False, range_msg, None)

    if isinstance(qty, int):
        n = qty
    elif isinstance(qty, float):
        if not qty.is_integer():
            return Result(False, range_msg, None)
        n = int(qty)
    else:
        text = str(qty).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            # Catches "", "three", "2.5", "5.0", symbols.
            return Result(False, range_msg, None)
        n = int(text)

    if not (MIN_QTY <= n <= MAX_QTY):
        return Result(False, range_msg, None)
    return Result(True, "Quantity accepted.", n)


def validate_menu_selection(selection: Any, item_count: int) -> Result:
    """Validate a 1-based menu pick against the number of loaded items.

    Rule: integer within [1, item_count]. Reject 0, out-of-range, letters,
    decimals, and empty input (PRD FR-3, edge cases 4 & 5 — a price typed as
    an item number is simply out of range and rejected).

    `item_count` is the live length of the parsed menu list (never hardcoded).

    Returns Result(ok, message, value=1_based_index).
    """
    pick_msg = "Choose a number from the list."
    if item_count <= 0:
        return Result(False, "Menu is empty; cannot select an item.", None)

    if isinstance(selection, bool):
        return Result(False, pick_msg, None)
    if isinstance(selection, int):
        n = selection
    elif isinstance(selection, float):
        if not selection.is_integer():
            return Result(False, pick_msg, None)
        n = int(selection)
    else:
        text = str(selection).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            return Result(False, pick_msg, None)
        n = int(text)

    if not (1 <= n <= item_count):
        return Result(False, f"Choose a number from 1 to {item_count}.", None)
    return Result(True, "Selection accepted.", n)


def validate_toppings_selection(selected_ids: Any) -> Result:
    """Validate a multi-topping pick.

    Rule: at least MIN_TOPPINGS topping must be chosen (multiple allowed).
    `selected_ids` is whatever the caller already resolved to item ids (the
    UI maps its widget's selected labels back to ids before calling this).

    Returns Result(ok, message, value=list_of_ids).
    """
    ids = list(selected_ids) if selected_ids else []
    if len(ids) < MIN_TOPPINGS:
        plural = "topping" if MIN_TOPPINGS == 1 else "toppings"
        return Result(False, f"Choose at least {MIN_TOPPINGS} {plural}.", None)
    return Result(True, "Toppings accepted.", ids)


def validate_payment(choice: Any) -> Result:
    """Validate a payment-mode choice and produce a mode-specific confirmation.

    Accepts the menu code ("1"/"2"/"3") or a canonical/loose mode name
    ("cash"/"card"/"upi", any case) (PRD FR-7). Returns the canonical mode
    name as value and a mode-specific confirmation message.

    Returns Result(ok, message, value=mode_name).
    """
    options = "Pay with 1 Cash, 2 Card, or 3 UPI."
    if choice is None:
        return Result(False, options, None)

    text = str(choice).strip()
    mode = None
    if text in PAYMENT_MODES:
        mode = PAYMENT_MODES[text]
    else:
        for name in PAYMENT_MODES.values():
            if text.lower() == name.lower():
                mode = name
                break
    if mode is None:
        return Result(False, options, None)
    return Result(True, payment_confirmation(mode), mode)


def payment_confirmation(mode: str) -> str:
    """Return the mode-specific confirmation message for a canonical mode."""
    messages = {
        "Cash": "Cash selected — please pay the rider on delivery.",
        "Card": "Card selected — keep your card ready for the POS machine.",
        "UPI": "UPI selected — a payment request will be sent to your number.",
    }
    return messages.get(mode, f"{mode} selected.")


# --------------------------------------------------------------------------- #
# Pricing engine (PRD FR-4). Order of operations is FIXED and testable:
#   unit price -> subtotal -> discount -> GST -> final.
# --------------------------------------------------------------------------- #
def unit_price(base_price: Any, pizza_price: Any, topping_prices: Iterable[Any]) -> Decimal:
    """Unit price = base + pizza + sum of all chosen topping prices.

    `topping_prices` is an iterable (one or more toppings can be selected per
    order line). Returns a Decimal (2 dp).
    """
    total = to_money(base_price) + to_money(pizza_price)
    for topping_price in topping_prices:
        total += to_money(topping_price)
    return quantize_money(total)


def discount_for(subtotal: Decimal, qty: int) -> Decimal:
    """Order-level discount on the subtotal.

    DISCOUNT_RATE off when qty >= DISCOUNT_THRESHOLD, else zero (PRD FR-5).
    Both rule values are module constants the grader can change live.
    """
    if qty >= DISCOUNT_THRESHOLD:
        return quantize_money(subtotal * DISCOUNT_RATE)
    return Decimal("0.00")


def price_order(
    base_price: Any,
    pizza_price: Any,
    topping_prices: Iterable[Any],
    qty: int,
) -> Bill:
    """Compute the full bill for one order line.

    Fixed order of operations (PRD FR-4):
        unit  = base + pizza + sum(toppings)
        sub   = unit * qty
        disc  = DISCOUNT_RATE * sub   (only if qty >= DISCOUNT_THRESHOLD)
        gst   = GST_RATE * (sub - disc)        # GST on POST-discount subtotal
        final = (sub - disc) + gst

    `topping_prices` is an iterable — one or more toppings per order line.
    `qty` is assumed already validated by `validate_quantity`. This function is
    pure: no I/O, no UI — safe for the Stage 3 LLM agent to call directly.

    Returns a Bill with all monetary fields as 2-dp Decimals.
    """
    unit = unit_price(base_price, pizza_price, topping_prices)
    subtotal = quantize_money(unit * Decimal(qty))
    discount = discount_for(subtotal, qty)
    discounted = subtotal - discount
    gst = quantize_money(discounted * GST_RATE)
    final_total = quantize_money(discounted + gst)
    return Bill(
        unit_price=unit,
        quantity=qty,
        subtotal=subtotal,
        discount=discount,
        gst=gst,
        final_total=final_total,
    )


def format_money(value: Decimal) -> str:
    """Render a Decimal as an INR amount string, e.g. '₹299.00' (PRD 3.6)."""
    return f"₹{quantize_money(to_money(value)):.2f}"
