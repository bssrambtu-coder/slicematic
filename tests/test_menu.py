"""
test_menu.py — parser test SIGNATURES (skeleton).

OWNER: data-model teammate. Fill these in alongside menu.py. They are written
as `pytest.skip(...)` stubs so CI is GREEN now and turns into real coverage as
the parser is implemented. Remove each skip when you implement the test body.

Cover at minimum the PRD defensive-parsing contract (FR-3 / NFR 3.5 / edge 8):
  * well-formed "ID;Name;Price" line -> MenuItem with Decimal price
  * leading/trailing whitespace and spaces around ';' tolerated
  * blank lines skipped
  * malformed line (missing price, extra field, non-numeric price) skipped,
    rest of file still loads
  * missing file -> MenuFileError naming the file
  * empty-after-parse file -> MenuFileError
  * no menu data hardcoded (parser works on a swapped/temp file)
"""

import pytest

import menu


def test_parse_well_formed_line():
    pytest.skip("TODO(data teammate): parse 'B1;Thin Crust;149' -> MenuItem")


def test_parse_tolerates_whitespace_around_delimiter():
    pytest.skip("TODO: ' B1 ; Thin Crust ; 149 ' parses to the same MenuItem")


def test_blank_lines_skipped():
    pytest.skip("TODO: blank/whitespace-only lines return None from parse_line")


def test_malformed_line_skipped_rest_loads(tmp_path):
    pytest.skip("TODO(edge case 8): a line missing the price is skipped; others load")


def test_non_numeric_price_rejected():
    pytest.skip("TODO: 'B1;Thin Crust;free' is treated as malformed and skipped")


def test_missing_file_raises_menu_error(tmp_path):
    pytest.skip("TODO: load_menu_file on a missing path raises MenuFileError naming it")


def test_empty_after_parse_raises_menu_error(tmp_path):
    pytest.skip("TODO: a file with only malformed lines raises MenuFileError")


def test_load_all_menus_on_swapped_files(tmp_path):
    pytest.skip("TODO: parser works on grader-swapped temp files (nothing hardcoded)")
