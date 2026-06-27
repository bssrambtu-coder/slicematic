"""
test_quota.py — daily sold-out quota tests.

Covers: availability/consumption bookkeeping, weekend quota > weekday quota,
and the midnight-IST reset (simulated via an injected `now`, not real sleep).
"""

from datetime import datetime, date
from zoneinfo import ZoneInfo

import pytest

import quota


IST = ZoneInfo("Asia/Kolkata")


def _config():
    return {
        "bases": {
            "B1": {"name": "Thin Crust", "weekday": 2, "weekend": 5},
        },
        "toppings": {
            "T1": {"name": "Black Olives", "weekday": 999, "weekend": 999},
        },
    }


class TestAvailability:
    def test_available_when_remaining_positive(self):
        # 2026-06-29 is a Monday -> weekday quota (2).
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        assert qm.is_available("B1") is True
        assert qm.remaining("B1") == 2

    def test_unavailable_at_zero(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        qm.consume("B1")
        qm.consume("B1")
        assert qm.remaining("B1") == 0
        assert qm.is_available("B1") is False

    def test_unknown_item_id_is_unavailable(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        assert qm.is_available("B999") is False
        assert qm.remaining("B999") == 0


class TestConsume:
    def test_consume_decrements_by_one(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        qm.consume("B1")
        assert qm.remaining("B1") == 1

    def test_consume_never_goes_negative(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        for _ in range(5):
            qm.consume("B1")
        assert qm.remaining("B1") == 0

    def test_effectively_unlimited_topping_survives_many_consumes(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        for _ in range(50):
            qm.consume("T1")
        assert qm.is_available("T1") is True


class TestWeekendQuota:
    def test_weekend_quota_higher_than_weekday(self):
        weekday_qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))  # Monday
        weekend_qm = quota.QuotaManager(_config(), today=date(2026, 6, 28))  # Sunday
        assert weekday_qm.remaining("B1") == 2
        assert weekend_qm.remaining("B1") == 5
        assert weekend_qm.remaining("B1") > weekday_qm.remaining("B1")

    def test_saturday_also_gets_weekend_quota(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 27))  # Saturday
        assert qm.remaining("B1") == 5


class TestMidnightReset:
    def test_reset_restores_counts_on_new_day(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))  # Monday, quota 2
        qm.consume("B1")
        qm.consume("B1")
        assert qm.remaining("B1") == 0

        next_day = datetime(2026, 6, 30, 0, 0, 1, tzinfo=IST)  # Tuesday
        reset_happened = qm.check_and_reset_if_new_day(now=next_day)

        assert reset_happened is True
        assert qm.remaining("B1") == 2  # weekday quota restored

    def test_no_reset_within_same_day(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))
        qm.consume("B1")
        same_day_later = datetime(2026, 6, 29, 23, 0, 0, tzinfo=IST)
        reset_happened = qm.check_and_reset_if_new_day(now=same_day_later)

        assert reset_happened is False
        assert qm.remaining("B1") == 1

    def test_reset_switches_weekday_to_weekend_quota(self):
        qm = quota.QuotaManager(_config(), today=date(2026, 6, 29))  # Monday
        assert qm.remaining("B1") == 2
        saturday = datetime(2026, 7, 4, 0, 0, 1, tzinfo=IST)
        qm.check_and_reset_if_new_day(now=saturday)
        assert qm.remaining("B1") == 5


class TestLoadQuotaConfig:
    def test_loads_real_shipped_config(self):
        from pathlib import Path

        config_path = Path(__file__).resolve().parent.parent / "data" / "quota_config.json"
        config = quota.load_quota_config(config_path)
        assert "bases" in config and "pizzas" in config and "toppings" in config
        assert config["bases"]["B1"]["weekday"] == 15
        assert config["toppings"]["T1"]["weekday"] == 999

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(quota.QuotaConfigError):
            quota.load_quota_config(tmp_path / "missing.json")

    def test_malformed_json_raises(self, tmp_path):
        bad = tmp_path / "quota_config.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(quota.QuotaConfigError):
            quota.load_quota_config(bad)
