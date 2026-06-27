# SliceMatic — Stage 2 (Gradio MVP)

Pizza ordering system for a single outlet. This repo is the Stage 2 MVP: a
Gradio UI over a pure, tested business-logic core. Stage 3 will add two AI
features that **reuse this code unchanged** — design choices here exist to make
that possible.

## Architecture — strict separation of concerns

```
app.py            ROOT entry point (Hugging Face Spaces requires app.py at
                  the repo root). Thin, state-driven CART-FLOW Gradio UI: per
                  combo (base -> pizza -> toppings[optional, Skip available]
                  -> qty -> Add to Cart), then Add Another Item / Remove Last
                  Item / Checkout from the cart. Back/Start-Over on every
                  step, sold-out filtering via quota, styled HTML bill,
                  Kitchen (Admin) tab. Calls core/menu/persistence/quota only.
                  Fully implemented.
src/
  core.py         PURE logic: validators + pricing/GST/discount.
                  NO Gradio, NO file I/O, NO input()/print(). Fully implemented & tested.
  menu.py         Defensive parser for the 3 menu .txt files. Does file I/O.  Fully implemented & tested.
  persistence.py  Appends completed orders to orders_log.txt.        Fully implemented & tested.
  quota.py        Daily per-item sold-out quota + midnight-IST reset. Fully implemented & tested.
tests/
  test_core.py        Full edge-case harness (8 graded cases + pricing + golden bill). GREEN.
  test_menu.py        Full parser test suite (malformed lines, missing files, swap test). GREEN.
  test_persistence.py Log read/write tests + phone-lookup hook. GREEN.
  test_quota.py        Availability/consume/weekend-quota/reset tests. GREEN.
data/             The 3 swappable menu files (ID;Name;Price) + quota_config.json.
```

**The golden rule:** all business rules live in `core.py`. menu/persistence/quota/app
must never re-derive validation, discount, or GST. The Stage 3 LLM agent will
call the same `core` validators and `core.price_order`/`core.price_cart` with
plain arguments.

**Cart pricing (`core.price_cart`):** an order can hold multiple combos
(base+pizza+toppings+qty each). Discount/GST are computed ONCE at the ORDER
level — on the cart's combined quantity across all combos, not any single
combo's qty — because the PRD's discount rule is explicitly "order-level".
`core.price_order`/`core.Bill` (single combo, no cart) are kept for backward
compatibility and still fully tested; `app.py` exclusively uses
`core.price_cart`/`core.CartBill` now that every order is cart-shaped (even a
one-combo order is just a one-line cart).

All modules are fully implemented and tested (134 tests passing), and the app
has been smoke-tested end-to-end with a real Playwright-driven browser — golden
path, the golden-bill dataset to the paisa, a multi-combo cart where the
order-level discount triggers on combined quantity even though no single
combo reached the threshold, "no toppings" via Skip, Back/Start-Over
preserving prior input, and sold-out filtering. Treat `core`'s
`Result`/`Bill`/`CartBill`/`CartLineBill` shapes, `menu`'s `MenuItem`/
`load_all_menus`/`MenuFileError`, `persistence`'s `LOG_FIELDS`/
`OrderLogError`, and `quota`'s `QuotaManager`/`QuotaConfigError` as stable
APIs — coordinate before changing them.

**Note on `app.py`'s location:** Hugging Face Spaces requires the entry point
at the repo root, so `app.py` lives there (not in `src/`) and adds `src/` to
`sys.path` itself. `src/menu.py`/`core.py`/`persistence.py`/`quota.py` still
import each other as flat top-level modules (`import core`, not `from . import
core`) — `pytest.ini`'s `pythonpath = src` makes that work for tests too.

## Hard rules from the PRD (the grader enforces these)

- **No hardcoded menu data.** Names/counts/prices are loaded from `data/*.txt`
  at runtime. The grader WILL swap these files.
- **Money is `decimal.Decimal`, never float.**
- **Tunable rules are named constants** in `core.py`: `DISCOUNT_THRESHOLD`,
  `DISCOUNT_RATE`, `GST_RATE`. The grader changes the discount threshold (5→3)
  live — never inline these numbers.
- **Fixed pricing order:** unit price → subtotal (×qty) → 10% discount if
  `qty ≥ DISCOUNT_THRESHOLD` → 18% GST on **post-discount** subtotal → final.
  For a multi-combo cart (`core.price_cart`), the same order applies but
  "qty" in the discount check is the cart's TOTAL quantity across all combos.
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

A cart checkout with N combos writes N rows sharing one `timestamp`+`name`+
`phone` (maps onto an `orders` + `order_line_items` schema). Each row's
`base_name`/`pizza_name`/`topping_name`/`qty`/`subtotal` is per-combo;
`discount`/`gst`/`final_total` are order-level and repeated identically
across all N rows — never `SUM()` those three when querying.

## Run

```bash
cd slicematic
pip install -r requirements.txt
pytest      # run the test suite
python app.py  # launch the Gradio app (entry point at repo root)
```
