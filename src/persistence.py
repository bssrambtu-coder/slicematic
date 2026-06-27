"""
persistence.py — append completed orders to orders_log.txt.

OWNER: backend/persistence teammate. This is a SKELETON — signatures +
contract only. Implement the bodies and keep the on-disk format EXACT.

Log format (PRD 3.4 — fixed, machine-parseable by the Stage 3 importer):
  * Pipe-separated fields, ONE order block per record.
  * A blank line separates records.
  * Field order is EXACTLY:

      timestamp | name | phone | base_name | base_price | pizza_name |
      pizza_price | topping_name | topping_price | qty | subtotal |
      discount | gst | final_total | payment_mode

Stage 3 forward-compatibility (Option A — recommendation engine):
  * `phone` is the customer key. The lookup helper below keys cleanly on the
    10-digit phone string so past orders can be retrieved without a migration.

Failure handling (PRD NFR 3.5):
  * A log-write failure (permissions/disk) must surface a clear message and
    NEVER lose the order silently — raise OrderLogError; the app reports it.

This module does file I/O but MUST NOT import Gradio or call core's validators
(the app validates before handing a clean record here).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Mapping

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

FIELD_DELIMITER = "|"
RECORD_SEPARATOR = "\n\n"  # blank line between order blocks
DEFAULT_LOG_PATH = "orders_log.txt"


class OrderLogError(Exception):
    """Raised when an order cannot be persisted (caught and surfaced by app)."""


def format_record(order: Mapping[str, object]) -> str:
    """Render one order dict into a single pipe-delimited line.

    `order` must contain every key in LOG_FIELDS. Emits fields in LOG_FIELDS
    order joined by FIELD_DELIMITER. Money values should already be 2-dp
    strings/Decimals from core.Bill. Must not contain raw '|' inside a field.
    """
    raise NotImplementedError


def append_order(order: Mapping[str, object], log_path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Append one completed order block to orders_log.txt.

    Writes the formatted record followed by a blank-line separator so the file
    stays parseable. Raises OrderLogError on any I/O failure — never swallows
    a write error (the order must not be lost silently).
    """
    raise NotImplementedError


def find_orders_by_phone(
    phone: str,
    log_path: str | Path = DEFAULT_LOG_PATH,
) -> List[dict]:
    """Return all past order records for a phone number, newest-last.

    STAGE 3 HOOK (Option A — recommendation engine). Parses orders_log.txt and
    returns each matching block as a dict keyed by LOG_FIELDS. Keying on the
    10-digit `phone` string is the whole reason the log format fixes phone as
    column 3 — implement the lookup here so Stage 3 reuses it unchanged.
    Returns [] if the log is missing or has no match (does not raise).
    """
    raise NotImplementedError
