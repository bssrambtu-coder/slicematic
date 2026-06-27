"""
test_app.py — tests for app.py's testable (non-UI) logic.

build_ui()/main() launch a real Gradio server and are exercised manually
(see README "Run" section), not under pytest. Everything else — record
assembly, bill rendering, and the place_order orchestration that wires
core -> menu -> persistence — is plain Python and is covered here.
"""

from decimal import Decimal

import pytest

import app
import core
import menu


def _fake_menu():
    return {
        "base": [menu.MenuItem("B1", "Thin Crust", Decimal("149"))],
        "pizza": [menu.MenuItem("P1", "Margherita", Decimal("299"))],
        "topping": [menu.MenuItem("T1", "Black Olives", Decimal("49"))],
    }


@pytest.fixture
def wired_menu(monkeypatch, tmp_path):
    """Point app at a one-item fake menu and an isolated log file."""
    monkeypatch.setattr(app, "_MENU", _fake_menu())
    monkeypatch.setattr(app, "LOG_PATH", tmp_path / "orders_log.txt")
    return tmp_path / "orders_log.txt"


def test_build_order_record_has_all_log_fields():
    base = menu.MenuItem("B1", "Thin Crust", Decimal("149"))
    pizza = menu.MenuItem("P1", "Margherita", Decimal("299"))
    topping = menu.MenuItem("T1", "Black Olives", Decimal("49"))
    bill = core.price_order(base.price, pizza.price, topping.price, qty=2)

    record = app.build_order_record("Ravi Kumar", "9876543210", base, pizza, topping, bill, "Cash")

    import persistence

    assert set(persistence.LOG_FIELDS) <= set(record.keys())
    assert record["name"] == "Ravi Kumar"
    assert record["base_price"] == base.price
    assert record["final_total"] == bill.final_total


def test_render_bill_shows_final_total_and_payment_mode():
    base = menu.MenuItem("B1", "Thin Crust", Decimal("149"))
    pizza = menu.MenuItem("P1", "Margherita", Decimal("299"))
    topping = menu.MenuItem("T1", "Black Olives", Decimal("49"))
    bill = core.price_order(base.price, pizza.price, topping.price, qty=1)

    text = app.render_bill("Ravi Kumar", base, pizza, topping, bill, "UPI")

    assert "Ravi Kumar" in text
    assert core.format_money(bill.final_total) in text
    assert "UPI" in text


class TestPlaceOrderGoldenPath:
    def test_valid_order_is_priced_and_persisted(self, wired_menu):
        status, bill_text = app.place_order(
            "Ravi Kumar", "9876543210", "1", "1", "1", "2", "Cash"
        )
        assert status.startswith("✅")
        assert "Final total" in bill_text
        assert wired_menu.exists()
        assert "Ravi Kumar" in wired_menu.read_text(encoding="utf-8")

    def test_discount_qty_reflected_in_bill(self, wired_menu):
        status, bill_text = app.place_order(
            "Ravi Kumar", "9876543210", "1", "1", "1", str(core.DISCOUNT_THRESHOLD), "Card"
        )
        assert status.startswith("✅")
        assert "Discount: -₹0.00" not in bill_text


class TestPlaceOrderRejections:
    @pytest.mark.parametrize(
        "field_index,bad_value",
        [
            (0, ""),         # name blank
            (1, "123"),      # phone too short
            (2, "0"),        # base out of range
            (3, "9"),        # pizza out of range (only 1 item)
            (4, "abc"),      # topping non-numeric
            (5, "2.5"),      # qty decimal
            (6, "bitcoin"),  # payment invalid
        ],
    )
    def test_invalid_field_rejected_without_persisting(self, wired_menu, field_index, bad_value):
        args = ["Ravi Kumar", "9876543210", "1", "1", "1", "2", "Cash"]
        args[field_index] = bad_value

        status, bill_text = app.place_order(*args)

        assert status.startswith("❌")
        assert bill_text == ""
        assert not wired_menu.exists()
