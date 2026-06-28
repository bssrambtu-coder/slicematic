---
title: SliceMatic
emoji: 🍕
colorFrom: red
colorTo: yellow
sdk: gradio
sdk_version: 6.19.0
python_version: '3.13'
app_file: app.py
pinned: false
short_description: A Gradio pizza-ordering app with cart checkout
---

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

pytest          # run the test suite
python app.py   # launch the Gradio UI (app.py lives at the repo root — Hugging Face Spaces requires this)
```

Requires Python 3.11+.

## What it does

1. Collects a customer name and 10-digit mobile number (validated), one step
   at a time, with Back/Start-Over available on every step.
2. Loads the menu (base, pizza, topping) at runtime from `data/*.txt`.
3. **Cart flow** — for each combo: choose a base, a pizza, and any number of
   toppings (zero is fine — there's an explicit "Skip" as well as "Next" with
   nothing checked), then a quantity (1–10), then **Add to Cart**. From the
   cart you can **Add Another Item** (another base+pizza+toppings+qty combo),
   **Remove Last Item**, or **Checkout**.
4. At checkout, the WHOLE order is priced together:
   **per-combo unit price × qty → cart subtotal → 10% discount if the
   order's TOTAL quantity (summed across every combo) ≥ 5 → 18% GST → final
   total.** The discount is order-level on purpose — e.g. 3× one combo + 2× a
   different combo (5 total) still gets the discount, even though neither
   combo alone reached 5.
5. Filters out items that are sold out for the day (see Quota logic below) and
   greys them out as "Sold out today" instead of letting them be picked.
6. Confirms a payment mode (Cash / Card / UPI), renders a styled bill, then
   appends the completed order to `orders_log.txt` — one row per combo, all
   sharing the same timestamp/name/phone, for later analytics.
7. A separate **Kitchen (Admin)** tab shows remaining-today stock per item.

## Repository layout

| Path | Purpose | Status |
|------|---------|--------|
| `app.py` | Thin, state-driven cart-flow Gradio UI (root entry point, required by Hugging Face Spaces) | ✅ implemented + smoke-tested |
| `src/core.py` | Pure validators + per-combo and order-level (cart) pricing engine | ✅ implemented + tested |
| `src/menu.py` | Defensive `ID;Name;Price` file parser | ✅ implemented + tested |
| `src/persistence.py` | Append orders to `orders_log.txt` | ✅ implemented + tested |
| `src/quota.py` | Daily per-item sold-out quota + midnight-IST reset | ✅ implemented + tested |
| `tests/test_core.py` | Edge-case harness (8 graded cases + pricing + golden bill + cart pricing) | ✅ green |
| `tests/test_menu.py` | Parser test suite | ✅ green |
| `tests/test_persistence.py` | Order log read/write + phone lookup | ✅ green |
| `tests/test_quota.py` | Quota availability/consume/weekend/reset tests | ✅ green |
| `data/*.txt`, `data/quota_config.json` | Swappable menu + quota config | ✅ sample data |

134 tests pass. The app has been smoke-tested end-to-end via a real
browser (Playwright): golden path, the golden-bill dataset (₹229+₹379+₹69,
qty 5 → ₹3594.87 to the paisa), a multi-combo cart where the order-level
discount triggers on combined quantity, "no toppings" via Skip, Back/Start-Over
preserving prior input, sold-out filtering, and quota decrementing on order
placement.

## Quota / sold-out logic

`src/quota.py` tracks a remaining-today count per base/pizza id (toppings are
effectively unlimited at 999 in Stage 2 — a manual sold-out toggle per
topping is planned for Stage 3). Numbers in `data/quota_config.json` come from
the Stage 1 business-economics model: weekday average ~38 orders/day, weekend
~68. Weekend quotas are higher than weekday for every base and pizza.
Quota resets automatically at midnight **IST** (`zoneinfo("Asia/Kolkata")`),
checked by a background daemon thread — no extra scheduler dependency needed.
This is single-process, in-memory state, which is fine for demonstrating
sold-out behavior in one Gradio process; Stage 3 replaces it with Supabase
realtime so kitchen stock stays consistent across multiple app instances.

Quota is consumed **proportional to quantity** at checkout (`QuotaManager.
consume(item_id, count=qty)`), not once per combo — ordering qty=10 of a
pizza decrements its stock by 10, not 1. While a cart is still being built
(before checkout), each combo's availability/stock check is computed net of
whatever the SAME unpaid cart has already reserved for that item
(`_effective_remaining` in `app.py`), so ordering the same near-sold-out item
across two different combos in one order can't oversell it just because
quota itself hasn't been decremented yet. Separately, the outlet's 10-pizza
cap (`core.MAX_QTY`) applies to the whole ORDER's combined quantity across
every combo (`core.validate_cart_total_quantity`), not any single combo.

## Stage 3 direction

- A web app (not a mobile app) on **Vercel**, backed by **Supabase** for
  persistence and realtime sync (replacing the flat `orders_log.txt` and the
  single-process `QuotaManager`).
- **AI Option A** — a recommendation engine that looks up a customer's past
  orders by phone via `persistence.find_orders_by_phone`.
- **AI Option B** — a conversational ordering agent that calls the exact same
  `core.py` validators and `core.price_order`, unchanged.
- Real cross-app kitchen sync (today's `quota.py` is single-process; Stage 3
  needs it visible across devices).

## Menu data format

Each file is one item per line, semicolon-separated, INR integer price:

```
B1;Thin Crust;149
P1;Margherita;299
T1;Black Olives;49
```

**Nothing about the menu is hardcoded** — the parser reads these at runtime, and
the files can be swapped without touching code.

## Order log format

Pipe-separated, one order block per record, blank line between blocks. Field
order is fixed (`persistence.LOG_FIELDS`):

```
timestamp | name | phone | base_name | base_price | pizza_name | pizza_price |
topping_name | topping_price | qty | subtotal | discount | gst | final_total | payment_mode
```

`phone` is the customer key — `persistence.find_orders_by_phone` is the
Stage 3 Option-A (recommendation engine) lookup hook.

**Multi-combo orders write multiple rows.** A cart checkout with N combos
writes N rows, all sharing the same `timestamp`+`name`+`phone` (that's how a
Stage 3 importer groups them back into one order — they map one-to-one onto
an `orders` + `order_line_items` relational schema). Each row's own
`base_name`/`pizza_name`/`topping_name`/`qty`/`subtotal` is that COMBO's;
`discount`/`gst`/`final_total` are ORDER-level and are repeated identically
on every row of that order — don't `SUM()` those three across rows when
querying, only `subtotal`.

## Design notes

- All money uses `decimal.Decimal` — never float.
- Business rules (`DISCOUNT_THRESHOLD`, `DISCOUNT_RATE`, `GST_RATE`) are named
  constants in `core.py`, changeable without editing logic.
- `core.py` has **zero** UI or I/O coupling so the Stage 3 LLM agent can call the
  same validators and pricing engine directly.

See [CLAUDE.md](CLAUDE.md) for the full module contract and the rules the grader
enforces.
