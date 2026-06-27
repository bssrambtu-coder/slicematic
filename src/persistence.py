"""
persistence.py — append completed orders to orders_log.txt.

Log format (PRD 3.4 — fixed, machine-parseable by the Stage 3 importer):
  * Pipe-separated fields, ONE order block per record (a single line).
  * A blank line separates records.
  * Field order is EXACTLY (LOG_FIELDS):

      timestamp | name | phone | base_name | base_price | pizza_name |
      pizza_price | topping_name | topping_price | qty | subtotal |
      discount | gst | final_total | payment_mode

Stage 3 forward-compatibility (Option A — recommendation engine):
  * `phone` is the customer key. find_orders_by_phone keys cleanly on the
    10-digit phone string so past orders can be retrieved without a migration.

Failure handling (PRD NFR 3.5):
  * A log-write failure (permissions/disk) surfaces a clear message and never
    loses the order silently — raises OrderLogError; the app reports it.

This module does file I/O but does not import Gradio and does not call core's
validators (the app validates before handing a clean record here).
"""

from __future__ import annotations

import re
import warnings
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Mapping

# Canonical column order. Persist exactly these keys, in this order.
LOG_FIELDS = [
    "timestamp",
    "name",
    "phone",
    "base_name",
    "base_price",
    "pizza_name",
    "pizza_price",
    "topping_name",
    "topping_price",
    "qty",
    "subtotal",
    "discount",
    "gst",
    "final_total",
    "payment_mode",
]

# Fields that hold money and must round-trip as 2-dp Decimal.
_MONEY_FIELDS = {
    "base_price",
    "pizza_price",
    "topping_price",
    "subtotal",
    "discount",
    "gst",
    "final_total",
}

FIELD_DELIMITER = "|"
DEFAULT_LOG_PATH = "orders_log.txt"
_TWO_PLACES = Decimal("0.01")


class OrderLogError(Exception):
    """Raised when an order cannot be persisted (caught and surfaced by app)."""


def _format_value(value: object) -> str:
    """Render one field value for storage. Decimals are fixed to 2 places."""
    if isinstance(value, Decimal):
        value = value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return str(value)


def format_record(order: Mapping[str, object]) -> str:
    """Render one order dict into a single pipe-delimited line.

    `order` must contain every key in LOG_FIELDS. Emits fields in LOG_FIELDS
    order joined by FIELD_DELIMITER. Raises OrderLogError if a required field
    is missing or a value itself contains the delimiter (would corrupt the
    fixed-width parse).
    """
    rendered = []
    for key in LOG_FIELDS:
        if key not in order:
            raise OrderLogError(f"Order is missing required field: {key!r}")
        text = _format_value(order[key])
        if FIELD_DELIMITER in text:
            raise OrderLogError(f"Field {key!r} value contains '{FIELD_DELIMITER}': {text!r}")
        rendered.append(text)
    return FIELD_DELIMITER.join(rendered)


def append_order(order: Mapping[str, object], log_path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Append one completed order block to orders_log.txt.

    Writes the formatted record as one line, preceded by a blank-line
    separator if the file already has content, so the file stays parseable.
    Raises OrderLogError on any I/O failure — never swallows a write error
    (the order must not be lost silently).
    """
    record_line = format_record(order)
    path = Path(log_path)
    try:
        has_existing_content = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8") as f:
            if has_existing_content:
                f.write("\n")
            f.write(record_line + "\n")
    except OSError as exc:
        raise OrderLogError(f"Could not write order to {path}: {exc}") from exc


def find_orders_by_phone(
    phone: str,
    log_path: str | Path = DEFAULT_LOG_PATH,
) -> List[Dict[str, object]]:
    """Return all past order records for a phone number, oldest-first.

    STAGE 3 HOOK (Option A — recommendation engine). Parses orders_log.txt and
    returns each matching block as a dict keyed by LOG_FIELDS, with money
    fields restored to Decimal and qty restored to int. Returns [] if the log
    is missing, empty, or has no match — never raises on a malformed file;
    corrupt blocks are skipped with a warning so one bad record can't break
    the lookup for everyone else.
    """
    path = Path(log_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return []

    matches: List[Dict[str, object]] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        block = block.strip()
        if not block:
            continue

        fields = block.split(FIELD_DELIMITER)
        if len(fields) != len(LOG_FIELDS):
            warnings.warn(f"Skipping malformed order_log record: {block!r}")
            continue

        record: Dict[str, object] = dict(zip(LOG_FIELDS, (f.strip() for f in fields)))
        if record.get("phone") != phone:
            continue

        try:
            for key in _MONEY_FIELDS:
                record[key] = Decimal(record[key])
            record["qty"] = int(record["qty"])
        except (InvalidOperation, ValueError):
            warnings.warn(f"Skipping order_log record with unparsable numeric field: {block!r}")
            continue

        matches.append(record)
    return matches
