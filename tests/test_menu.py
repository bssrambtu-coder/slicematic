"""
test_menu.py — parser tests.

Covers the PRD defensive-parsing contract (FR-3 / NFR 3.5 / edge case 8):
  * well-formed "ID;Name;Price" line -> MenuItem with Decimal price
  * leading/trailing whitespace and spaces around ';' tolerated
  * blank lines skipped
  * malformed line (missing price, extra field, non-numeric price) skipped,
    rest of file still loads
  * missing file -> MenuFileError naming the file
  * empty-after-parse file -> MenuFileError
  * no menu data hardcoded (parser works on a swapped/temp file)
"""

from decimal import Decimal

import pytest

import menu


def test_parse_well_formed_line():
    item = menu.parse_line("B1;Thin Crust;149")
    assert item == menu.MenuItem(item_id="B1", name="Thin Crust", price=Decimal("149"))


def test_parse_tolerates_whitespace_around_delimiter():
    item = menu.parse_line(" B1 ; Thin Crust ; 149 ")
    assert item == menu.MenuItem(item_id="B1", name="Thin Crust", price=Decimal("149"))


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\t  \t"])
def test_blank_lines_skipped(raw):
    assert menu.parse_line(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "B1;Thin Crust",          # missing price field
        "B1;Thin Crust;149;extra",  # extra field
        "B1;;149",                # empty name
        ";Thin Crust;149",        # empty id
        "B1;Thin Crust;",         # empty price
    ],
)
def test_malformed_line_returns_none(raw):
    assert menu.parse_line(raw) is None


def test_non_numeric_price_rejected():
    assert menu.parse_line("B1;Thin Crust;free") is None


def test_negative_price_rejected():
    assert menu.parse_line("B1;Thin Crust;-10") is None


def test_malformed_line_skipped_rest_loads(tmp_path):
    """Edge case 8: a line missing the price is skipped; the rest still loads."""
    f = tmp_path / "Types_of_Base.txt"
    f.write_text(
        "B1;Thin Crust;149\n"
        "B2;Thick Crust\n"          # malformed: missing price
        "\n"                        # blank line
        "B3;Cheese Burst;229\n",
        encoding="utf-8",
    )
    with pytest.warns(UserWarning):
        items = menu.load_menu_file(f)
    assert [i.item_id for i in items] == ["B1", "B3"]


def test_missing_file_raises_menu_error(tmp_path):
    missing = tmp_path / "Types_of_Base.txt"
    with pytest.raises(menu.MenuFileError, match="Types_of_Base.txt"):
        menu.load_menu_file(missing)


def test_empty_after_parse_raises_menu_error(tmp_path):
    f = tmp_path / "Types_of_Base.txt"
    f.write_text("garbage line\nanother;bad\n", encoding="utf-8")
    with pytest.warns(UserWarning):
        with pytest.raises(menu.MenuFileError):
            menu.load_menu_file(f)


def test_load_all_menus_on_swapped_files(tmp_path):
    """Parser works on grader-swapped temp files — nothing hardcoded."""
    (tmp_path / menu.BASE_FILE).write_text("B1;New Base;100\n", encoding="utf-8")
    (tmp_path / menu.PIZZA_FILE).write_text("P1;New Pizza;200\n", encoding="utf-8")
    (tmp_path / menu.TOPPINGS_FILE).write_text("T1;New Topping;30\n", encoding="utf-8")

    menus = menu.load_all_menus(tmp_path)

    assert set(menus.keys()) == {"base", "pizza", "topping"}
    assert menus["base"][0].name == "New Base"
    assert menus["pizza"][0].price == Decimal("200")
    assert menus["topping"][0].item_id == "T1"


def test_load_all_menus_raises_naming_missing_file(tmp_path):
    (tmp_path / menu.BASE_FILE).write_text("B1;New Base;100\n", encoding="utf-8")
    # Pizza and topping files intentionally absent.
    with pytest.raises(menu.MenuFileError, match=menu.PIZZA_FILE):
        menu.load_all_menus(tmp_path)


def test_format_menu_lines_numbered_and_priced():
    items = [
        menu.MenuItem("B1", "Thin Crust", Decimal("149")),
        menu.MenuItem("B2", "Thick Crust", Decimal("179")),
    ]
    lines = menu.format_menu_lines(items)
    assert lines[0].startswith("1. Thin Crust")
    assert "149.00" in lines[0]
    assert lines[1].startswith("2. Thick Crust")
    assert "179.00" in lines[1]


def test_real_data_files_load():
    """Sanity check against the actual shipped data/ files (real menu, not stub)."""
    from pathlib import Path

    repo_data_dir = Path(__file__).resolve().parent.parent / "data"
    menus = menu.load_all_menus(repo_data_dir)
    assert len(menus["base"]) > 0
    assert len(menus["pizza"]) > 0
    assert len(menus["topping"]) > 0
