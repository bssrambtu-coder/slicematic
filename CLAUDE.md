# SliceMatic — Stage 2 (Gradio MVP)

Pizza ordering system for a single outlet. This repo is the Stage 2 MVP: a
Gradio UI over a pure, tested business-logic core. Stage 3 will add two AI
features that **reuse this code unchanged** — design choices here exist to make
that possible.

## Architecture — strict separation of concerns

```
src/
  core.py         PURE logic: validators + pricing/GST/discount.
                  NO Gradio, NO file I/O, NO input()/print(). Fully implemented & tested.
  menu.py         Defensive parser for the 3 menu .txt files. Does file I/O.  Fully implemented & tested.
  persistence.py  Appends completed orders to orders_log.txt.        Fully implemented & tested.
  app.py          THIN Gradio UI. Calls core/menu/persistence only.  Fully implemented & tested.
tests/
  test_core.py        Full edge-case harness (the 8 graded cases + pricing). GREEN.
  test_menu.py        Full parser test suite (malformed lines, missing files, swap test). GREEN.
  test_persistence.py Log read/write tests + phone-lookup hook. GREEN.
  test_app.py          place_order orchestration + helper tests. GREEN.
data/             The 3 swappable menu files (ID;Name;Price).
```

**The golden rule:** all business rules live in `core.py`. menu/persistence/app
must never re-derive validation, discount, or GST. The Stage 3 LLM agent will
call the same `core` validators and `core.price_order` with plain arguments.

All four modules are now fully implemented and tested (117 tests passing),
and the app has been smoke-tested end-to-end against the real `data/` files —
golden path and all 8 PRD edge cases verified live via `gradio_client` against
a running server. Treat `core`'s `Result`/`Bill` shapes, `menu`'s `MenuItem`/
`load_all_menus`/`MenuFileError`, and `persistence`'s `LOG_FIELDS`/
`OrderLogError` as stable APIs — coordinate before changing them.

## Hard rules from the PRD (the grader enforces these)

- **No hardcoded menu data.** Names/counts/prices are loaded from `data/*.txt`
  at runtime. The grader WILL swap these files.
- **Money is `decimal.Decimal`, never float.**
- **Tunable rules are named constants** in `core.py`: `DISCOUNT_THRESHOLD`,
  `DISCOUNT_RATE`, `GST_RATE`. The grader changes the discount threshold (5→3)
  live — never inline these numbers.
- **Fixed pricing order:** unit price → subtotal (×qty) → 10% discount if
  `qty ≥ DISCOUNT_THRESHOLD` → 18% GST on **post-discount** subtotal → final.
- **Validation rules:** name = alpha+spaces, 2–40, no whitespace-only; phone =
  10 digits starting 6/7/8/9; qty = integer 1–10 (reject 0, >10, negatives,
  decimals, words); menu pick = integer in `[1, len]`; payment = Cash/Card/UPI.
- **No unhandled exception may reach the user.** Validators return
  `Result(ok, message, value)` and never raise on bad user input. Every failure
  message says what was wrong AND what's acceptable.
- **Graceful failure:** missing menu file → clear message naming it, exit
  cleanly (no traceback); malformed line → skip with warning, rest loads; empty
  menu → refuse to start; log-write failure → surface it, never lose the order.

## orders_log.txt format (fixed — Stage 3 importer depends on it)

Pipe-separated, one order block per record, blank line between blocks. Fields in
EXACT order (`persistence.LOG_FIELDS`):

```
timestamp | name | phone | base_name | base_price | pizza_name | pizza_price |
topping_name | topping_price | qty | subtotal | discount | gst | final_total | payment_mode
```

`phone` is the customer key — the Stage 3 recommendation engine looks up past
orders by phone via `persistence.find_orders_by_phone`.

## Run

```bash
cd slicematic
pip install -r requirements.txt
pytest            # run the test suite
python -m src.app # launch the Gradio app (once app.py is implemented)
```
