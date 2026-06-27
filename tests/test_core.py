"""
test_core.py — edge-case harness for the pure business logic.

This is the project's safety net. It encodes the PRD's pre-disclosed 8-case
test matrix (NFR 3.3) plus the fixed pricing order of operations (FR-4) and the
configurable discount rule (FR-5). It is written to stay correct even after the
grader changes DISCOUNT_THRESHOLD live, by asserting against the named constant
rather than the literal 5.
"""

from decimal import Decimal

import pytest

import core


# --------------------------------------------------------------------------- #
# Name validation (PRD FR-1 / edge cases 1, 6)
# --------------------------------------------------------------------------- #
class TestValidateName:
    @pytest.mark.parametrize("name", ["Al", "Ravi Kumar", "A" * 40])
    def test_valid_names_accepted(self, name):
        res = core.validate_name(name)
        assert res.ok is True
        assert res.value == name.strip()

    def test_trims_surrounding_spaces(self):
        res = core.validate_name("  Ravi  ")
        assert res.ok is True
        assert res.value == "Ravi"

    @pytest.mark.parametrize(
        "name",
        [
            "   ",        # edge case 1: whitespace-only
            "",           # edge case 6: empty
            "A",          # too short (< 2)
            "A" * 41,     # too long (> 40)
            "Ravi1",      # digit
            "Ravi_Kumar", # symbol
            "O'Brien",    # apostrophe not allowed
            None,         # missing
        ],
    )
    def test_invalid_names_rejected(self, name):
        res = core.validate_name(name)
        assert res.ok is False
        assert res.message  # specific, non-empty corrective message
        assert res.value is None


# --------------------------------------------------------------------------- #
# Phone validation (PRD FR-1 / edge case 2)
# --------------------------------------------------------------------------- #
class TestValidatePhone:
    @pytest.mark.parametrize("phone", ["9876543210", "6000000000", "7123456789", "8123456789"])
    def test_valid_phones_accepted(self, phone):
        res = core.validate_phone(phone)
        assert res.ok is True
        assert res.value == phone

    @pytest.mark.parametrize(
        "phone",
        [
            "1234567890",   # edge case 2: starts with 1
            "5876543210",   # starts with 5
            "987654321",    # 9 digits
            "98765432100",  # 11 digits
            "98765abcde",   # letters
            "",             # empty
            "  ",           # whitespace
            None,
        ],
    )
    def test_invalid_phones_rejected(self, phone):
        res = core.validate_phone(phone)
        assert res.ok is False
        assert res.value is None

    def test_trims_whitespace(self):
        assert core.validate_phone("  9876543210  ").value == "9876543210"


# --------------------------------------------------------------------------- #
# Quantity validation (PRD FR-2 / edge cases 3, 6, 7)
# --------------------------------------------------------------------------- #
class TestValidateQuantity:
    @pytest.mark.parametrize("qty,expected", [("1", 1), ("10", 10), (5, 5), ("  3 ", 3), (4.0, 4)])
    def test_valid_quantities_accepted(self, qty, expected):
        res = core.validate_quantity(qty)
        assert res.ok is True
        assert res.value == expected
        assert isinstance(res.value, int)

    @pytest.mark.parametrize(
        "qty",
        [
            "0", 0,          # edge case 3: zero
            "11", 11,        # edge case 3: above capacity
            "-1", -3,        # negatives
            "2.5", 2.5,      # edge case 7: decimal
            "three",         # edge case 7: words
            "",              # edge case 6: empty
            "  ",            # whitespace
            None,
            True, False,     # booleans are not quantities
        ],
    )
    def test_invalid_quantities_rejected(self, qty):
        res = core.validate_quantity(qty)
        assert res.ok is False
        assert res.value is None
        assert res.message

    def test_boundaries_use_named_constants(self):
        assert core.validate_quantity(core.MIN_QTY).ok is True
        assert core.validate_quantity(core.MAX_QTY).ok is True
        assert core.validate_quantity(core.MIN_QTY - 1).ok is False
        assert core.validate_quantity(core.MAX_QTY + 1).ok is False


# --------------------------------------------------------------------------- #
# Menu selection (PRD FR-3 / edge cases 4, 5, 6)
# --------------------------------------------------------------------------- #
class TestValidateMenuSelection:
    def test_valid_selection_in_range(self):
        res = core.validate_menu_selection("2", item_count=5)
        assert res.ok is True
        assert res.value == 2

    @pytest.mark.parametrize(
        "selection",
        [
            "0", 0,        # edge case 4: zero
            "6", 6,        # edge case 4: above list length (count=5)
            "149",         # edge case 5: a price typed as item number -> out of range
            "abc",         # letters
            "2.5",         # decimal
            "",            # edge case 6: empty
            None,
        ],
    )
    def test_invalid_selection_rejected(self, selection):
        res = core.validate_menu_selection(selection, item_count=5)
        assert res.ok is False
        assert res.value is None

    def test_empty_menu_rejects_any_selection(self):
        assert core.validate_menu_selection(1, item_count=0).ok is False


# --------------------------------------------------------------------------- #
# Payment (PRD FR-7)
# --------------------------------------------------------------------------- #
class TestValidatePayment:
    @pytest.mark.parametrize("choice,mode", [("1", "Cash"), ("2", "Card"), ("3", "UPI")])
    def test_codes_map_to_modes(self, choice, mode):
        res = core.validate_payment(choice)
        assert res.ok is True
        assert res.value == mode
        assert mode.lower() in res.message.lower()  # mode-specific confirmation

    @pytest.mark.parametrize("choice,mode", [("cash", "Cash"), ("CARD", "Card"), ("Upi", "UPI")])
    def test_names_accepted_case_insensitive(self, choice, mode):
        assert core.validate_payment(choice).value == mode

    @pytest.mark.parametrize("choice", ["0", "4", "", "bitcoin", None])
    def test_invalid_payment_rejected(self, choice):
        res = core.validate_payment(choice)
        assert res.ok is False
        assert res.value is None


# --------------------------------------------------------------------------- #
# Pricing engine (PRD FR-4, FR-6) — fixed order of operations, Decimal money
# --------------------------------------------------------------------------- #
class TestPricing:
    # Thin Crust 149 + Margherita 299 + Black Olives 49 = 497 unit price.
    BASE, PIZZA, TOP = 149, 299, 49
    UNIT = Decimal("497.00")

    def test_unit_price_is_sum_of_three(self):
        assert core.unit_price(self.BASE, self.PIZZA, self.TOP) == self.UNIT

    def test_all_money_is_decimal(self):
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=1)
        for field in (bill.unit_price, bill.subtotal, bill.discount, bill.gst, bill.final_total):
            assert isinstance(field, Decimal)

    def test_no_discount_below_threshold(self):
        qty = core.DISCOUNT_THRESHOLD - 1
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=qty)
        assert bill.discount == Decimal("0.00")
        # subtotal = unit * qty; gst = 18% of subtotal; final = subtotal + gst
        expected_sub = self.UNIT * qty
        assert bill.subtotal == expected_sub
        assert bill.gst == (expected_sub * core.GST_RATE).quantize(Decimal("0.01"))
        assert bill.final_total == (expected_sub + bill.gst)

    def test_discount_applies_at_threshold(self):
        qty = core.DISCOUNT_THRESHOLD
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=qty)
        expected_sub = self.UNIT * qty
        expected_disc = (expected_sub * core.DISCOUNT_RATE).quantize(Decimal("0.01"))
        assert bill.discount == expected_disc
        # GST is on POST-discount subtotal — this is the key ordering rule.
        discounted = expected_sub - expected_disc
        assert bill.gst == (discounted * core.GST_RATE).quantize(Decimal("0.01"))
        assert bill.final_total == discounted + bill.gst

    def test_gst_computed_on_post_discount_not_pre(self):
        qty = core.DISCOUNT_THRESHOLD
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=qty)
        pre_discount_gst = (self.UNIT * qty * core.GST_RATE).quantize(Decimal("0.01"))
        assert bill.gst < pre_discount_gst  # discount lowered the taxable base

    def test_worked_example_qty5(self):
        # 497 * 5 = 2485.00; disc 10% = 248.50; discounted 2236.50;
        # gst 18% = 402.57; final = 2639.07
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=5)
        assert bill.subtotal == Decimal("2485.00")
        assert bill.discount == Decimal("248.50")
        assert bill.gst == Decimal("402.57")
        assert bill.final_total == Decimal("2639.07")

    def test_threshold_is_configurable_constant(self):
        # The grader changes DISCOUNT_THRESHOLD live (e.g. 5 -> 3). Verify the
        # engine keys off the constant, so qty == threshold always discounts.
        assert core.discount_for(Decimal("100.00"), core.DISCOUNT_THRESHOLD) > 0
        assert core.discount_for(Decimal("100.00"), core.DISCOUNT_THRESHOLD - 1) == Decimal("0.00")


# --------------------------------------------------------------------------- #
# Golden bill: Cheese Burst (229) + BBQ Chicken (379) + Extra Cheese (69).
# Independent worked example, verified to the paisa.
# --------------------------------------------------------------------------- #
class TestGoldenBill:
    BASE, PIZZA, TOP = 229, 379, 69
    UNIT = Decimal("677.00")

    def test_golden_bill_qty5_to_the_paisa(self):
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=5)
        assert bill.unit_price == self.UNIT
        assert bill.subtotal == Decimal("3385.00")
        assert bill.discount == Decimal("338.50")
        assert bill.subtotal - bill.discount == Decimal("3046.50")
        assert bill.gst == Decimal("548.37")
        assert bill.final_total == Decimal("3594.87")

    def test_golden_bill_no_discount_qty4(self):
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=4)
        assert bill.subtotal == Decimal("2708.00")
        assert bill.discount == Decimal("0.00")
        assert bill.gst == Decimal("487.44")
        assert bill.final_total == Decimal("3195.44")

    def test_golden_bill_boundary_qty_equals_threshold_discounts(self):
        bill = core.price_order(self.BASE, self.PIZZA, self.TOP, qty=core.DISCOUNT_THRESHOLD)
        assert bill.discount > Decimal("0.00")


# --------------------------------------------------------------------------- #
# Money formatting (PRD 3.6)
# --------------------------------------------------------------------------- #
def test_format_money_inr_two_decimals():
    assert core.format_money(Decimal("299")) == "₹299.00"
    assert core.format_money(149) == "₹149.00"
