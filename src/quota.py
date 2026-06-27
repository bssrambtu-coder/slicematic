"""
quota.py — daily per-item sold-out quota, reset at midnight IST.

Quota numbers come from the Stage 1 business-economics model (weekday avg ~38
orders/day, weekend ~68) and live in data/quota_config.json, structured as:
    {"bases": {"B1": {"name", "weekday", "weekend"}, ...},
     "pizzas": {...}, "toppings": {...}}
Toppings carry a weekday/weekend of 999 — effectively unlimited in Stage 2; a
manual sold-out toggle per topping is planned for Stage 3.

QuotaManager holds the remaining-today count per item id in memory and resets
it whenever the IST calendar date rolls over. This is deliberately
SINGLE-PROCESS, in-memory state — fine for demonstrating sold-out behavior in
one Gradio process. Stage 3 replaces this with Supabase realtime so quota
stays consistent across multiple app instances/kitchen displays.

This module does file I/O (loading the config) but has no Gradio or core
coupling — app.py calls is_available()/consume() the same way it would call
any other plain-argument helper.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_RESET_POLL_SECONDS = 60


class QuotaConfigError(Exception):
    """Raised when quota_config.json is missing or malformed."""


def load_quota_config(path: str | Path) -> dict:
    """Load and parse quota_config.json. Raises QuotaConfigError on failure."""
    p = Path(path)
    if not p.exists():
        raise QuotaConfigError(f"Quota config file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise QuotaConfigError(f"Could not read quota config {p}: {exc}") from exc


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5  # Monday=0 ... Saturday=5, Sunday=6


class QuotaManager:
    """Tracks remaining-today stock per item id, reset at IST midnight.

    `config` is the parsed quota_config.json dict (category -> {item_id ->
    {"name", "weekday", "weekend"}}). The category names themselves don't
    matter to the manager; item ids are looked up across all categories.
    """

    def __init__(
        self,
        config: dict,
        *,
        today: Optional[date] = None,
        auto_reset: bool = False,
    ) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._remaining: Dict[str, int] = {}
        self._current_date = today or datetime.now(IST).date()
        self._reset_to(self._current_date)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if auto_reset:
            self.start_auto_reset()

    def _quota_for_day(self, entry: dict, day: date) -> int:
        return entry["weekend"] if _is_weekend(day) else entry["weekday"]

    def _reset_to(self, day: date) -> None:
        with self._lock:
            for category in self._config.values():
                for item_id, entry in category.items():
                    self._remaining[item_id] = self._quota_for_day(entry, day)
            self._current_date = day

    def is_available(self, item_id: str) -> bool:
        """True if at least one unit of item_id remains today."""
        with self._lock:
            return self._remaining.get(item_id, 0) > 0

    def remaining(self, item_id: str) -> int:
        """Remaining count for item_id today (0 if unknown)."""
        with self._lock:
            return self._remaining.get(item_id, 0)

    def all_remaining(self) -> Dict[str, int]:
        """Snapshot of every tracked item id's remaining-today count."""
        with self._lock:
            return dict(self._remaining)

    def consume(self, item_id: str) -> None:
        """Decrement remaining stock for item_id by 1 (floor at 0; no-op if untracked)."""
        with self._lock:
            if self._remaining.get(item_id, 0) > 0:
                self._remaining[item_id] -= 1

    def check_and_reset_if_new_day(self, *, now: Optional[datetime] = None) -> bool:
        """Reset all counts if the IST calendar date has rolled over.

        Accepts an injectable `now` so callers/tests can simulate a day
        change without sleeping until real midnight. Returns True if a reset
        happened.
        """
        today = (now or datetime.now(IST)).date()
        if today != self._current_date:
            self._reset_to(today)
            return True
        return False

    def start_auto_reset(self, poll_seconds: int = DEFAULT_RESET_POLL_SECONDS) -> None:
        """Start a background daemon thread that polls for the IST date
        rolling over and resets quota automatically at midnight IST."""
        if self._thread is not None:
            return

        def _loop() -> None:
            while not self._stop_event.wait(poll_seconds):
                self.check_and_reset_if_new_day()

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background reset thread, if running."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
