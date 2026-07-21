---
name: blanxer-skill
description: End-to-end automation for a Blanxer vendor store (app.blanxer.com) via direct API. Covers bulk product upload from CSV/Excel/paired bill images (printed BILL FORM + handwritten notebook selling prices), per-outlet Main Branch/Branch B outlet; asks to add/upload/import/adjust/transfer/delete/reprint products, inventory, or labels; asks about orders (create, edit, status change, POS sale, custom line items, cash+QR split), transactions/settlements/subscription, analytics (sales report, P&L, daily overview, shift close), delivery charges, or categories; drops a folder of handwritten bill images (e.g. "<DDMMM Entry>/Bill N/") into Downloads; or asks about supplier lookup, batch discovery, stock reconciliation, or product deletion cleanup on that store. Skip only when the user explicitly wants Blanxer's native CSV importer, the dashboard UI, or a one-off single-product entry.
---

# Blanxer Product Upload

This skill lets you push products into a Blanxer vendor store directly via the API. Auth is a single Blanxer API key (from **Store Setting → API Key**); the key exchanges for a short-lived JWT, and the JWT covers every subsequent call. No browser tab, no session tokens.

The flow is two POSTs per product: create the product, then stock it into an outlet. Both calls are bearer-token authed against the user's logged-in session.

## When to use

Trigger as soon as you see any of:

- A reference to Blanxer (the vendor app at `app.blanxer.com`).
- A CSV/Excel/screenshot with rows of products plus quantity, cost, and selling price — especially the bill format with columns "Product Name", "Quantity (pieces)", "Cost Rate (Rs.)", "Selling Rate (Rs.)".
- A request to "upload these to my store", "add to inventory", "stock in 40 items at Main Branch", etc., when a Blanxer tab is open.

## What you need before running

**Rule: don't guess prerequisites. Never invent an API key, outlet, channel, or CSV path if the user hasn't specified.** A single upfront question is much cheaper than uploading 40 products to the wrong outlet.

### Minimum to start (ask up front, in ONE short message)

Only two things are needed just to load the skill — everything else depends on which workflow the user picks:

1. **Blanxer API key** — 59-char `sk_…` from **Store Setting → API Key**. Ask the user to paste it or set `BLANXER_API_KEY` in the env. Nothing else works — session tokens, DevTools localStorage, and Chrome-tab injection are all deprecated. The key gets exchanged for a short-lived JWT via `POST /api-key/check` (details in "Auth options" below).
2. **What are we doing?** — offer the common flows and let the user pick:
   - Upload products from CSV/Excel/paired bill images
   - Reprint barcode labels for existing products
   - Adjust inventory (stock-in / write-off / transfer / count correction)
   - Delete products cleanly (write-off orphan stock, then delete)
   - Orders / transactions / analytics query

Do NOT batch-ask for outlet, CSV path, channel, images, delay, etc. in the opening question. Those are workflow-specific and irrelevant if the user just wants a report or a label reprint. Ask them **only** after the user picks a workflow.

### After the user picks a workflow — the workflow-specific inputs

Ask for whichever of these are relevant to what they picked, and only then:

**Upload / stock-in / inventory adjust flows** need:

- **CSV path or bill-image folder.** If the user hasn't given one, ask. If you don't have filesystem access to the folder, call `request_cowork_directory` (typically `~/Downloads`).
- **`outlet_id` / outlet name** (e.g. "Main Branch"). Resolve via `GET /inventory/outlets/:store_id`. If multiple match or none, list options and ask — don't pick.
- **Product channel.** Codes: **Website = `2`**, **POS = `3`**, **All = `1`**. Default POS for stock-in flows from handwritten bills. Confirm if intent is unclear.
- **Delay between products.** Default 3s. Ask if the batch is >100 or the user wants faster/slower.
- **Images (Website / All channels only).** For POS-only uploads, skip. For Web/All:
  - Ask whether the user has images ready (folder path? one image per row?).
  - Fetch `customization.image_ratio` via `GET /store/{store_id}` and translate: `1`=1:1 square, `2`=4:3, `3`=16:9.
  - **Ask upfront: crop yourself (agent) or user pre-crops?** The storefront crops at render time to the store's `image_ratio` — off-center subjects will get chopped. Options:
    - User pre-crops → just upload as-is.
    - Agent auto-crops → use `sips`, Pillow (`ImageOps.fit`), or ImageMagick to center-crop to the target ratio before uploading. Confirm the ratio before batch-processing.
  - **Don't pre-convert format.** Server auto-converts raster images (JPG/PNG/HEIC) to **WebP quality 95** via sharp on upload; the returned `file_url` will end in `.webp`. SVG passes through unchanged.
  - **No code-level file-size cap**, but downscale phone photos to ~2000 px on the long edge to avoid upstream gateway caps and memory pressure. Corrupt/undecodable bytes cause a `500`.

**Reprint labels** needs: product IDs (or a name substring — the reprint script accepts `BLANXER_PRODUCT_QUERY`). Nothing else.

**Delete products** needs: the product IDs to delete. Warn about the write-off-first orphan-stock recipe (see `references/api.md` → "Deleting a product cleanly") before executing.

**Orders / transactions / analytics** need: date range (or use defaults per endpoint) and, for POS reports, optional groupBy/format. See `references/api.md`.

Never fabricate an answer. Restate what you're about to do in a one-line dry-run summary (see step 3 of the workflow) before firing any batch mutation.

### Auth options — how to send credentials

**Only one supported path: Blanxer API key.** The `sk_…` key is the sole credential — session bearer tokens, DevTools-copied `blanxer_access_token` values, and Chrome-tab injection are all deprecated for this skill. If the user doesn't have a key, direct them to their Blanxer dashboard: **Store Setting → API Key** to generate one. The key is 59 chars, starts with `sk_`, and embeds the `store_id` in chars 3..27.

**Storage — never persist the key inside this skill's folder.** Prefer, in order: (a) prompt-each-run and pass via env var (`BLANXER_API_KEY=sk_...`) to the script, (b) shell-level env var the user has set in `~/.zshrc` / macOS Keychain via `security find-generic-password`, (c) macOS Keychain lookup. Never log the key, never echo it into a saved transcript, and don't add it to `settings.json`.

**API-key → Bearer token exchange (do this first, before any other call).** The `sk_…` API key is NOT sent directly on data endpoints. It's exchanged for a short-lived JWT via one dedicated endpoint, and that JWT is then used as `Authorization: Bearer …` for everything else.

**Exchange endpoint:**

```
POST https://api.blanxer.com/api-key/check
Content-Type: application/json
User-Agent / Origin / Referer / Accept  ← required (see "CF" note below)
(no Authorization header — the api_key IS the credential)

{ "api_key": "sk_<24hexStoreId>........................" }
```

**⚠ Cloudflare gates this endpoint too.** As of 2026-07-20 the exchange returned `403 error code: 1010` from plain HTTP clients without browser headers. **Always send the full CF header set** (`User-Agent`, `Origin: https://app.blanxer.com`, `Referer: https://app.blanxer.com/`, `Accept: application/json`) on `/api-key/check` — same as every other mutating call. Earlier notes claiming this route was exempt were wrong; treat every request in this skill as CF-gated.

**Response** (200):

```json
{
  "success": true,
  "store": {
    "_id": "<store_id — same as chars 3..27 of the key>",
    "name": "...",
    "phone_number": "...",
    "sub_domain": "...",
    "custom_domain": "...",
    "owner": "..."
  },
  "token": "<JWT — use as Bearer for all subsequent calls>"
}
```

**Key format** — total 59 chars, must start with `sk_`. The 24 chars at positions 3..27 are the store's Mongo `_id`; the rest is a random tail. So the store_id is ALREADY encoded in the key — you can extract it as `apiKey.substring(3, 27)` without a network call, but always confirm against `store._id` in the exchange response.

**Server-side validation chain** (for reference, so you understand possible error shapes):

1. `validateApiKeyAndGetStoreId(api_key)` — format check (length 59, `sk_` prefix, chars 3..27 are a valid ObjectId).
2. Look up `ApiKey.findOne({ store: storeId, value: api_key })` — key must exist and belong to the store encoded in it.
3. `api_key.includes(String(isApiKey._id))` — the ApiKey document's own `_id` must also appear in the key (anti-forgery).
4. Load `Store`, then the owner `User`.
5. `getTokens(userData)` mints a JWT for the owner.

**After exchange**, use the token for every other endpoint including `GET /inventory/outlets/:store_id`, `POST /product/:store_id`, `POST /inventory/stock-in`, etc.:

```
Authorization: Bearer <token from /api-key/check>
```

`authRoleCheck` on those routes resolves the JWT → owner `user_id` → matching `StoreUser` for `store_id` → owner-level scope (all permissions, all outlets).

**Preflight order** (do NOT skip):

1. `POST /api-key/check` with the raw sk_ key **+ browser headers**. Expect 200 + `{store, token}`.
2. Keep `token` and `store._id` in Python variables for the rest of the session.
3. `GET /inventory/outlets/:store_id` with `Authorization: Bearer <token>` **+ browser headers** — expect 200 with `{outlets, allowed, inventory_roles, isOwner}`.
4. Match the outlet name against `allowed`.
5. Only then start the create+stock-in loop.

**Storage rules — read carefully so auto mode doesn't refuse the exchange:**

- **Never write the sk_ key or the JWT into**: `settings.json`, `~/.claude/` anywhere, git-tracked files, this skill's folder, permanent env-var files (`~/.zshrc`, `.env` committed to repo).
- **OK to write to** an ephemeral scratch dir like `/tmp/<something>/exchange.json` when a subprocess needs the token — that's expected for the direct-HTTP script. Auto mode should allow this; if it blocks, use the in-memory pattern below instead.
- **Best pattern — no disk writes at all.** Pass the key via env var into a single Python process that does exchange → all the calls → exits. Nothing ever hits the filesystem:

```python
import json, urllib.request, os
BASE, UA = "https://api.blanxer.com", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
CF = {"User-Agent": UA, "Origin": "https://app.blanxer.com", "Referer": "https://app.blanxer.com/"}
api_key = os.environ["BLANXER_API_KEY"]

# Exchange (needs CF headers now — Cloudflare gates this route too)
req = urllib.request.Request(
    f"{BASE}/api-key/check",
    data=json.dumps({"api_key": api_key}).encode(),
    headers={"Content-Type": "application/json", "Accept": "application/json", **CF},
    method="POST",
)
r = json.loads(urllib.request.urlopen(req, timeout=30).read())
token = r["token"]
store_id = r["store"]["_id"]
# ... use token + store_id for all subsequent calls, then exit
```

Invocation: `BLANXER_API_KEY='sk_...' python3 /path/to/script.py` — the key stays in the process environment, never touches disk.

**Failure modes specific to API-key auth:**

- Exchange returns 4xx: the key is malformed (wrong length / missing `sk_` / bad ObjectId in chars 3..27) OR revoked (no matching `ApiKey` doc). Surface the response body and stop.
- Exchange succeeds but subsequent Bearer calls 401: the minted JWT has expired. Just re-exchange — the sk_ key itself doesn't expire.
- Attempting to send the sk_ key directly as `Authorization: Bearer` (or any other header) against data endpoints returns `401 {"message":"Forbidden 🚫🚫"}`. This is the wrong flow — always exchange first.

## End-to-end workflow

Follow these steps in order. Don't skip the dry-run summary (step 4) — it catches column-mapping mistakes before they become 40 garbage products in production.

### 1. Read and parse the source (CSV *or* paired images)

**Source A — CSV/Excel**

Use the file tools (`Read`, `Glob`) to find and parse the CSV. Build a per-row record with at minimum: `name`, `qty`, `costRate`, `sellingRate`. Skip header and total rows (rows where the quantity field isn't a positive integer).

If the CSV uses different column names than the bill format, detect them by header keywords. Common variants:

- **Name**: `Product Name`, `Name`, `Item`, `Description`
- **Quantity**: `Quantity (pieces)`, `Quantity`, `Qty`, `Pieces`, `Units`
- **Cost rate**: `Cost Rate (Rs.)`, `Cost Rate`, `Cost Price`, `Cost`, `Buy Price`, `Wholesale`
- **Selling rate**: `Selling Rate (Rs.)`, `Selling Rate`, `Selling Price`, `Price`, `MRP`, `Retail`

If you can't confidently match a column, ask the user — don't guess.

**Source B — paired bill images (printed invoice + handwritten notebook)**

the user's usual workflow is to hand you a folder like `~/Downloads/<DDMMM Entry>/Bill N/` containing:

- A **printed "BILL FORM" / invoice** (Sangam-style pad, printed in blue, dated in the header) — this is the **cost price** side. Each row has `SN | Qty (Npc) | Rate (cost) | Amount`. The product name is written on row 1 (typically `"sall set"` or similar) and rows below use ditto marks (`" u u "`).
- A **handwritten notebook page** with the same row count — this is the **selling price** side. Columns are usually `SN | pieces | rate` with no product name.

**Matching procedure (do this before any upload):**

1. Convert `.HEIC` files with `sips -s format jpeg -Z 2400 <file> --out <out>.jpg` before Reading (the Read tool won't decode HEIC directly).
2. Read both images. Extract each row as `{sn, qty, cost, selling}`.
3. **Reconcile row-by-row on `qty`** — the piece count on the printed bill must match the piece count on the notebook for the same SN. If any row doesn't line up, stop and ask (numbering may be scrambled — see the "circled corrections" note below).
4. **Verify the cost-side grand total** against the printed bill's `TOTAL` box. This is a cheap sanity check that OCR read all rates correctly.
5. Watch for **circled corrections / arrow notations on the notebook** (e.g. `3800 → 20`, encircled `-1`, encircled `20`). the user uses these as adjustments or lot markers — do NOT silently apply them as price edits or drop them. Surface every circled/arrow'd row in the dry-run summary and ask what each means.
6. **Product naming:** default format is `<SN>. <D/M> <name>` (number first, then day/month with **no year**, then name). Example: `1. 13/7 sall set`, `22. 12/7 sall set`. Where:
   - `<SN>` is the row's serial number from the printed bill. Do NOT zero-pad unless the user asks — the user prefers plain `1.`, `2.`, …, `23.`.
   - `<D/M>` is day/month only, taken from the bill header (e.g. `13/7`, `12/7`, `11/7`). Drop the year.
   - `<name>` is whatever's written on the first row of the printed bill (`sall set`, etc.). Rows with ditto marks inherit this name. If a row has a different explicit name, use that.
   - If the user asks for a different order or padding, honor it — but this is the sticky default from prior sessions.
7. Present the fully-extracted table (SN, qty, cost, selling, ambiguity flags, and the constructed product name) and **wait for explicit confirmation before proceeding to step 2**.

### 2. Discover store_id and outlet_id via the API key

Exchange the `sk_` key for a JWT, then read the outlets list. The store_id comes back in the exchange response (and is also encoded in the key's chars 3..27).

```python
import json, urllib.request, urllib.parse

BASE = "https://api.blanxer.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 1) Exchange sk_ → JWT
ex = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/api-key/check",
    data=json.dumps({"api_key": api_key}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)).read())
token, store_id = ex["token"], ex["store"]["_id"]

# 2) Fetch outlets
req = urllib.request.Request(
    f"{BASE}/inventory/outlets/{store_id}",
    headers={"Authorization": f"Bearer {token}",
             "User-Agent": UA, "Origin": "https://app.blanxer.com", "Referer": "https://app.blanxer.com/"})
body = json.loads(urllib.request.urlopen(req).read())
```

The response has four fields: `outlets`, `allowed`, `inventory_roles`, `isOwner` (full shape in `references/api.md`). Use them like this:

- **Match against `allowed`, not `outlets`.** `allowed` is the list scoped to the current user. Matching an outlet that isn't in `allowed` will 403 on stock-in.
- Name match is case-insensitive, ignoring whitespace. If multiple match or none match, list options and ask.
- **Skip the synthetic `{_id: "all", name: "All Outlets"}` entry** — it's not a real outlet and can't accept stock-in. Fall back to `outlets` (by name) to resolve which real `_id` to use if the user says "all outlets".
- **Verify `inventory_roles` includes `"stock_in"`** before running the loop. If it doesn't, tell the user their role can't add stock and stop.
- `isOwner: true` is a shortcut meaning `allowed` covers every real outlet; matching logic is the same.

Don't hardcode IDs across runs — different stores and outlets exist. The IDs from the previous Example Store session (`store=507f1f77bcf86cd799439011`, `outlet=507f1f77bcf86cd799439012`) are example values, not constants.

### 3. Confirm the plan with the user

Show a one-line preview before running anything: count of products, outlet name, channel, delay between products, and any rows you skipped. Example:

> About to upload **43 products** to outlet Main Branch** on channel **POS**, with a **3-second gap** between products. Estimated time ~2.5 minutes. Skipped 1 row (totals). Proceed?

Wait for explicit confirmation. The user often wants a small delay (1–5 sec) to avoid hammering the API; default to 3 seconds if unspecified.

### 3.5. Upload images (Website / All channels only)

Skip if `channel == 3` (POS-only). For Website (`2`) or All (`1`):

**Per product**, for each image in the user's per-row image mapping:

```
POST /product/{store_id}/file            (multipart, CF browser headers)
Content-Type: multipart/form-data
Fields: file=<image binary>, upload_purpose=product_image
```

Response includes `file.file_url` — an S3 URL. Collect these per product; the **first URL becomes the primary/thumbnail** in `image_urls[]`, so order matters.

- **Cropping**: before uploading, decide the per-image approach (already agreed in prerequisites step 7). If auto-cropping, use `sips -c <H> <W> <input> --out <output>` for square (macOS) or Pillow (`ImageOps.fit(img, (w, h))`) for arbitrary ratios. Feed the cropped file to the upload, not the original.
- **Fail-soft**: if one image fails, keep the URLs that succeeded and continue to product create rather than aborting the whole row. Log the row/filename so the user can retry manually via `POST /product/{store_id}/{product_id}/file` on the created product.
- **Parallelism**: image uploads are the slow part. If you're batching 40+ products with images, upload in parallel (5–10 at a time) — the create step below is still sequential.

For POS-only channel this step is entirely skipped; product cards in the POS UI work off name/barcode alone.

### 3.6. Categories — optional, run before product create

**Only engage if the user asks for categorization or the source file has a category column.** Otherwise send `categories: []` on every product create and move on. Don't proactively ask "what category?" for a plain CSV that has no category hint.

**Categories are subdocs on the Store**, not a separate collection. So all lookup is client-side:

1. **Fetch once, cache for the whole batch.** `GET /store/{store_id}` → keep `.categories[]` in memory. Do **not** refetch per product — 41 products would mean 41 wasted GETs.
2. **Match logic** (case-insensitive, whitespace-trimmed on `name`):
   - Exactly one name match → use its `_id`.
   - Multiple same-name matches → list them (name + slug + \_id) and ask which.
   - No match → ask: *"No category 'Snacks' exists. Create it, pick an existing one, or skip categories?"* **Never auto-create** — a typo makes a permanent duplicate category on the storefront.
3. **On confirmed create** → `POST /store/{store_id}/add_category` with `{name}` (only field that matters — `slug` auto-generates). Capture the returned `category._id` **and append it to your in-memory `.categories[]` cache** so later products in the same batch reuse it instead of triggering another create call.
4. Pass the resolved id(s) into the product-create body: `categories: ["<cat_id>", ...]`.

**⚠ The API does not validate category ids.** `POST /product/{store_id}` silently stores unknown ids as dangling references — a typo won't error, it'll just leave a broken chip on the product page. Only send ids that came from the fetched-or-just-created cache; never invent one.

**Role**: create/update needs owner/manager; a non-owner/manager should pick an existing category or skip. **CF**: `add_category` is a POST → include the browser browser headers.

This step can also fire **after** an upload (assigning categories to already-created products) via `POST /product/{store_id}/{product_id}` update — but the cleanest path for a fresh batch is to resolve the category before the create loop and include it in the body.

### 3.7. Supplier — optional, run before stock-in

**Only engage this flow if the user mentions a supplier / vendor / invoice / bill-from, or the source file has a supplier column. Otherwise skip silently and leave `reference_number` empty on stock-in.** Never proactively ask "which supplier" for a plain CSV that has no supplier hint.

When supplier context exists:

1. **Search first**: `GET /pos-finance/suppliers/{store_id}?q=<name>` (works for any store user).
2. **Match logic:**
   - Exactly one strong match → confirm with the user: *"Found supplier 'ABC Traders' — use this? (yes / pick another / create new)"*.
   - Multiple matches → list them (name + phone) and ask which one.
   - No match → ask: *"No supplier named 'ABC Traders' exists. Create it, pick an existing one, or skip supplier for this upload?"*
3. **Create only on explicit confirmation**: `POST /pos-finance/suppliers/{store_id}` with at least `name` (**owner/manager only** — non-owner/manager users must pick existing or skip). Never auto-create; a typo would spawn a duplicate vendor. Capture the returned `_id`.
4. **Never block the upload on supplier.** If the user declines, is unsure, or lacks the role to create, proceed with no supplier — stock-in still works fine.

**⚠ How the chosen supplier is actually applied — read this carefully.**

**`POST /inventory/stock-in` does NOT accept a supplier id.** The `Batch` model has a `supplier` field but the handler never sets it — it only writes `supplier_ref: <reference_number>` (free text) to the batch. So:

- Selecting a supplier does not create an automatic stock↔supplier link.
- The only supplier trace on the batch is whatever string you send in `stock-in.reference_number`.
- Payables / ledger entries are a separate flow (`POST /pos-finance/supplier-entry`) — not triggered by stock-in.

**Practical application** (all this step does):

- Pass a stable descriptor into every `stock-in` call for this upload: `reference_number: "ABC Traders / INV-4471"` (name + invoice number if the user has one). This becomes the batch's `supplier_ref` and is searchable in stock movement logs.
- If the user *also* wants the batch value recorded as payable to that supplier, offer — don't assume — a follow-up `POST /pos-finance/supplier-entry/{store_id}/{supplier_id}` after the upload completes. Ask before firing.

**Be honest with the user**: "Picking a supplier just puts their name in the batch reference and (optionally) records a payable. It doesn't magic-link the vendor to each stocked-in item — Blanxer's batch model doesn't wire that up today."

### 4. Run the upload loop (direct HTTP via API key)

Fire `scripts/upload_direct_http.py` with `BLANXER_API_KEY`, `BLANXER_OUTLET_ID`, `BLANXER_CSV`, and optional channel/delay overrides. It handles the `sk_ → JWT` exchange, sets the Cloudflare browser headers, loops create + stock-in per row with a configurable delay, and auto-generates the barcode PDF at the end.

For each product, include `image_urls: [<url1>, <url2>, ...]` (from step 3.5) in the create-product body. For POS-only uploads, `image_urls: []` is fine.

The script is the source of truth for payload shape. If you need to inline a smaller version for any reason, use these payloads exactly:

**Create product** — `POST https://api.blanxer.com/product/{store_id}`

```json
{
  "name": "<from CSV>",
  "channel": 3,
  "price": <selling rate>,
  "compare_at_price": 0,
  "cost_per_item": 0,
  "weight": 0,
  "quantity": 0,
  "showVariant": false,
  "showColorPreview": false,
  "continue_selling": true,
  "slug": "", "brand": "", "categories": [],
  "description": "", "long_description": "",
  "images": [], "image_urls": [],
  "sku": "", "color_name": "", "size_name": "",
  "color_codes": [], "colors": [], "sizes": [],
  "variants": [], "custom_fields": [], "tags": [],
  "releaseDate": null, "similar_products": []
}
```

Channel mapping: `1=All`, `2=Website`, `3=POS`. Response on success: `{success: true, product: {_id: "...", ...}}`. Keep `_id` for step two.

**Stock in** — `POST https://api.blanxer.com/inventory/stock-in`

```json
{
  "store_id": "<discovered>",
  "outlet_id": "<discovered>",
  "reference_number": "<see step 3.7 — supplier descriptor, e.g. 'ABC Traders / INV-4471', else empty>",
  "items": [{
    "product_id": "<_id from create response>",
    "variant_id": "",
    "quantity": <from CSV>,
    "cost_price": <cost rate from CSV>,
    "bin_location": ""
  }]
}
```

Both calls require `Authorization: Bearer <token from /api-key/check>` and `Content-Type: application/json`, plus the Cloudflare browser headers.

**⚠ Cloudflare gotcha (confirmed on 2026-07-20 against `api.blanxer.com v2.2`):** Requests from a plain HTTP client (curl, requests, urllib) get blocked with **`403` and body `error code: 1010`** — Cloudflare's browser-fingerprint challenge, not a Blanxer auth error. **Send the browser headers on EVERY request** — POST, DELETE, and GET alike, including the `POST /api-key/check` exchange. Empirical rule: it's cheaper to always add them than to remember which routes are gated.

**Fix**: always send these headers on every mutating request (create product, stock-in, delete, etc.):

```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36
Origin: https://app.blanxer.com
Referer: https://app.blanxer.com/
Accept: application/json, text/plain, */*
Accept-Language: en-US,en;q=0.9
```

If you see `403 error code: 1010`, don't retry-loop and don't fall back to fewer products — add the headers above. Also note the `code=403` from Blanxer's own layer is not the same shape (it returns JSON error messages, e.g. `{"message": "..."}`), so distinguishing is easy: `error code: 1010` = Cloudflare; anything else at 4xx = Blanxer app-level.

**⚠ Advanced-inventory stores:** when `use_advanced_inventory` is ON, the `quantity` field in the create-product payload is **ignored** — the product is created with `quantity: 0` and empty `inventory_summary`. Stock only enters via `POST /inventory/stock-in`. the user's Example Store store is in advanced-inventory mode as of 2026-07-20, so the two-step create-then-stock-in flow described above is required, not optional. If a store isn't in advanced mode yet: `POST /inventory/enable` (owner only) turns it on once.

**⚠ Product delete** (for cleaning test products or accidental uploads):

```
DELETE https://api.blanxer.com/product/{store_id}/{product_id}
Authorization: Bearer <token>
+ the Cloudflare browser headers above
```

Response: `200 {"success": true}`. Only DELETE with the full `/product/{store_id}/{product_id}` path works — variants like `/product/{id}` or `/product/delete/{id}` return 404 or 500. Role required: **owner** (not manager).

**⚠ Delete does NOT cascade inventory.** The endpoint calls `deleteOne()` on the Product document only. Batches, stock ledger entries, and `inventory_summary` stay behind as orphaned stock — the totals dashboard, cost of inventory, and outlet on-hand counts stay inflated. **Always write off remaining stock before delete**, in this order:

1. `GET /inventory/batch/{store_id}?product={id}&hasStock=true&per_page=100` → collect batches; group by `outlet`; sum `quantity`. If `meta.total = 0`, skip to step 3.
2. **One `POST /inventory/write-off` per distinct outlet** — write-off is scoped `outlet_id + batches[]`, so a product with stock at 2 outlets needs 2 write-off calls. Use `subtype: "SYSTEM_FIX"` (product-deletion cleanup, not damage) with the exact per-batch remaining quantity as the write-off quantity.
3. `DELETE /product/{store_id}/{product_id}`.

If the order is reversed (delete first, then write-off), write-off still succeeds because batches are found by product ref regardless — but the write-off's `Product.inventory_summary` update silently no-ops since the Product doc is gone, leaving `stock_ledger` correct but `inventory_summary` stale. Doing write-off first keeps everything in sync. Full recipe with payload shapes is in `references/api.md` under "Deleting a product cleanly".

**Required create-product body fields:** `name`, `description`, `continue_selling` — everything else has a server default. Keep `description: ""` if the user hasn't provided one (server accepts empty string).

**Universal limits (apply on every plan):**
- **500 variants per product** (hard cap for everyone).
- **SKU uniqueness within the store** (base SKU + variant SKUs).

**Plan-tier gates (checked upfront in step 0 — see next section):**
- **No paid plan** (`store.plan` empty/undefined) → hard cap of **15 products total**, no `bulk_add`, no SMS, no Excel export.
- **Any of the 5 paid plans** (`pos`, `basic`, `premium`, `platinum`, `plus`) → unlimited products, `bulk_add` allowed, SMS/export unlocked.

### 0. Preflight — read the store plan (verified live 2026-07-20)

**Do this before Step 1** for any upload of >5 products.

```
GET https://api.blanxer.com/store/{store_id}
Authorization: Bearer <token>
+ CF browser headers (Origin/Referer/UA — this is a GET so it usually works without, but send them anyway to be safe)
```

**Verified response shape** (Example Store, 2026-07-20):

```jsonc
{
  "_id": "507f1f77bcf86cd799439011",
  "name": "Example Store",
  "plan": "platinum",                     // ← top-level string, this is what to check
  "use_advanced_inventory": true,
  "customization": { "image_ratio": 2 },
  "setting": { ... },                     // payment secrets stripped for non-owners
  ...
}
```

**How to gate on it:**

- **`plan` is one of** `"pos"` / `"basic"` / `"premium"` / `"platinum"` / `"plus"` → paid plan. Skip the product-count check; `bulk_add` / SMS / Excel export all allowed.
- **`plan` is** `""` / `null` / `undefined` / missing → non-premium (free / lapsed / trial-without-plan). Also run `GET /product/pos/{store_id}` to count existing products. If `existing_count + planned_batch > 15`, **STOP and warn**: *"Store has no paid plan; capped at 15 products total. You have N; adding M would exceed the cap. Trim the batch or ask about upgrading."* Do not partial-upload — mid-batch failures leave orphan products with no batches.

For non-premium stores also disable any suggestions of `bulk_add`, SMS blasts, or Excel exports later in the flow — they'll all `not_allowed` regardless.

**Known store reference** (as of 2026-07-20): Example Store (`507f1f77bcf86cd799439011`) is on **platinum** — unlimited products, 2.75% Blanxer-Pay charge, 50 staff cap. Advanced inventory is ON. `image_ratio` is `2` (4:3). Skip this preflight for Example Store uploads unless the plan might have changed — but still worth a quick check if the batch is huge.

**⚠ Advanced-inventory detection needs TWO fields, not one:**

```python
is_advanced_inventory = store.get("use_advanced_inventory") is True and bool(store.get("website_outlet"))
```

The flag alone is insufficient — `website_outlet` is only set as a side-effect of the enable migration. A store with `use_advanced_inventory=true` but no `website_outlet` is in a half-migrated / broken state; treat it as non-advanced (use direct-quantity flow, not stock-in).

**⚠ Never auto-run `POST /inventory/enable`.** It's **Platinum-only** (throws for any other plan), NOT bodyless (requires an outlet payload), and is a **one-way migration** — walks every existing product and seeds `OPENING_BALANCE` batches from current quantities, then sets `website_outlet`. Two BETA stores are blocked entirely. If the user asks to enable advanced inventory, hand them the payload shape and confirm the outlet fields with them; don't fire it as a side-effect of an upload.

**Branch on the two flows:**

| Mode | Product-create body | Stock adjustment | Stock read |
|---|---|---|---|
| **Advanced** (Platinum + `website_outlet`) | `quantity` forced to 0; must call `POST /inventory/stock-in` per outlet after | `write-off` / `transfer-stock` / `stock-in` on the batch ledger. Editing quantity via product-edit is **ignored**. | `/inventory/list`, `/inventory/summary`, `/inventory/batch` |
| **Non-advanced** (every non-Platinum store, or Platinum-but-not-enabled) | `quantity` and each `variants[].quantity` in body **is** the stock — no follow-up call | `POST /product/variant_inventory/{store_id}/{product_id}` — sets absolute values (not deltas). Owner/manager. | `GET /product/pos/{store_id}` or `GET /product/{store_id}/{product_id}`. **`/inventory/*` endpoints return empty** because there's no `Batch` collection populated. |

Full endpoint reference for both paths lives in `references/api.md` under "Advanced-inventory detection" and "Non-advanced path".

**Python snippet for the plan check:**

```python
import json, urllib.request
req = urllib.request.Request(
    f"https://api.blanxer.com/store/{store_id}",
    headers={"Authorization": f"Bearer {token}",
             "User-Agent": UA, "Origin": "https://app.blanxer.com", "Referer": "https://app.blanxer.com/"})
store = json.loads(urllib.request.urlopen(req).read())
plan = store.get("plan") or ""
is_premium = plan in {"pos", "basic", "premium", "platinum", "plus"}
```

**Do not surface** staff-user limits or payment service-charge tier differences during an upload — they're irrelevant to the product flow. Only mention them if the user asks about plans, staff, or payment charges specifically. Reference table (for on-demand answers):

| Plan | Max staff users | Blanxer-Pay charge |
|---|---|---|
| Basic | 5 | 3.9% |
| Premium | 20 | 3.0% |
| Platinum | 50 | **2.75%** (lowest) |
| POS / Business Plus | unlimited | POS 3.9%, Plus 3.0% |
| (No plan) | can't invite | n/a |

(Own-gateway transactions = 0% regardless of plan.)

### Post-upload adjustments

When the source (notebook, count) says an already-uploaded product's quantity should change, DON'T re-create the product. Adjust the batch ledger instead:

- **Decrease** (e.g. notebook says "-1"): fetch `batch_id` via `GET /inventory/batch/{store_id}?product={id}&outlet={outlet_id}&hasStock=true`, then `POST /inventory/write-off` with `subtype: "COUNT_CORRECTION"` and `{batch_id, quantity: n}`.
- **Increase**: another `POST /inventory/stock-in` — creates a new batch layered on top.
- **Move between outlets**: `POST /inventory/transfer-stock` with `{target_outlet, batches:[{batch_id, quantity}]}`.
- **Verify**: `GET /inventory/list/{store_id}?outlet={outlet_id}&product_id={id}` — check `current_stock`.

Full endpoint bodies, subtypes (`DAMAGED|EXPIRED|LOST|THEFT|COUNT_CORRECTION|PURCHASE_RETURN|SYSTEM_FIX`), and the "adjust to target quantity" recipe are in `references/api.md` under "Inventory adjustment".

### 5. Verify after upload

When the loop reports done, navigate the tab back to `https://app.blanxer.com/dashboard/products`, take a screenshot, and spot-check the top 3 rows against the CSV (name, selling price, inventory count). Report total uploaded, total failed, and any errors. If any item failed, list its index, name, and error so the user can retry just those.

Then reconcile against the source if possible: total quantity, total cost amount, etc. — handwritten bills usually have a stated grand total at the bottom that should match.

### 6. Generate + download the barcode PDF (automatic)

**Do this without being asked** — the user needs to physically stick labels on the goods, so the PDF is the whole point of the upload. Fire it as soon as step 5 reconciles cleanly.

1. Collect the `product_id`s from the upload loop (they're already in your log/`progress.jsonl`).
2. Fetch authoritative on-hand stock via `GET /inventory/list/{store_id}?outlet={outlet_id}&per_page=100` — this catches any post-upload write-offs (e.g. "-1 pc less" notebook corrections) so the label count matches physical inventory.
3. Build `quantities = {product_id: current_stock, ...}`. For **variant products, key by `variant._id`** instead of `product._id` — mixing will drop labels.
4. `POST /order/print_request/{store_id}` with `{"orders": [pids], "print_for": 2}` → grab `id` from response (this is `print_id`).
5. `GET /product/generate_barcode_quantity/{store_id}/{print_id}?token=<JWT>&quantities=<url-encoded-JSON>&show_name=true&show_store=false&show_price=true&show_barcode=true` → save response bytes to a `.pdf` file. **`show_store=false` is a sticky the user preference** — product name goes on top, not the store name (which is redundant on Example Store labels).
6. **Copy the PDF into the source folder** (e.g. next to the input CSV / into `<DDMMM Entry>/barcodes.pdf`) so the user finds it without hunting.

**⚠ Cloudflare on BOTH calls:** send the browser headers (`User-Agent`, `Origin`, `Referer`) on the print-request POST **and** on the PDF GET. The GET returns `403` without them even though the JWT is in the query string. Confirmed 2026-07-20.

**⚠ Sticky label preference for the user's stores** — `show_name=true` + `show_store=false`. Product name at the top; store name suppressed (redundant on his labels). Both `upload_direct_http.py` and `reprint_barcodes.py` already default to this — don't undo it unless the user explicitly asks for the store name back. Other useful flags to pair: `show_price=true`, `show_barcode=true`, `show_variant=true` (for variant products), `show_crossed_price=true` (if you want the compare-at-price crossed out), `use_alt_barcode=true` (variant-level barcode instead of parent).

**⚠ No print-preview endpoint exists.** Blanxer has no "render this print request as HTML/JSON so I can inspect the layout before printing" route. The generated PDF **is** the preview — save it, open it locally, verify the layout, then physically print. If the layout is wrong, re-issue with different flags (a print request is single-shot but cheap to recreate). Two adjacent read endpoints that sound like previews but aren't:
- `GET /order/print_request/{store_id}/{print_id}` — returns the order/product IDs the print request was created for, NOT a layout preview.
- The `POST /order/print_request/…` response body includes `{success, id}` — no layout data.

**⚠ The `orders` field is a misnomer** — it takes product IDs, not order IDs. `print_for: 2` = barcodes; `1` = shipping labels.

**Skip this step only if the user explicitly says "no labels needed"** — otherwise assume they want the PDF and produce it. Full endpoint reference, all label-style query flags (`show_variant`, `mrp_label`, `jewelry_tag`, etc.), and the simpler `generate_barcode` (no-quantities) variant are in `references/api.md` under "Barcode PDF generation".

### Reprinting barcodes on demand (no fresh upload needed)

When the user asks to print labels for **existing** products ("reprint labels for the 12/7 batch", "give me 3 spare tags for row 22"), don't re-upload — use the same print-request flow with the products' existing IDs. Use `scripts/reprint_barcodes.py`:

```
BLANXER_API_KEY=sk_...  BLANXER_PRODUCT_IDS=6a00...79,6a00...80  \
  python3 /Users/prashant/.claude/skills/blanxer-skill/scripts/reprint_barcodes.py
```

Or search by name substring via `BLANXER_PRODUCT_QUERY="12/7"`, or pass explicit per-product counts via `BLANXER_QUANTITIES='{"6a00...79":3}'` for the by-quantity mode. Default = simple mode (one label per live stock unit).

Print requests are one-shot but **fully independent of the upload session** — nothing about the sk_ key or session state ties them together. Product barcode values are persistent (set once at create time), so a reprint months later produces the same scannable codes. Two modes:

- **Simple** (`GET /product/generate_barcode/{store_id}/{print_id}`) — one label per live stock unit; default choice when the user just says "reprint labels".
- **By-quantity** (`GET /product/generate_barcode_quantity/...`) — caller picks exact copies; use when they want a specific count irrespective of stock ("3 spare tags").

Both need CF browser headers on POST + GET. Full recipe (product-ID discovery via `/product/pos/{store_id}` or `/product/{store_id}/{product_id}`, mode selection, variant keying) in `references/api.md` under "Reprinting barcodes on demand".

## Failure modes to watch for

- **Bearer token expired (401)**: Tell the user to reload the Blanxer tab (it'll refresh the token), then retry the loop from where it stopped. Don't silently re-run successful items.
- **Duplicate name**: Blanxer permits duplicates by default but it's confusing for the user. If the CSV has duplicate product names, surface that in step 3 and ask whether to suffix them.
- **Non-numeric qty/price**: Skip those rows in step 1 with a count, surfaced in the dry-run summary.
- **Missing outlet match**: Don't pick an outlet on the user's behalf if the name is ambiguous. Show all options.
- **Network reader being flooded**: When debugging, the tab makes background polling GETs to `/store/{id}` that drown out the interesting POSTs. Use a fetch interceptor (`window.fetch = ...`) to filter to non-GET methods if you need to look at request bodies live.

## Direct-HTTP path (API key — the only supported path)

Use `scripts/upload_direct_http.py`. It handles the `sk_` → Bearer JWT exchange (`POST /api-key/check`), sets the Cloudflare-safe browser headers, and runs create + stock-in per row.

```
BLANXER_API_KEY=sk_...  BLANXER_OUTLET_ID=<outlet_id>  BLANXER_CSV=<csv_path>  \
  python3 /Users/prashant/.claude/skills/blanxer-skill/scripts/upload_direct_http.py
```

Optional env vars: `BLANXER_CHANNEL` (default 3=POS), `BLANXER_DELAY_S` (default 3s), `BLANXER_BARCODE_PDF` (default `<CSV dir>/barcodes.pdf`, `""` to skip). The script derives `store_id` from the key (chars 3..27) and prints the resolved store name before running. Confirm it before letting it loose on production data.

**If the user doesn't have a key**, direct them to their Blanxer dashboard: **Store Setting → API Key** to generate one. No fallback path — session tokens and Chrome-tab injection are not supported.

## Reference

- `scripts/upload_direct_http.py` — turnkey direct-HTTP uploader (sk_ key → exchange → CF headers → create + stock-in loop). Use this for API-key uploads.
- `scripts/upload_loop.js` — parameterized loop you paste into the tab (browser path).
- `references/api.md` — captured request/response examples + full endpoint reference table.
