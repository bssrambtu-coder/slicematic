# SliceMatic 🍕

A digital pizza-ordering MVP for a single outlet in New Ashok Nagar, East Delhi.
Stage 2 of the FDE applied project — a Gradio app over pure, tested Python
business logic. (Stage 3 adds an AI recommendation engine and a conversational
ordering agent that reuse this same `core.py`.)

## Quick start

```bash
cd slicematic
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest                 # run the test suite
python -m src.app      # launch the Gradio UI (after app.py is implemented)
```

Requires Python 3.11+.

## What it does

1. Collects a customer name and 10-digit mobile number (validated).
2. Loads the menu (base, pizza, topping) at runtime from `data/*.txt`.
3. Takes a quantity (1–10) and computes the bill:
   **unit price → subtotal → 10% discount if qty ≥ 5 → 18% GST → final total.**
4. Confirms a payment mode (Cash / Card / UPI).
5. Appends the completed order to `orders_log.txt` for later analytics.

## Repository layout

| Path | Purpose | Status |
|------|---------|--------|
| `src/core.py` | Pure validators + pricing/GST/discount engine | ✅ implemented + tested |
| `src/menu.py` | Defensive `ID;Name;Price` file parser | 🚧 skeleton |
| `src/persistence.py` | Append orders to `orders_log.txt` | 🚧 skeleton |
| `src/app.py` | Thin Gradio UI | 🚧 skeleton |
| `tests/test_core.py` | Edge-case harness (8 graded cases + pricing) | ✅ green |
| `tests/test_menu.py` | Parser test stubs | 🚧 skip stubs |
| `data/*.txt` | Swappable menu files | ✅ sample data |

## Menu data format

Each file is one item per line, semicolon-separated, INR integer price:

```
B1;Thin Crust;149
P1;Margherita;299
T1;Black Olives;49
```

**Nothing about the menu is hardcoded** — the parser reads these at runtime, and
the files can be swapped without touching code.

## Design notes

- All money uses `decimal.Decimal` — never float.
- Business rules (`DISCOUNT_THRESHOLD`, `DISCOUNT_RATE`, `GST_RATE`) are named
  constants in `core.py`, changeable without editing logic.
- `core.py` has **zero** UI or I/O coupling so the Stage 3 LLM agent can call the
  same validators and pricing engine directly.

See [CLAUDE.md](CLAUDE.md) for the full module contract and the rules the grader
enforces.
