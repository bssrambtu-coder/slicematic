"""
test_persistence.py — order log read/write tests.

Covers PRD 3.4 (fixed pipe-delimited format, blank line between blocks),
NFR 3.5 (log-write failure surfaces, never silently lost), and the Stage 3
phone-lookup hook (Option A).
"""

from decimal import Decimal

import pytest

import persistence


def _sample_order(phone="9876543210", **overrides):
    order = {
        "timestamp": "2026-06-27T10:00:00+00:00",
        "name": "Ravi Kumar",
        "phone": phone,
        "base_name": "Thin Crust",
        "base_price": Decimal("149"),
        "pizza_name": "Margherita",
        "pizza_price": Decimal("299"),
        "topping_name": "Black Olives",
        "topping_price": Decimal("49"),
        "qty": 2,
        "subtotal": Decimal("994.00"),
        "discount": Decimal("0.00"),
        "gst": Decimal("178.92"),
        "final_total": Decimal("1172.92"),
        "payment_mode": "Cash",
    }
    order.update(overrides)
    return order


class TestFormatRecord:
    def test_renders_fields_in_exact_order_pipe_delimited(self):
        line = persistence.format_record(_sample_order())
        parts = line.split("|")
        assert len(parts) == len(persistence.LOG_FIELDS)
        assert parts[1] == "Ravi Kumar"
        assert parts[2] == "9876543210"

    def test_decimal_fields_rendered_to_two_places(self):
        line = persistence.format_record(_sample_order(base_price=Decimal("149")))
        assert "149.00" in line

    def test_missing_field_raises(self):
        order = _sample_order()
        del order["payment_mode"]
        with pytest.raises(persistence.OrderLogError):
            persistence.format_record(order)

    def test_delimiter_in_field_value_raises(self):
        order = _sample_order(name="Ravi|Kumar")
        with pytest.raises(persistence.OrderLogError):
            persistence.format_record(order)


class TestAppendOrder:
    def test_first_write_creates_file_with_single_record(self, tmp_path):
        log = tmp_path / "orders_log.txt"
        persistence.append_order(_sample_order(), log)
        content = log.read_text(encoding="utf-8")
        assert content.count("\n\n") == 0
        assert content.strip().count("\n") == 0  # exactly one line

    def test_second_write_separated_by_blank_line(self, tmp_path):
        log = tmp_path / "orders_log.txt"
        persistence.append_order(_sample_order(name="First Customer"), log)
        persistence.append_order(_sample_order(name="Second Customer"), log)
        content = log.read_text(encoding="utf-8")
        blocks = content.strip().split("\n\n")
        assert len(blocks) == 2
        assert "First Customer" in blocks[0]
        assert "Second Customer" in blocks[1]

    def test_write_failure_raises_order_log_error(self, tmp_path):
        # A directory path can never be opened for append -> OSError.
        bad_path = tmp_path  # tmp_path is a directory, not a file
        with pytest.raises(persistence.OrderLogError):
            persistence.append_order(_sample_order(), bad_path)


class TestFindOrdersByPhone:
    def test_no_file_returns_empty_list(self, tmp_path):
        missing = tmp_path / "orders_log.txt"
        assert persistence.find_orders_by_phone("9876543210", missing) == []

    def test_finds_matching_records_and_restores_types(self, tmp_path):
        log = tmp_path / "orders_log.txt"
        persistence.append_order(_sample_order(phone="9876543210"), log)
        persistence.append_order(_sample_order(phone="8000000000"), log)
        persistence.append_order(_sample_order(phone="9876543210", name="Repeat Customer"), log)

        matches = persistence.find_orders_by_phone("9876543210", log)
        assert len(matches) == 2
        assert all(m["phone"] == "9876543210" for m in matches)
        assert isinstance(matches[0]["final_total"], Decimal)
        assert isinstance(matches[0]["qty"], int)
        assert matches[1]["name"] == "Repeat Customer"

    def test_no_match_returns_empty_list(self, tmp_path):
        log = tmp_path / "orders_log.txt"
        persistence.append_order(_sample_order(phone="9876543210"), log)
        assert persistence.find_orders_by_phone("6000000000", log) == []

    def test_malformed_record_skipped_with_warning(self, tmp_path):
        log = tmp_path / "orders_log.txt"
        log.write_text("not|enough|fields\n", encoding="utf-8")
        with pytest.warns(UserWarning):
            matches = persistence.find_orders_by_phone("9876543210", log)
        assert matches == []
