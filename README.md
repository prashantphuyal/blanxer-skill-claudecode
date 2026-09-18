# blanxer-skill

A [Claude Code](https://claude.com/claude-code) **skill** for end-to-end automation of a [Blanxer](https://blanxer.com) vendor store (`app.blanxer.com`) via direct HTTP against the Blanxer API — no browser tab, no dashboard clicking.

Drop it into `~/.claude/skills/` and it activates whenever you mention Blanxer, products, orders, inventory, barcodes, or analytics on a Blanxer store.

---

## What it covers

- **Products & inventory** — bulk upload from CSV, Excel, or paired handwritten bill images (printed invoice for cost + notebook for selling price); per-outlet stock-in; write-off with all 7 subtypes (`DAMAGED / EXPIRED / LOST / THEFT / COUNT_CORRECTION / PURCHASE_RETURN / SYSTEM_FIX`); transfer between outlets; count corrections; clean product delete with the write-off-first orphan-stock recipe.
- **Barcode labels** — auto-generated PDF at end of upload (one page per unit on-hand), plus an on-demand reprint script (by product ID or name substring, simple or by-quantity mode).
- **Image uploads** — multipart with server-side WebP auto-conversion; aspect-ratio aware (fetches `customization.image_ratio` from the store).
- **Product tags** — the full special-tag vocabulary (`coming_soon`, `no_price`, `main`, `team_order`, `show_color_chips`, `mirrago_tryon`, `rd_`/`ard_` redirect buttons, `key:value` and `seller:<name>` facets); set at upload time from a CSV column or a whole-run env var, or bulk add/remove/replace across the catalogue afterwards — with the read-merge-write that stops the full-replace endpoint from wiping custom fields.
- **Catalog metadata** — categories (fetch-once cached, never auto-create), suppliers (search/create with the honest "supplier_ref is free-text only, not linked to stock-in" caveat).
- **Orders** — admin/POS/lead create with custom line items, edit-items, status/payment updates, bulk status (with Group1/Group2 rule), delete guards.
- **Transactions & payments** — list, settlement history, subscription lookup, plus the "no date-filter on transaction list" limitation baked in.
- **Analytics & reporting** — daily overview, sales-by-{product,location,staff,payment}, inventory-value, expenses-by-category, profit-loss, POS shift reconciliation.
- **Store config** — plan detection (`pos / basic / premium / platinum / plus` vs free tier), delivery-charge matrix (Platinum-only, 6 weight tiers × per-district).

---

## Prerequisites

- **Claude Code** installed and set up
- **A Blanxer API key** — generate one from your Blanxer dashboard: **Store Setting → API Key**. It's a 59-char string starting with `sk_` and embeds your store's Mongo `_id` in chars 3..27.
- **Python 3.9+** (only stdlib — no external dependencies)
- **macOS or Linux** (scripts use `curl`-style HTTP; `sips` referenced for image cropping is macOS-only, replaceable with Pillow/ImageMagick on Linux)

The API key is the **only** supported auth method. Session bearer tokens, DevTools localStorage tokens, and Chrome-tab injection are all deprecated by this skill.

---

## Install

```bash
git clone https://github.com/prashantphuyal/blanxer-skill-claudecode.git ~/.claude/skills/blanxer-skill
```

Then in Claude Code, type `/blanxer-skill` (or just mention Blanxer in your prompt).

To verify it loaded, ask Claude "list my available skills" — you should see `blanxer-skill` in the list.

---

## Usage

The skill exposes three turnkey scripts under `scripts/`. All take the API key via env var so it stays out of shell history and disk.

### Bulk product upload + auto-generate barcode PDF

```bash
BLANXER_API_KEY='sk_your59charKeyHere...' \
BLANXER_OUTLET_ID='<outlet_id>' \
BLANXER_CSV='./products.csv' \
python3 ~/.claude/skills/blanxer-skill/scripts/upload_direct_http.py
```

CSV format (the `tags` column is optional):

```csv
product_name,qty,cost_rate,selling_rate,tags
"1. sall set",45,1460,2400,"seller:acme;color:red"
"2. sall set",20,2236,3800,coming_soon
```

Row tags are semicolon- or pipe-separated — not comma, so plain CSV stays safe.

Optional env vars:
- `BLANXER_CHANNEL` (default `3` = POS; `1` = All, `2` = Website)
- `BLANXER_DELAY_S` (default `3.0` seconds between products)
- `BLANXER_TAGS` (comma-separated tags applied to every product in the run, e.g. `'seller:acme,brand:nike'`)
- `BLANXER_BARCODE_PDF` (default `<CSV dir>/barcodes.pdf`; set to `""` to skip PDF generation)

After the loop, the script emits a barcode PDF (one page per unit of live stock, product name on top, no store name — see label defaults below).

### Manage product tags in bulk

Tags carry real behaviour in Blanxer — `coming_soon`, `no_price`, `main`, `team_order`, `show_color_chips`, `mirrago_tryon`, the `rd_`/`ard_` redirect buttons, and the `key:value` / `seller:<name>` filter facets. `manage_tags.py` edits them across the catalogue:

```bash
# See what's tagged today
BLANXER_API_KEY='sk_...' python3 ~/.claude/skills/blanxer-skill/scripts/manage_tags.py list

# Dry run: what would change
BLANXER_API_KEY='sk_...' python3 ~/.claude/skills/blanxer-skill/scripts/manage_tags.py \
  add "seller:acme" --all

# Commit it
BLANXER_API_KEY='sk_...' python3 ~/.claude/skills/blanxer-skill/scripts/manage_tags.py \
  add "seller:acme" --all --apply

# Narrower selectors
... manage_tags.py add "coming_soon" --name-contains "diwali" --apply
... manage_tags.py remove "coming_soon" --has-tag coming_soon --apply
... manage_tags.py set "brand:nike,main" --ids 66f...,66f... --apply
```

Modes: `list`, `add` (union), `remove` (subtract), `set` (replace the array). Selectors `--all`, `--ids`, `--name-contains`, `--has-tag`, `--channel` AND together. Nothing is written without `--apply`; the dry run prints a before → after diff per product.

Why a script rather than one curl: the tag endpoint (`POST /product/custom_fields/{store_id}/{product_id}`) is a **full replace** whose `custom_fields` and `similar_products` both default to `[]`, so a naive tags-only POST erases them. The script reads each product first and echoes all three arrays back.

### Reprint barcodes on demand

By product ID list:

```bash
BLANXER_API_KEY='sk_...' \
BLANXER_PRODUCT_IDS='6a5dd1305771b8b9d1c017aa,6a5dd1335771b8b9d1c0194a' \
python3 ~/.claude/skills/blanxer-skill/scripts/reprint_barcodes.py
```

By product name substring (fetches from `/product/pos/{store_id}` and filters client-side):

```bash
BLANXER_API_KEY='sk_...' \
BLANXER_PRODUCT_QUERY='sall set' \
python3 ~/.claude/skills/blanxer-skill/scripts/reprint_barcodes.py
```

For a specific label count per product (by-quantity mode), pass `BLANXER_QUANTITIES` as a JSON map:

```bash
BLANXER_API_KEY='sk_...' \
BLANXER_PRODUCT_IDS='6a00...79' \
BLANXER_QUANTITIES='{"6a00...79": 10}' \
python3 ~/.claude/skills/blanxer-skill/scripts/reprint_barcodes.py
```

Default label flags: `show_name=true`, `show_store=false`, `show_price=true`, `show_barcode=true`. Override any with:

```bash
BLANXER_LABEL_FLAGS='{"show_store":"true","show_variant":"true"}'
```

---

## How it works — internals worth knowing

- **Auth exchange**: `POST /api-key/check` with the raw `sk_...` returns `{store: {...}, token: <JWT>}`. The JWT is used as `Authorization: Bearer …` for every subsequent call.
- **Cloudflare shielding**: the entire `api.blanxer.com` surface (including `/api-key/check`) is gated by Cloudflare's browser-fingerprint challenge. All scripts send `User-Agent`, `Origin: https://app.blanxer.com`, `Referer: https://app.blanxer.com/`, and `Accept` on every request. Without these you get `403 error code: 1010`.
- **Advanced vs simple inventory**: Platinum-only stores can enable advanced inventory (`use_advanced_inventory && website_outlet` both required for detection). In advanced mode, product-create `quantity` is forced to 0 and stock must enter via `stock-in`. In simple mode, `quantity` in the create body is applied directly. The skill branches automatically.
- **Barcode PDF**: two-step flow (`POST /order/print_request/{store_id}` with `print_for: 2` → `GET /product/generate_barcode_quantity/{store_id}/{print_id}` with a URL-encoded `quantities` map). Cloudflare gates both the POST and the GET.
- **Server-side image conversion**: any raster image you upload (JPG/PNG/HEIC) is auto-converted to WebP quality 95 via `sharp` on the server. Don't pre-convert. SVG passes through untouched.
- **Product delete does NOT cascade**: `DELETE /product/{store_id}/{product_id}` only removes the Product doc — Batches, StockLedger entries, and `inventory_summary` stay behind. The skill's built-in recipe writes off remaining stock per-outlet (`subtype: SYSTEM_FIX`) first, then deletes.

Full endpoint reference (100+ routes across products, orders, transactions, analytics, POS, inventory) lives in `references/api.md`.

---

## Files

```
blanxer-skill/
├── SKILL.md                        # Main skill definition — loads into Claude Code context
├── README.md                       # This file
├── references/
│   └── api.md                      # Complete Blanxer API reference (routes, payloads, enums, gotchas)
└── scripts/
    ├── upload_direct_http.py       # Bulk upload (+ tags) + auto barcode PDF
    ├── manage_tags.py              # Bulk add/remove/replace product tags
    ├── reprint_barcodes.py         # On-demand label reprint
    └── upload_loop.js              # Legacy browser-tab injection (deprecated, kept for reference)
```

---

## Security notes

- **Never commit an `sk_` API key** to any repo. The skill's scripts read the key from `BLANXER_API_KEY` env var only — nothing writes it to disk.
- The exchanged JWT stays in a Python variable for the lifetime of the script process; if you rely on `/tmp/*.json` scratch files, make sure the path is under your own `$TMPDIR` (which is `/tmp` on macOS, wiped on reboot).
- The 24 hex characters at positions 3..27 of your API key are your store's Mongo `_id`. Treat the key itself as a secret.

---

## Contributing

This is a personal automation skill originally built for a specific store's workflow (handwritten bill entry → API upload → label printing). PRs that generalize or fix bugs are welcome. Issues are enabled for reporting API drift.

---

## License

No license attached yet. Treat this repo as source-available for personal reference until a license is added. The Blanxer API itself is owned by Blanxer Technology Pvt. Ltd. — you must have a valid Blanxer account and be authorized to access your store's data.
