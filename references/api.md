# Blanxer API — captured request/response shapes

These were captured from a live `Add Product` walkthrough using a fetch interceptor in the dashboard tab. Use them as the source of truth when constructing payloads.

## Auth

- Token in `localStorage.blanxer_access_token` (Bearer JWT, ~407 chars).
- Sent as `Authorization: Bearer <token>` header.
- Token refresh seems to happen automatically while a tab is open; expired tokens (401) require a tab reload.
- Store ID also lives in `localStorage.current_store_id`.

## Endpoints used by the upload flow

### `POST https://api.blanxer.com/product/{store_id}`

Creates a product. Channel codes: `1=All, 2=Website, 3=POS`.

**Request** (only required fields shown — the full payload sent by the UI is in `SKILL.md`):
```json
{
  "name": "TEST_CLAUDE_DELETE_ME_002",
  "channel": 3,
  "price": 1234,
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

**Response** (200, truncated):
```json
{
  "success": true,
  "product": {
    "name": "TEST_CLAUDE_DELETE_ME_002",
    "slug": "test_claude_delete_me_002",
    "store": "507f1f77bcf86cd799439011",
    "price": 1234,
    "compare_at_price": 0,
    "cost_per_item": 0,
    "channel": 3,
    "status": "Active",
    "_id": "6a003959d4d079c38b896079",
    "created_at": "2026-05-10T07:52:57.002Z",
    "updated_at": "2026-05-10T07:52:57.002Z"
  }
}
```

The `_id` is required for the stock-in step. Also note `barcode` is auto-assigned, and `slug` is auto-derived from the name unless you pass one explicitly.

### `GET https://api.blanxer.com/inventory/outlets/{store_id}`

Returns the list of outlets configured for the store. Use this to resolve a human outlet name like "Main Branch" to its `_id`.

**Auth**: `authRoleCheck()` — any authenticated store user (owner / manager / csr / viewer). `user_id` is read from the token, not the URL. Handler: `get-store-outlets.ts`, route defined in `inventory/routes.ts:23`. Dev port is `7778`; production base is `api.blanxer.com`.

**Response shape**:
```json
{
  "outlets": [
    {
      "_id": "...",
      "store": "...",
      "name": "Main Branch",
      "address": "...",
      "contact_name": "...",
      "contact_number": "...",
      "status": "active",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "allowed": [
    { "_id": "all", "name": "All Outlets" },
    { "_id": "...", "name": "Main Branch" }
  ],
  "inventory_roles": ["stock_in", "..."],
  "isOwner": true
}
```

**Which field to use for the upload flow:**
- `outlets` — every location in the store (full detail incl. address, status). Fine for matching by name if the caller is the store owner.
- `allowed` — locations the current user is scoped to (StoreUser.inventory_outlets). Owners and users with `'all'` also get a synthetic `{_id: "all", name: "All Outlets"}` entry. **For a non-owner user, always filter against `allowed` — matching an outlet that isn't in `allowed` will 403 on stock-in.**
- `inventory_roles` — the current user's inventory permissions. `stock_in` must be present for the second POST to succeed.
- `isOwner` — shortcut; if `true`, `allowed` == `outlets` (plus the synthetic all-outlets entry).

There are no geo-coordinates on an outlet — `outlet.ts` stores name/address/contact/status only. Don't expect `lat`/`lng`.

**Related outlet-management endpoints** (same router, not used by the upload flow):
- `POST /inventory/create-outlet`
- `POST /inventory/update-outlet`
- `POST /inventory/change-website-outlet`

**Per-location inventory quantities** (accept an outlet filter):
- `GET /inventory/list/:store_id`
- `GET /inventory/summary/:store_id`

### `POST https://api.blanxer.com/inventory/stock-in`

Adds initial stock for a product at an outlet.

**Request**:
```json
{
  "store_id": "507f1f77bcf86cd799439011",
  "outlet_id": "507f1f77bcf86cd799439012",
  "reference_number": "",
  "items": [{
    "product_id": "6a003959d4d079c38b896079",
    "variant_id": "",
    "quantity": 7,
    "cost_price": 888,
    "bin_location": ""
  }]
}
```

**Response** (200):
```json
{ "total_items": 7, "total_batches": 1 }
```

The `items` array can take multiple entries — useful if you ever batch the stock-in step (the create step is one product at a time).

## Other endpoints observed (not needed for upload, but useful context)

- `GET /store/{store_id}` — fetches store settings; called frequently as a polling heartbeat (this is the request that floods the network log if you're trying to read it raw).
- `GET /brand/all/{store_id}` — brand list for the brand dropdown.

## Full endpoint reference (2026-07-20 update)

**Auth exchange**

- `POST /api-key/check` — trade `sk_…` key for `{store, token}`. No auth header.

**Products**

- `POST /product/{store_id}` — create. Required body: `name`, `description`, `continue_selling`. Owner/manager roles.
- `DELETE /product/{store_id}/{product_id}` — delete. Owner/manager. Returns `{success: true}`. Only this exact path shape works.
- `POST /product/{store_id}/bulk_add` — multipart file upload for bulk product creation (alternative to the loop).
- `GET /product/pos/{store_id}` — POS product listing.

**Inventory / outlets**

- `GET /inventory/outlets/{store_id}` — list outlets + `allowed` scope + `inventory_roles` + `isOwner`.
- `POST /inventory/create-outlet` — needs `create_outlet` role.
- `POST /inventory/enable` — flip store into advanced-inventory mode. **Platinum plan only** (`if (!['platinum'].includes(plan)) throw "This feature is only available in Platinum plan"`). **NOT bodyless** — creates the store's first outlet in the same call. **One-way migration**: walks every existing product and seeds `OPENING_BALANCE` batches from current `quantity`/`variants[].quantity` via `executeStockIn(..., skipQuantityIncrease=true)`, then sets `website_outlet` and flips `use_advanced_inventory=true`. Two specific high-volume store IDs are blocked (BETA). Errors if any outlet already exists. Body:
  ```
  { "name": "Main Branch", "address": "...", "contact_name": "...", "contact_number": "...", "status": "active" }
  ```
  **Never auto-enable** — treat as a manual, Platinum-only owner action. Skill should only detect current mode and branch.
- `POST /inventory/stock-in` — add stock to an outlet. Body: `{store_id, outlet_id, reference_number, batch_code?, items: [{product_id, variant_id?, quantity, cost_price, expiry_date?, mfg_date?, bin_location?}]}`. Response: `{total_items, total_batches}`.
- `POST /inventory/bulk-stock-in` — many SKUs, one outlet, one request.
- `POST /inventory/transfer-stock` — move between outlets.
- `POST /inventory/write-off` — damage / loss.
- `GET /inventory/list/{store_id}?outlet=<id>` — current on-hand per outlet.
- `GET /inventory/summary/{store_id}` — summary cards.
- `GET /inventory/stock-movement-logs/{store_id}` — full movement history.

**Advanced-inventory detection — two conditions, both required**

```
isAdvancedInventory = store.use_advanced_inventory === true  &&  !!store.website_outlet
```

The flag alone is not enough. `website_outlet` is set as a side-effect of `POST /inventory/enable`, so a store with `use_advanced_inventory=true` but no `website_outlet` is in a broken/half-migrated state — treat as non-advanced.

**Advanced-inventory path (Platinum + `website_outlet` present):**

- `POST /product/{store_id}` — `quantity` in body is forced to 0 and `inventory_summary` emptied.
- Stock enters via `POST /inventory/stock-in` (creates a Batch, increments `inventory_summary.stock_on_hand` and `product.quantity`).
- Verify via `/inventory/list`, `/inventory/summary`, `/inventory/batch` (all batch-based).
- Adjust later via write-off / transfer / stock-in on the ledger.
- Editing quantity through the product-edit endpoint is **ignored** in this mode.

Flow:
1. `POST /api-key/check` → `{token, store._id}`
2. `GET /store/{store_id}` → confirm `plan === "platinum"` AND `use_advanced_inventory && website_outlet` (do NOT auto-run `/inventory/enable` — see its entry above)
3. `GET /inventory/outlets/{store_id}` → pick `outlet_id`
4. `POST /product/{store_id}` (quantity forced to 0)
5. `POST /inventory/stock-in` with the outlet
6. `GET /inventory/list/{store_id}` to verify

**Non-advanced path (every non-Platinum store + Platinum stores that haven't enabled — the common case):**

- `POST /product/{store_id}` — `quantity` (and each `variants[].quantity`) is **applied directly**. Done. No outlets, no batches, no stock-in call needed.
- Adjust stock later via `POST /product/variant_inventory/{store_id}/{product_id}` (`edit-product-variant-inventory.ts`) — sets the **absolute** root `quantity` and per-variant `quantity`. Owner/manager. This is the non-advanced equivalent of stock-in/write-off/adjust; it's a set-to-value, not a delta.
- **Stock is INVISIBLE to `/inventory/list`, `/inventory/summary`, `/inventory/batch`** — those read the `Batch` collection which is empty for non-advanced stores. Use `GET /product/pos/{store_id}` or `GET /product/{store_id}/{product_id}` to verify quantity instead.
- Barcode: `GET /product/generate_barcode/{store_id}/{print_id}` (simple mode) reads `product.quantity` directly. `generate_barcode_quantity` still works if you pass explicit `quantities` map.

Flow:
1. `POST /api-key/check` → `{token, store._id}`
2. `GET /store/{store_id}` → confirm not-advanced
3. `POST /product/{store_id}` **with `quantity` and `variants[].quantity` set** — that's the whole stock step
4. Verify via `GET /product/pos/{store_id}` or `GET /product/{store_id}/{product_id}`
5. Later adjustments: `POST /product/variant_inventory/{store_id}/{product_id}` with absolute quantity

**Universal limits (every plan):** 500 variants / product, SKU uniqueness within store, advanced-inventory availability.

**Non-premium-only cap:** 15 products total per store. Lifted by any of the 5 paid plans — see "Plan tiers and gates" below.

**Cloudflare shielding:** mutating endpoints (POST/DELETE on product/inventory routes) require browser-like headers (`User-Agent`, `Origin`, `Referer`, `Accept*`) or return `403 error code: 1010`. See `SKILL.md` for the exact header set.

## Plan tiers and gates

Read `.plan` from `GET /store/{store_id}`. `isPremiumStore(plan)` returns `true` if the plan is any of the 5 paid codes:

| Code (`store.plan`) | Display name |
|---|---|
| `pos` | POS |
| `basic` | Basic |
| `premium` | Premium |
| `platinum` | Platinum |
| `plus` | Business Plus |

**"Non-premium" = empty / undefined `.plan`** (free tier, lapsed subscription, or trial without a paid plan attached). NOT "basic-tier" — `basic` is a paid plan and counts as premium for these gates.

**What non-premium (no paid plan) loses** — every one throws `not_allowed` / an upgrade error for a plan-less store:

| Capability | Source |
|---|---|
| Products capped at 15 total | `add-product.ts:70` |
| `POST /product/{id}/bulk_add` (multipart bulk upload) | `checkPremium()` |
| Product Excel export (`export_all`, `export_edit`) | export tasks |
| Order Excel export | export-order tasks |
| SMS feature | `enable-sms.ts:72` |
| Invite staff users at all | `store.routes inviteUser` |
| Files / folders (create, list, folder files) | `file.routes` |
| Delivery charge set / read | `store.routes` |
| Add-ons: Blanxer Pay, SMS, eSewa, eSewa SCD | `shouldCheckPremium` |

**Differences among the 5 paid plans:**

Staff-user limits (`store.controller.ts:186`):

| Plan | Max staff users |
|---|---|
| Basic | 5 |
| Premium | 20 |
| Platinum | 50 |
| POS / Business Plus | not capped in this check (effectively unlimited) |

Blanxer-Pay service charge (`payment.service.ts:42`) — applied only to Blanxer-Pay gateway transactions. Store's own gateway = 0% regardless of plan:

| Plan | Service charge |
|---|---|
| Platinum | **2.75%** (lowest) |
| Premium | 3.0% |
| Business Plus | 3.0% |
| POS / Basic / default | 3.9% |

**Not plan-gated (universal to every store):**

- 500 variants per product.
- Store-wide SKU uniqueness (base + variant).
- Core `POST /product`, image upload, supplier CRUD, category CRUD — all available on any plan (subject only to the 15-product cap for plan-less stores).

**Plan-gated features that are easy to miss:**

- **Advanced inventory** (`POST /inventory/enable`) — **Platinum-only** (`if (!['platinum'].includes(plan)) throw`). NOT toggleable on other paid plans. Also one-way + creates an outlet + migrates existing quantity into `OPENING_BALANCE` batches. See the `/inventory/enable` entry.
- Once a store is in advanced-inventory mode, `stock-in`, `write-off`, `transfer-stock`, `/inventory/list`, `/inventory/summary`, `/inventory/batch` all become the source of truth. Before advanced-inventory (or on any non-Platinum store), these endpoints work but read from an empty Batch collection — stock lives directly on `product.quantity` / `variants[].quantity` instead.

**Agent preflight logic for uploads:**

1. `GET /store/{store_id}` → read `.plan`.
2. If `.plan` is empty → non-premium. `GET /product/pos/{store_id}` to count existing products. If `existing + planned_batch > 15`, warn and stop; don't partial-upload (leaves orphan products with no batches).
3. If `.plan` is any of the 5 codes → treat as unlimited for products; `bulk_add` and Excel exports are allowed.
4. 500-variant and unique-SKU limits apply on every plan — validate the source file for these regardless.
5. Don't surface payment-charge or staff-limit differences during an upload; only if the user asks about plans, staff, or charges directly.

## Categories (embedded on the Store, optional in upload flow)

**Categories are NOT a separate collection.** They're subdocs on the Store document: `store.categories[]`. This shapes every "list" and "check" op — you read them by fetching the store, not from a `/categories` endpoint.

**Each category shape** (from `GET /store/{store_id}` → `.categories[]`):

```jsonc
{
  "_id": "...",
  "name": "Snacks",
  "slug": "snacks",
  "order": 999,
  "image": "",
  "hide_on_product": false,
  "seo_title": "",
  "seo_description": "",
  "seo_image": "",
  "views": 0
}
```

**Endpoints** (all mounted under `/store`):

| Verb + Path | Purpose | Auth |
|---|---|---|
| `GET /store/{store_id}` → `.categories[]` | List / get / existence-check (client-side match) | any store user |
| `POST /store/{store_id}/add_category` | Create | owner / manager |
| `POST /store/{store_id}/update_category/{cat_id}` | Update fields | owner / manager |
| `DELETE /store/{store_id}/remove_category/{cat_id}` | Delete | owner / manager |
| `POST /store/{store_id}/update_category_order` | Reorder | owner / manager |

**Create body** (only `name` matters; `slug` auto-generates, `parent` optional for sub-categories):

```
POST /store/{store_id}/add_category
{
  "name": "Snacks",
  "parent": "",
  "image": "",
  "hide_on_product": false,
  "seo_title": "", "seo_description": "", "seo_image": ""
}
→ { "success": true, "category": { "_id": "...", "name": "Snacks", "slug": "snacks", "order": 999, ... } }
```

`slug` is auto-derived from `name`; if it collides or equals `new-arrivals`, the server appends random chars. Grab the returned `_id` — this is what `POST /product`'s `categories: [...]` expects.

**⚠ How categories tie into product create — no server-side validation.**

`POST /product/{store_id}` accepts a `categories: ["<cat_id>", ...]` array of ObjectId strings. The handler builds an `id → name` map from the store's categories but **does NOT reject unknown ids** — a bad id is stored as a dangling reference on the product silently, showing as a broken chip in the dashboard. So:

- **Only pass `_id`s you actually resolved from `store.categories[]`.** Never make up ids or reuse ids from a different store.
- **Leave `categories: []` to skip entirely** — safer than guessing.

## Delivery charge (premium-gated, out-of-band from the product flow)

Not part of the upload flow, but documented here because it lives on `/store` and gets asked about. **Both read and write are premium-gated** — a plan-less store gets `not_allowed` on either.

**Read** — `read-delivery-charge.ts`. Auth: any store user (+ premium).

```
GET /store/{store_id}/delivery_charge
→ {
    "defaults": [c0, c1, c2, c3, c4, c5],                           // 6 weight-tier default prices
    "places":  [ ["Kathmandu Inside Ring Road", true, v0, v1, v2, v3, v4, v5], ... ]
  }
```

- Data lives in **DynamoDB** (not the store doc), Redis-cached under `{store_id}_delivery_charge_v3`.
- If never configured, returns a fresh template: `defaults: [0,0,0,0,0,0]` and all ~92 districts pre-listed (from `costCodes`) with values `-1`.
- Auto-migrates the legacy single-price format into this shape on read.

**Update** — `update-delivery-charge.ts`. Auth: owner/manager (+ premium).

```
POST /store/{store_id}/delivery_charge
Content-Type: application/json  + CF browser headers

{
  "defaults": [120, 150, 200, 250, 350, 500],                        // EXACTLY 6 non-negative ints
  "places": [
    ["Kathmandu Inside Ring Road", true, 100, 120, 150, 200, 300, 450],
    ["Pokhara", true, -1, -1, -1, -1, -1, -1],                       // -1 = fall back to defaults[col]
    ...                                                              // at least 2 place rows required
  ]
}
→ { "success": true }
```

**Weight-tier column meaning** (from `CustomDeliveryCharges.tsx`):

| Slot | Weight bracket |
|---|---|
| 0 | 0–1 kg |
| 1 | 1–2 kg |
| 2 | 2–3 kg |
| 3 | 3–5 kg |
| 4 | 5–10 kg |
| 5 | > 10 kg |

Each place row: `[districtName: string, enabled: boolean, ...6 weight-tier prices]`. A value of `-1` in any slot means "inherit `defaults[thatSlot]`" for that district — use it to avoid duplicating numbers.

**⚠ Full-document overwrite, not partial.** The POST **replaces the entire DynamoDB record**. To adjust one charge, always: **GET current → mutate arrays in memory → POST the complete `{defaults, places}` back**. A partial payload wipes what you omit.

**Strict schema validation:**
- `defaults` must be **exactly 6 integers**, each `≥ 0`.
- `places` must have **≥ 2 rows** — validation fails otherwise.
- Each place row must be `[string, boolean, int, int, int, int, int, int]`.

**Non-premium fallback**: plan-less stores can't use `/delivery_charge` at all. They use the legacy flat fields `setting.delivery_charge_valley` and `setting.delivery_charge_out_valley` on the store doc, updated via `POST /store/{store_id}/customization-style` — different endpoint, single-price semantics, no district-per-weight matrix.

**CF**: the POST needs the browser-like headers (`User-Agent`, `Origin`, `Referer`).

## Suppliers (POS-finance, optional in the upload flow)

Mounted at `/pos-finance`. Suppliers are a **record-keeping** entity — they exist for payable tracking in POS-finance, not for automatic stock↔vendor linking. See the linkage caveat below before wiring this into any upload logic.

**Search / list** — `get-suppliers.ts`. Auth: any store user.

```
GET /pos-finance/suppliers/{store_id}?q=<optional case-insensitive name substring>
→ { "suppliers": [ { "_id", "name", "contact_person", "phone", "email", "address", "pan", "opening_balance", "current_balance", "notes" }, ... ] }
```

Omit `q` to list all. Soft-deleted suppliers excluded; sorted by name.

**Create** — `create-supplier.ts`. Auth: **owner / manager only**. `name` is the only required field.

```
POST /pos-finance/suppliers/{store_id}
{ "name": "ABC Traders", "contact_person": "", "phone": "", "email": "", "address": "", "pan": "", "opening_balance": 0, "notes": "" }
→ { "success": true, "supplier": { "_id": "...", ... } }
```

**Update / balance / ledger / entry** (not needed for the upload flow, but useful to know they exist):

- `PATCH /pos-finance/suppliers/{store_id}/{id}` — edit supplier fields.
- `GET /pos-finance/supplier-balance/{store_id}/{id}` — current payable/receivable balance.
- `GET /pos-finance/supplier-ledger/{store_id}/{id}` — full ledger history.
- `POST /pos-finance/supplier-entry/{store_id}/{id}` — record a payable (purchase on credit) or a payment. This is the endpoint the user hits *if* they want the current stock-in to hit the supplier's payable ledger — it's not automatic.

**⚠ Critical linkage caveat — supplier does NOT attach to stock-in.**

The `Batch` mongoose schema has a `supplier` ObjectId field, but the `POST /inventory/stock-in` handler **never sets it**. What it does write is `batch.supplier_ref: <reference_number>` — a free-text field derived from the `reference_number` you pass in. So:

- Picking or creating a supplier does not create an automatic link to the newly stocked-in batch.
- The only supplier trace that reaches a batch today is whatever string you send in `stock-in.reference_number`.
- Supplier accounting (payables, ledger, balance) is a separate POS-finance flow via `supplier-entry` — never triggered as a side-effect of stock-in.

**How to actually attach a supplier to inventory** (as much as the API allows):

1. Search / create supplier as above, capture `_id` and `name`.
2. In the `stock-in` call, put a stable descriptor into `reference_number`: `"ABC Traders / INV-4471"` (name + invoice number if the user has it). This becomes `batch.supplier_ref` and is searchable in stock movement logs.
3. If the user explicitly wants the batch value recorded as payable to that supplier, follow up with `POST /pos-finance/supplier-entry/{store_id}/{supplier_id}` — separate action, ask before firing.

## Inventory adjustment (post-upload corrections)

There is no single "set quantity to X" endpoint — the ledger model uses batches. Pick the right verb:

| Goal | Endpoint | Notes |
|---|---|---|
| Increase stock | `POST /inventory/stock-in` | Creates a new batch. Same payload as the initial upload flow. |
| Decrease / correct count | `POST /inventory/write-off` (subtype `COUNT_CORRECTION`) | Pulls from specific batches — you need `batch_id`. |
| Move between outlets | `POST /inventory/transfer-stock` | `{store_id, outlet_id, target_outlet, batches:[{batch_id, quantity}]}`. Role: `transfer_stock`. |

### Discovering `batch_id`

```
GET /inventory/batch/{store_id}?product={product_id}&outlet={outlet_id}&hasStock=true
```

Response: `{meta, items: [{_id (batch_id), product:{_id, name, ...}, batch_no, cost_price, outlet, quantity, initial_quantity, last_in_at, ...}]}`. For freshly-uploaded products there's typically one batch per outlet.

Alternate: `?group_id=<outletId>-<productId>-<variantId>` shortcut.

### Write-off (used for the "notebook says -1" correction)

```
POST /inventory/write-off
Authorization: Bearer <token>  + CF browser headers
Content-Type: application/json

{
  "store_id":  "<id>",
  "outlet_id": "<id>",
  "subtype":   "COUNT_CORRECTION",   // or DAMAGED | EXPIRED | LOST | THEFT | PURCHASE_RETURN | SYSTEM_FIX
  "reference_number": "bill notebook -1 correction",
  "batches": [ { "batch_id": "<id>", "quantity": 1 } ]
}
```

Response: `{"success": true}`. `user_id` is taken from the token, not the body. Role required: `write_off`.

### Transfer between outlets

**Scope**: same store only. Blanxer has no cross-store transfer endpoint — a store's inventory is siloed. This moves stock between two outlets that both belong to the same `store_id`.

```
POST /inventory/transfer-stock
Authorization: Bearer <token>  + CF browser headers
Content-Type: application/json

{
  "store_id":      "<store_id>",
  "outlet_id":     "<source_outlet_id>",
  "target_outlet": "<destination_outlet_id>",
  "reference_number": "",
  "batches": [ { "batch_id": "<id>", "quantity": 5 } ]   // qty ≥ 1, batch_ids must be unique in the array
}
```

Response: `{"success": true}`. Role required: `transfer_stock`. Handler: `action-transfer-stock.ts` → `handleBatchTransfer.ts`.

**Internal behavior**: for each source batch (must be `is_active`, in the source outlet, belonging to the store), the server writes a `TRANSFER_OUT` log at the source and a matching `TRANSFER_IN` log at the target, then moves the quantity across `inventory_summary` atomically.

**Guards that will 400 / throw** — pre-check these before calling:

- `outlet_id === target_outlet` (source can't equal destination).
- Duplicate `batch_id`s in the `batches` array.
- Any `batch_id` not found, inactive, or not in the source outlet → server responds "Some source batches were not found".
- `quantity` less than 1, or greater than the batch's `current_stock`.

**Flow to build a transfer:**

1. `GET /inventory/outlets/{store_id}` → resolve source `outlet_id` and destination `target_outlet`.
2. `GET /inventory/batch/{store_id}?outlet={source_outlet}&product={id}&hasStock=true` → pick `batch_id`s that have enough stock.
3. `POST /inventory/transfer-stock` with the batches array.
4. Verify: `GET /inventory/list/{store_id}?outlet={target_outlet}&product_id={id}` should show the transferred quantity as `current_stock` at the destination; source's `current_stock` should have dropped by the same amount.

### Image upload (before create)

`image_urls[]` on the create-product payload expects finished S3 URLs. There's no way to attach a raw file in the create call — upload each image first, collect the URLs, then include them in the create.

```
POST /product/{store_id}/file
Authorization: Bearer <token>  + CF browser headers
Content-Type: multipart/form-data

file:            <image binary>          (form field literally named "file")
upload_purpose:  product_image           (required; or "product_description" for rich-text images)
```

Response: `{"success": true, "file": {"file_url": "https://.../uploads/{store}/product_image-....jpg", "file_key": "...", "size": 12345, ...}}`. Handler: `product.controller.ts uploadFile`. Auth: owner / manager.

One call per image. **The first URL in `image_urls[]` becomes the primary/thumbnail** — order matters.

Alternate: `POST /product/{store_id}/{product_id}/file` (public, no `upload_purpose` needed) for images added to an already-created product. For the upload flow, use `/product/{store_id}/file` before create.

**Server auto-converts raster images to WebP.** `fileUpload()` on the product routes is called without options (`product.routes.ts:83`) so `express-fileupload` applies no size cap, no `abortOnLimit`, and no MIME allowlist. The global `express.json()` / `urlencoded()` ~100 KB cap (`app.ts:29`) does NOT apply — multipart bypasses the JSON parser entirely. But `s3helper.ts s3Upload` (and its R2 mirror) rewrites the extension and pipes the body through `sharp(...).webp({ quality: 95 })` for any raster `image/*` mimetype:

| You upload | Stored as | Notes |
|---|---|---|
| JPG / PNG / HEIC / any raster `image/*` | **WebP quality 95** | Extension rewritten to `.webp`; `file_url` ends in `.webp`. |
| SVG (`image/svg…`) | SVG, as-is | Only image type left untouched. |
| Non-image (PDF, etc.) | Original mimetype, as-is | No conversion. |

**Practical rules for callers:**

- **Don't pre-convert format.** Send JPG/PNG straight from disk — the server converts to WebP for you. Trying to send WebP yourself just adds a round-trip.
- **Do downscale huge source images.** Files are buffered in memory + sharp reprocesses them; there's no code-level size cap but there's likely an upstream nginx / gateway limit and phone photos can hit it. If a batch will run into hundreds of MB, downscale to ~2000px on the long edge before upload.
- **Don't send corrupt / non-image bytes with an `image/*` mimetype.** `sharp` is the implicit validator — if it can't decode, `.webp()` throws and you get a `500`.
- **The `file_url` you save into `image_urls[]` will always be a `.webp` URL** for raster inputs. That's fine — the storefront and POS UI serve it directly.

**Fail-soft rule:** if one image fails to upload, still create the product with whatever URLs succeeded rather than aborting the whole product. Log the failure and let the user re-upload later via `/product/{store_id}/{product_id}/file`.

### Store settings — `GET /store/{store_id}`

```
GET /store/{store_id}
Authorization: Bearer <token>
```

Handler: `store.controller.ts getStoreDetails`. Returns the entire store document; payment-gateway secrets under `setting` are stripped for non-owners.

**Verified live response shape** (Example Store, 2026-07-20):

```jsonc
{
  "_id": "507f1f77bcf86cd799439011",
  "name": "Example Store",
  "plan": "platinum",                     // top-level string — the plan-gate field
  "use_advanced_inventory": true,
  "customization": { "image_ratio": 2 },  // 1=1:1, 2=4:3, 3=16:9
  "setting": { /* payment secrets stripped for non-owners */ },
  ...
}
```

Confirmed: `.plan` is a top-level string, not nested. Empty/missing `plan` means the store has no paid subscription; any of the 5 paid codes means fully-premium.

Only image-related config lives at `customization.image_ratio`:

| Value | Aspect ratio |
|---|---|
| `1` | 1:1 (square) |
| `2` | 4:3 |
| `3` | 16:9 |

This is a **display aspect ratio only** — the storefront crops uploaded images to it at render time, but the file stored on S3 is the full-frame WebP (see "Image upload" above for the auto-conversion). There is no store-level dimension, size, or MIME setting; `image_ratio` is the entire image-related config surface. If you want the storefront cards to look right, either (a) pre-crop the source image to that ratio before uploading, or (b) accept that off-center subjects will get chopped by the render-time crop.

```
curl -s "https://api.blanxer.com/store/$STORE_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.customization.image_ratio'
```

### Full Web + POS upload flow (with images)

Web vs POS differ only in `channel` (Website `2`, POS `3`, All `1`); everything else — including the inventory step — is identical.

```
0. POST /api-key/check                     → {token, store._id}                (or reuse dashboard token)
1. GET  /store/{store_id}                  → read .plan, .use_advanced_inventory + .website_outlet, .customization.image_ratio
2. Detect mode: isAdvancedInventory = use_advanced_inventory === true && !!website_outlet
                (do NOT auto-run /inventory/enable — Platinum-only, one-way, requires outlet body)
3. [advanced only] GET /inventory/outlets/{store_id}  → pick outlet_id
── per product ──
4. POST /product/{store_id}/file           → upload each image, collect file_url[]
5. POST /product/{store_id}                → create with channel + image_urls, capture _id
6. [advanced inv] POST /inventory/stock-in { outlet_id, items:[{product_id, variant_id?, quantity, cost_price}] }
   [simple inv]    quantity from step 5 is already applied — no stock-in needed
── after batch ──
7. POST /order/print_request  +  GET /product/generate_barcode_quantity/...    → barcodes.pdf
8. GET  /inventory/list/{store_id}         → verify
```

**Web vs POS differences to remember:**

- `channel`: **Website = `2`**, **POS = `3`**, **All (both) = `1`**.
- **Images on Website**: `image_urls[]` is effectively mandatory — storefront cards show them, missing images look broken.
- **Images on POS-only**: optional — POS list works off name/barcode.
- Inventory model is identical either way — `use_advanced_inventory` decides whether `quantity` in the create body is applied directly (OFF) or forced to 0 with stock-in required (ON).

**Validation caps (server-side zod):**

| Field | Constraint |
|---|---|
| `name` | max 2000 chars |
| `price`, `compare_at_price`, `cost_per_item`, `weight` | ≥ 0 |
| Advanced-inventory `quantity` on create | forced to 0 regardless of what's sent |
| `stock-in.items[].quantity`, `write-off.batches[].quantity` | ≥ 1 |
| CF shielding on all POST/DELETE | browser headers or 403 `error code: 1010` |

### Deleting a product cleanly

`DELETE /product/{store_id}/{product_id}` (owner only, `product.service.ts:63`) only removes the Product document. It does **not** cascade to `Batch`, `StockLedger`, or `inventory_summary` — those become orphaned stock, still counted in totals dashboards and outlet on-hand until explicitly written off.

**Correct order: write-off first, then delete.**

**Step 1 — discover remaining batches for the product across all outlets:**

```
GET /inventory/batch/{store_id}?product={product_id}&hasStock=true&per_page=100
```

The batch collection is queried by `product` field, so this works whether the Product doc still exists or not. Each returned item has `_id` (the `batch_id`), `outlet`, and `quantity`. Group items by `outlet`.

If `meta.total === 0`, skip to Step 3.

**Step 2 — write off, one call per distinct outlet:**

```
POST /inventory/write-off
{
  "store_id":  "<store_id>",
  "outlet_id": "<outlet_id>",                            // ONE call per outlet
  "subtype":   "SYSTEM_FIX",                             // product-deletion cleanup (COUNT_CORRECTION also works)
  "reference_number": "Product deletion cleanup",
  "batches": [
    { "batch_id": "<batch_id>", "quantity": <remaining qty for that batch> }
  ]
}
```

Repeat for each outlet that had stock. Write-off requires `is_active: true` batches with `quantity >= requested`. Role required: `write_off`.

**Step 3 — delete the product:**

```
DELETE /product/{store_id}/{product_id}
```

Response: `{"success": true}`. Role required: `owner`.

**Why order matters:** if you delete first, the subsequent write-off's `Product.inventory_summary` update matches no document and silently no-ops, so the ledger records the deduction but the summary field stays stale. Write-off before delete keeps `quantity`, `inventory_summary`, and the stock ledger consistent — the delete is then a clean removal with zero orphaned stock.

**Role recap:**
- Delete a product: **owner only** (`validateStoreRole(..., ['owner'])`).
- Write off stock: **any user with `write_off` inventory role** (owner/manager/csr with the role granted).
- A store manager can therefore clean up stock but can't delete the product itself.

### Barcode PDF generation (post-upload label printing)

Barcodes are auto-assigned on `POST /product/{store_id}` — the product doc's `barcode` field is set at creation time (base 100 + product number for the base product, plus per-variant barcodes). There's no separate "generate barcode" step for the codes themselves. What you're generating in this flow is the **printable label PDF** — one page per physical unit.

The flow reuses Blanxer's order-label print-request machinery with `print_for: 2` (barcodes) instead of `1` (shipping labels).

**Step 1 — create a print request:**

```
POST /order/print_request/{store_id}
Authorization: Bearer <token>  + CF browser headers
Content-Type: application/json

{
  "orders": ["<product_id>", "<product_id>", ...],   // ⚠ misnomer: these are PRODUCT ids, not order ids
  "print_for": 2                                      // 2 = barcodes, 1 = shipping labels
}
```

Response: `{"success": true, "id": "<print_id>"}`. Handler: `print-request.ts`. Any authenticated store user.

**Step 2 — download the PDF:**

```
GET /product/generate_barcode_quantity/{store_id}/{print_id}
    ?token=<JWT>
    &quantities=<url-encoded JSON>
    &show_name=true&show_price=true&show_barcode=true
```

Streams `application/pdf` with `Content-Disposition: inline; filename="barcodes.pdf"`. **Save the response body straight to a `.pdf` file** — the CLI just needs to write bytes.

- **`token` goes in the query string, not the header.** The UI opens this in a new tab, so `authRoleCheck()` reads the JWT from the query. This is why it works as a plain download URL.
- **`quantities`** is a URL-encoded JSON map: `{ "<productId or variantId>": <label count> }`. If omitted, falls back to each product's stored `quantity`.
- **Key semantics**: use `variant._id` for variant products; use `product._id` for simple (non-variant) products. Mixing them will drop labels.
- Backend validates `print_for === 2` and that the print-request's store matches — mismatch throws.

Sibling endpoint `GET /product/generate_barcode/{store_id}/{print_id}` (no `quantities`) prints one label per unit of the product's stored `quantity` — simpler but less precise. For the upload flow, use `_quantity` since you know exactly how many you stocked in (and can subtract for any post-upload write-offs).

**Label option query flags** (from `barcodeSchema`): all boolean — `show_name`, `show_variant`, `show_price`, `show_barcode`, `show_store`, `show_crossed_price`, `show_company_info`, `use_alt_barcode`, `prefix_barcode`, plus style switches `jewelry_tag`, `jewelry_cutout`, `mrp_label`, `mrp_center`.

**⚠ Title-line logic on the default 50×25mm label (barcode-utils.ts:143-155)** — the top line of the label is chosen by an `if / else-if`, so `show_store` wins over `show_name`:

```js
if      (options.flags.show_store) → storeName.toUpperCase()
else if (options.flags.show_name)  → productName.toUpperCase()
```

**Defaults are not what you'd guess.** Every flag in `barcodeSchema` uses `booleanField`, which has `.default(true)` (barcode-utils.ts:18-29). So **omitting `show_store` does NOT mean false — it defaults to `true` and the title becomes the store name**, regardless of what `show_name` is set to. The only flags that default to `false` are `show_crossed_price`, `jewelry_*`, `mrp_*`, `show_company_info`.

**Rule: to get the product name as the title, you must send `&show_name=true&show_store=false` explicitly.** Full working GET:

```
GET /product/generate_barcode/{store_id}/{print_id}
    ?token=<JWT>&show_name=true&show_store=false&show_price=true&show_barcode=true
```

**Layout variants where the logic differs:**

- **Jewelry tag / jewelry cutout** (barcode-utils.ts:259-273, 359-373) — NOT `else-if`; both lines print. Store on line 1, product name on line 2. `show_store=false` still gets product name to the top.
- **MRP label** (barcode-utils.ts:445-453) — only `show_name` matters for the title; prints `Product - Variant`. Store name only appears in the small "Imported & distributed by" block at the bottom.

**Cross-reference in Blanxer's own clients**: the dashboard label modal defaults `show_store: false` and force-clears `show_name` when the user ticks "store". Following the same convention in this skill keeps behavior identical to the UI.

**⚠ Cloudflare on the PDF GET**: contrary to the assumption that only mutating requests need browser headers, `GET /product/generate_barcode_quantity/...` also returns `403` from Cloudflare without `User-Agent` + `Origin` + `Referer` (confirmed 2026-07-20). Always send the browser headers on this GET too. The POST print-request definitely needs them (it's a POST).

**Note on the barcode value itself (no separate endpoint)** — the scannable code on each label is assigned at product creation, not generated separately:
- `productNumber = 100 + store.product_count` (atomic `$inc` in utils.ts:169; see add-product.ts:115-116).
- Base product → `barcode: productNumber`; variants → `${productNumber}${getVariantNumber(i+1)}` (3-digit padded, e.g. `104001`).
- Bulk path does the same at bulk-product-add.ts:296-303.
- Rendered as Code128 via bwip-js (barcode-utils.ts:114). No "regenerate barcode value" API exists.

**Post-upload recipe (recommended for the automated flow):**

1. Collect `product_id`s from the upload loop.
2. Fetch authoritative `current_stock` per product via `GET /inventory/list/{store_id}?outlet={outlet_id}&per_page=100` — this reflects any post-upload write-offs.
3. Build `quantities` map: `{product_id: current_stock}`. For variant products, key by `variant._id` instead.
4. `POST /order/print_request/{store_id}` with `orders: [pids]` + `print_for: 2` → get `print_id`.
5. `GET /product/generate_barcode_quantity/{store_id}/{print_id}` (query string: `token`, url-encoded `quantities`, label flags) with CF browser headers → save PDF.
6. Copy PDF next to the source CSV or into the source folder (e.g. `<DDMMM Entry>/barcodes.pdf`) so the user can find it.

### Reprinting barcodes on demand ("download later")

**Print requests are reusable and unrelated to the upload session** — you can generate a fresh one for any existing products at any time. The barcode value on each label is the product's persistent `barcode` field (set at creation), so reprints months later produce the same scannable code.

Two modes are exposed on the product page — both are the same two-step flow, differing only in the download endpoint:

| Mode | Endpoint | Copies per item |
|---|---|---|
| **Simple** — one label per current stock unit | `GET /product/generate_barcode/{store_id}/{print_id}` | Reads product's live `quantity` (or variant.`quantity`). No `quantities` param needed. |
| **By quantity** — caller picks count | `GET /product/generate_barcode_quantity/{store_id}/{print_id}` | From URL-encoded `quantities` JSON. Falls back to stored qty if omitted. |

Both accept `?token=<JWT>` + the same label flags. Both need CF browser headers.

**Step 0 — discover product IDs** (skip if you already have them from an earlier upload or from context):

- `GET /product/pos/{store_id}` — POS product listing. Use for searching by name.
- `GET /product/{store_id}/{product_id}` — fetch a single product (returns `barcode` + `variants[].barcode` too).

**Steps 1 & 2 — identical to the post-upload flow:**

```
POST /order/print_request/{store_id}
{ "orders": ["<product_id>", ...], "print_for": 2 }
→ { "success": true, "id": "<print_id>" }
```

Then either:

```
# Simple mode (reprint from product page default — reads stored qty)
GET /product/generate_barcode/{store_id}/{print_id}
    ?token=<JWT>&show_name=true&show_price=true&show_barcode=true

# By-quantity mode (caller picks per-product count)
GET /product/generate_barcode_quantity/{store_id}/{print_id}
    ?token=<JWT>
    &quantities=<url-encoded {"<pid_or_vid>": <count>, ...}>
    &show_name=true&show_barcode=true
```

**When to pick which:**
- **Simple** = natural default for a UI-style "reprint labels for this product" ask ("print labels for `3. 12/7 sall set`"). Zero bookkeeping — it just uses live stock.
- **By-quantity** = you want a specific count regardless of stock ("give me 3 spare labels for damaged tags", "print 10 of everything for a booth").

**Variant products:** for `quantities` map, key by `variant._id`; simple mode automatically uses each variant's stored `quantity`.

### Read-back / verify

```
GET /inventory/list/{store_id}?outlet={outlet_id}&product_id={id}&page=1&per_page=15
```

Response: `{meta, items: [{_id:{product,variant,outlet}, product_name, sku, current_stock, cost_price, selling_price, batch_count, stock_status}]}`. `outlet` and `product_id` are optional filters. Role: `get_inv_list`.

Summary cards (totals, low/dead/expiring counts):

```
GET /inventory/summary/{store_id}?outlet={outlet_id}   # &fresh=1 bypasses 1h cache
```

Movement history: `GET /inventory/stock-movement-logs/{store_id}` and `.../stock-movement-detail/{store_id}/{sm_id}`.

### "Adjust to target quantity" recipe

1. `GET /inventory/list/{store_id}?outlet=...&product_id=...` → read `current_stock`.
2. Compute delta = target − current.
3. If delta > 0 → `POST /inventory/stock-in` with `quantity: delta`.
4. If delta < 0 → `GET /inventory/batch/...&hasStock=true` to get `batch_id`, then `POST /inventory/write-off` with `subtype: "COUNT_CORRECTION"` and `quantity: |delta|`.
5. Re-check via `/inventory/list` or `/inventory/summary?fresh=1`.

## Channel mapping observation

The UI dropdown shows `All / Website / POS` and the internal codes from a live capture were `1 / 2 / 3` respectively (confirmed for POS = 3 by submitting with that selection and seeing `"channel":3` in the body).

## Orders (mount `/order`)

Feature dir: `features/order/`. Handles storefront checkout, admin/POS create, edit-items, status updates, courier submits, labels, reviews, exports. Routes: `features/order/routes.ts`. Handlers: `features/order/task/*` (re-exported via `task/index.ts`).

Auth conventions: `authRoleCheck()` with no args = any authenticated store user; `authRoleCheck('owner','manager','csr')` = restricted. `authFromApiKey()` = api-key path (used by Sambad marketplace). Public routes have no middleware.

**Complete route table (41 routes):**

| # | Method | Path | Auth | Handler |
|---|---|---|---|---|
| 1 | GET | `/get_tracking_link/:order_id` | public | getTrackingLinkFromOrder |
| 2 | GET | `/public/:store_id/id/:order_id` | public | publicGetOrderDetails |
| 3 | POST | `/public/submit-review` | public | publicReview |
| 4 | POST | `/public/cancel` | public | publicCancelOrder |
| 5 | POST | `/:store_id([0-9a-f]{24})` | public + orderLimiter | createOrder (storefront) |
| 6 | GET | `/delivery_address_for_upaye/:store_id` | any auth | getAddressForUpaye |
| 7 | GET | `/pick-and-drop-branches/:store_id` | any auth | getPickAndDropBranches |
| 8 | GET | `/pick-and-drop-addresses/:store_id` | any auth | getPickAndDropAddresses |
| 9 | GET | `/:store_id/export_order` | owner, manager | exportOrderToExcel |
| 10 | GET | `/:store_id/export_order/v2` | owner, manager | exportOrderToExcelV2 |
| 11 | GET | `/:store_id/reviews` | owner, manager, csr | getStoreReviews |
| 12 | GET | `/sales_overview/:store_id/:product_id` | owner, manager | salesOverview |
| 13 | GET | `/print_request/:store_id/:print_id` | any auth | getOrderFromPrintRequest |
| 14 | GET | `/:store_id` | any auth | getStoreOrders |
| 15 | GET | `/dispatched/:store_id` | any auth | getDispatchedOrders |
| 16 | GET | `/:store_id/:order_id` | any auth | getOrderDetails |
| 17 | POST | `/:store_id([0-9a-f]{24})` | public + orderLimiter | ⚠ DUPLICATE of #5 |
| 18 | POST | `/sambad/create` | `authFromApiKey()` | sambadCreateOrder |
| 19 | POST | `/create/:store_id` | owner, manager, csr | adminCreateOrder |
| 20 | POST | `/create-lead/:store_id` | owner, manager, csr | adminCreateLead |
| 21 | POST | `/create-via-pos/:store_id` | owner, manager, csr | posCreateOrder |
| 22 | POST | `/pos-check-qr-status/:store_id` | owner, manager, csr | posCheckQrPayment |
| 23 | POST | `/create_label/:store_id` | owner, manager, csr | createLabel |
| 24 | POST | `/update_label/:store_id/:order_id` | owner, manager, csr | updateOrderLabel |
| 25 | POST | `/change_order/:store_id/:order_id` | owner, manager, csr | changeOrderItems |
| 26 | POST | `/print_request/:store_id` | any auth | printRequest |
| 27 | POST | `/:store_id/:order_id/aramex` | owner, manager, csr | submitToAramex |
| 28 | POST | `/:store_id/:order_id/ncm` | owner, manager, csr | submitToNcm |
| 29 | POST | `/:store_id/:order_id/dash` | owner, manager, csr | submitToDash |
| 30 | POST | `/:store_id/:order_id/pathao` | owner, manager, csr | submitToPathao |
| 31 | POST | `/:store_id/:order_id/upaya` | owner, manager, csr | submitToUpaye |
| 32 | POST | `/:store_id/:order_id/fabbud` | owner, manager, csr | submitToFabbud |
| 33 | POST | `/:store_id/:order_id/pick-and-drop` | owner, manager, csr | submitToPickAndDrop |
| 34 | POST | `/:store_id/:order_id/daraz` | owner, manager, csr | submitToDaraz |
| 35 | DELETE | `/:store_id/:order_id` | owner, manager, csr | deleteOrder |
| 36 | POST | `/:store_id/delete_bulk` | owner, manager | deleteOrderBulk |
| 37 | POST | `/:store_id/:order_id/status` | owner, manager, csr | updateStatus |
| 38 | POST | `/:store_id/bulk_status` | owner, manager, csr | updateStatusBulk |
| 39 | POST | `/:store_id/:order_id/customer` | owner, manager, csr | updateCustomerDetails |
| 40 | DELETE | `/label/:store_id/:label_id` | owner, manager | deleteLabel |
| 41 | DELETE | `/:store_id/:order_id` | owner, manager, csr | ⚠ DUPLICATE of #35 |

**Rate limiter (`orderLimiter`)**: 5 requests / 10 min, keyed by `${store_id}_${ip}`. Applied only to the public `createOrder` (routes 5 & 17).

**Duplicate registrations**: `POST /:store_id` (routes 5 & 17) and `DELETE /:store_id/:order_id` (routes 35 & 41) are each registered twice. The first registration wins in Express — the second is dead code.

### Admin create — `POST /order/create/:store_id`

```json
{
  "customer_id": "<mongo_id>",
  "products": [
    { "product": "<product_id>", "variant": "<variant_id>", "quantity": 2 },
    { "product": "", "name": "Gift wrap", "price": 150, "cost_price": 50, "quantity": 1 }
  ],
  "customer_full_name": "Ram",
  "customer_address_city": "Kathmandu",
  "customer_address": "Main Branch",
  "customer_address_landmark": "",
  "order_note": "",
  "override_delivery_charge": -1,
  "discount": 0,
  "payment_status": "Paid",
  "payment_method": "cash",
  "partial_payment_amount": 0,
  "force": false
}
→ { "status": "success", "_id", "order_number" }
   // or { "status": "halt", ... } if same-phone order exists within 7 days and force=false
```

### POS sale — `POST /order/create-via-pos/:store_id`

```json
{
  "outlet": "<outlet_id>",
  "customer_id": "",
  "products": [ { "product": "", "name": "Loose item", "price": 200, "quantity": 1 } ],
  "discount": 0,
  "payment_method": "split",
  "cash_amount": 200,
  "qr_amount": 300,
  "pan": "", "company_name": ""
}
→ { success, order:{…}, customer, cashier,
    store:{name,address,phone_number,receipt_footer},
    qr_data: { prn, socket_url, qr_payload, amount } | null }
```

- `outlet` is required when advanced inventory is ON.
- `split` requires both `cash_amount>0` and `qr_amount>0`, and `cash+qr == total-discount`.
- `qr` / `split` trigger Fonepay dynamic QR — poll `POST /order/pos-check-qr-status/:store_id`.
- POS orders are created with `status: "Completed"`, `channel: 3` (POS).

### ⚠ Custom (non-catalog) line items

There is **no `is_custom` flag**. A line is "custom" purely when `product` is empty and you supply `name` + `price` (+ `cost_price` where accepted). Stored as `{product_name, price, quantity}` with no `product_id`.

| Endpoint | Custom items? |
|---|---|
| Admin create `/create` | ✅ |
| Lead create `/create-lead` | ✅ |
| POS create `/create-via-pos` | ✅ |
| Change items `/change_order` | ✅ |
| Public checkout `POST /:store_id` | ❌ — every line must reference a real catalog product id |

### Edit line items — `POST /order/change_order/:store_id/:order_id`

```json
{
  "products": [
    { "product": "<id>", "quantity": 3 },
    { "product": "", "name": "X", "price": 100, "quantity": 1 }
  ],
  "partial_payment_amount": -1,
  "discount": -1,
  "delivery_charge": -1
}
→ { "success": true }
```

Sentinel values: `-1` = keep current, `0` = clear (partial → `Unpaid`), `>0` = set (partial → `Partial`). `discount: -1` ignored if the order came from a coupon.

Editable only when `status ∈ {Draft, Pending, Processing}` and `payment_status != "Paid"`. The single-order GET returns a `can_edit_items` boolean telling you this upfront.

### Update status / payment — `POST /order/:store_id/:order_id/status`

```json
{
  "status": "Dispatched",
  "payment_status": "Paid",
  "payment_method": "cash"
}
→ { "success": true }
```

- `status` and `payment_status` are both required.
- `payment_method` is **rejected if a gateway Transaction already exists** for the order (you can't overwrite gateway records).
- Moving into `Cancelled`/`Returned` restores inventory; moving out re-reduces it.
- `Dispatched`/`Delivered` also set `dispatched_at`/`delivered_at`, fire SMS + delivered email.

### Enums (order-level, stored as strings)

**Order status**: `Inactive` (unpaid online / lead), `Draft`, `Pending`, `Processing`, `Waiting Pickup`, `Dispatched`, `Delivered`, `Cancelled`, `Returned`, `Completed` (POS only).

**payment_status**: `Paid`, `Unpaid`, `Partial`, `Pending`, `Processing`, `Failed`, `Refunded`.

**payment_method** (string on the order):

| Value | Meaning | | Value | Meaning |
|---|---|---|---|---|
| `COD` | Cash on delivery || `khalti` | Khalti wallet |
| `cash` | Cash (POS/manual) || `connectips` | ConnectIPS |
| `qr` | Fonepay dynamic QR || `bank_deposit` | Manual bank deposit |
| `fonepay` | Fonepay || `card` | Card |
| `esewa` | eSewa || `nps` | Nepal Payment Solution |
| `nabil_card` | Nabil card || `split` | POS cash+QR (POS only) |
| `Manual` | auto-set when `Paid` w/ no method |||||

**channel** (numeric): `1` Manual · `2` Web (default) · `3` POS · `4` Sambad · `5` Marketplace.
**logistics** (numeric): `0` None · `1` Aramex · `2` Pathao · `3` NCM · `4` Dash · `5` Upaya · `6` Fabbud · `7` Pick&Drop · `8` Daraz.

**`ordered_products` subdoc**: `product_id?` (absent for custom), `product_name`, `price`, `compare_at_price`, `cost_per_item`, `customization_charge`, `variant_id`, `variant_name`, `quantity`, `remained_quantity`, `sku`, `discount_amount`, `custom_fields[]`, `categories[]`.

**Order-level discount**: `{discount_id, code, d_value, d_type(1 FLAT | 2 PERCENT | 3 SHIPPING)}`.

**Partial-payment integrity rule** (all endpoints): `discount + partial_payment_amount ≤ product_total (+ delivery_charge in change_order)`.

### List / read

```
GET /order/:store_id?from=<ISO>&to=<ISO>&status=<exact>&query=<text>&label=<label>
→ { orders: [ {…projected fields…, cod_amount} ], labels: [...] }
```

`query` (full-text search) overrides the date range. Empty `status` excludes `Inactive`.

```
GET /order/:store_id/:order_id
→ full order + comments + stock_movements + can_edit_items + integration flags (hasAramex/…)
```

### Public storefront checkout — `POST /:store_id` (createOrder)

File: `task/create-order.ts`. Path: `POST /:store_id` (Mongo-id-shaped path). Public + `orderLimiter` (5/10min per `store_id_ip`). Body is merged with params + server-injected `ip`/`user_agent`; `customer_email` is pre-cleaned.

**Zod schema** (distinct from the admin/POS create bodies):

```
store_id: valid MongoId (from param)
products: array (min 1) of {
  product: string, default ''         // catalog product _id — REQUIRED for real lines
  variant: string, default ''         // variant _id
  quantity: number, min 1, default 1
  customization_charge: number, min 0, default 0
  custom_fields: any, optional
}
sender_full_name / sender_email / sender_phone_number / delivery_date / pan / company_name  (all optional or defaulted)
customer_full_name: string, min 2, max 120                (REQUIRED)
customer_email: optional email
customer_phone_number: string, length EXACTLY 10          (REQUIRED)
customer_address_city: string, min 2, max 320             (REQUIRED)
customer_address: string, min 2, max 320                  (REQUIRED)
customer_address_landmark: string, max 320, default ''
order_note: string, max 320, default ''
coupon: string, default ''         // treated as applied if length > 20
url: string, default ''
paymentMethod: string, default 'COD'   // free string, not enum — only 'COD' is special-cased
ip / user_agent: server-injected
```

**Key behavior:**

- **No custom line items** — every entry MUST reference a real catalog product. Empty `product` values are filtered out; if none remain → `"Product is required"`. Variant required if the product has variants. Out-of-stock rejected unless `continue_selling`.
- `paymentMethod` is a **free string**; only `'COD'` is special-cased. If `paymentMethod == 'COD'` and the delivery location has COD disabled → rejected.
- **Status set to `'Pending'`** if `paymentMethod == 'COD'`, else `'Inactive'`. COD orders immediately reduce inventory; non-COD wait for payment.
- **Silent no-op success for spam**: emails containing `mailinator.net` or phone `0000000000` return the shape below with `_id: ''` and no order created.

**Response:**

```json
{ "success": true, "_id", "order_number", "total_price", "total_quantity", "delivery_charge", "email", "slug": "" }
```

### Admin create lead — `POST /create-lead/:store_id`

File: `task/admin-create-lead.ts`. Roles: owner/manager/csr. Nearly identical to `adminCreateOrder` except:

- `payment_status` enum `['Paid','Unpaid','Partial']` defaults to `'Unpaid'`.
- `customer_address` defaults `''` (not min-2 required); name/email/phone come from `customer_id`.
- No `payment_method` field in schema.
- **⚠ Blocked entirely when the store has `use_advanced_inventory` on** — handler returns "in maintainance". Only works on non-advanced stores.
- Custom line items supported (same mechanism as `adminCreateOrder`).

### Bulk status update — `POST /:store_id/bulk_status`

File: `task/update-status-bulk.ts`. Roles: owner/manager/csr. Body:

```
{
  "order_ids": ["<id>", ...],
  "from_status": "",                 // empty = don't filter by current status
  "status": "",
  "payment_status": ""
}
```

**Only allows transitions WITHIN the same inventory group** (this avoids inventory adjustment side-effects that per-order `updateStatus` handles individually):

- **Group 1** (dormant): `Inactive`, `Cancelled`, `Returned`
- **Group 2** (active pipeline): `Pending`, `Processing`, `Waiting Pickup`, `Dispatched`, `Delivered`

Cross-group transitions are blocked. `updateMany` matched on `from_status`. Response: `{ success: true }`.

### Order delete guard

`DELETE /:store_id/:order_id` (roles owner/manager/csr): order is **only deletable when** `status ∈ {Inactive, Cancelled, Returned}` **AND** `payment_status != 'Paid'`. Archives to `DeletedItems` collection first, then removes. Response: `{ success: true }`.

Bulk delete: `POST /:store_id/delete_bulk` (roles owner/manager) — same guard applied per order.

### Additional enums (numeric — orders / channels / SMS / logistics)

**`channel` (order_channel)** — `src/core/constants/status.ts:8`. Stored on the order as numeric `channel` (default `WEB:2`):

| Value | Name | Meaning |
|---|---|---|
| 1 | MANNUAL | Admin create (`/create/:store_id`) |
| 2 | WEB | Public storefront (default) |
| 3 | POS | POS sale |
| 4 | SAMBAD | Sambad marketplace |
| 5 | MARKETPLACE | Generic marketplace |

**`logistics`** — `status.ts:21`:

`NONE:0, ARAMEX:1, PATHAO:2, NCM:3, DASH:4, UPAYA:5, FABBUD:6, PICK_AND_DROP:7, DARAZ:8`

**`sms_events`** — `status.ts:58`:

`ORDER_RECEIVED:1, ORDER_PROCESSING:2, ORDER_DISPATCHED:3, ORDER_DELIVERING_TODAY:4, ORDER_DELIVERED:5` — fired by `updateStatus` transitions.

**Legacy `order_status` numeric enum** (`generic.constant.ts`, mostly unused by the string-based Order model — kept for backwards-compat):
`PENDING:1, PROCESSING:2, DISPATCHED:3, DELIVERED:4, CANCELLED:5, RETURNED:6, DRAFT:7`. The Order model stores `status` as a **String**; only the transaction/gateway layer uses numeric enums.

**Numeric `payment_status`** (`generic.constant.ts`): `UNPAID:1, PAID:2, PROCESSING:3, FAILED:4, REFUNDED:5` — again, legacy; the Order model's `payment_status` is a String.

**`discount.d_type`** on the order: `FLAT:1, PERCENT:2, SHIPPING:3` (numeric, from `discount` enum in `generic.constant.ts`).

### Per-handler enum acceptance (subtle differences)

- `updateStatus` `status`: `Inactive`, `Pending`, `Processing`, `Dispatched`, `Delivered`, `Cancelled`, `Returned`. **Does NOT include** `Draft`, `Waiting Pickup`, or `Completed` — those are set only at creation time or via bulk status update.
- `updateStatus` `payment_status`: **only** `Paid`, `Unpaid`, `Refunded`. `Partial` is not accepted here — use `changeOrderItems` or admin/POS create for that.
- `updateStatus` `payment_method`: accepts all 12 order-level strings (`cash`, `qr`, `fonepay`, `esewa`, `khalti`, `connectips`, `bank_deposit`, `card`, `nps`, `nabil_card`, `COD`, `Manual`). Optional.
- `adminCreateOrder` `payment_method`: same 11 as `updateStatus` **minus `Manual`** (`Manual` is auto-assigned when `payment_status='Paid'` with no method given).
- `posCreateOrder` `payment_method`: adds `split` (POS-only).
- Public `createOrder` `paymentMethod`: **free string**, no enum validation. Default `'COD'`, only `'COD'` special-cased downstream.

### Non-storefront create surfaces

**Sambad marketplace create** — `POST /sambad/create` (auth via `authFromApiKey()`, not user JWT). Handler `sambadCreateOrder`. Sets `channel: 4` (SAMBAD).

**POS QR poll** — `POST /pos-check-qr-status/:store_id` (owner/manager/csr). Client-side poll after `posCreateOrder` returns a `qr_data` blob (`{prn, socket_url, qr_payload, amount, extras}`). Returns `{ success: bool, paid: bool, ... }` — poll until `paid: true` or user aborts.

### ordered_products subdoc — full field list (`order.ts:157`)

```
image_url: String
product_id: String              // absent/undefined for CUSTOM items
product_name: String
price: Number
compare_at_price: Number
cost_per_item: Number
customization_charge: Number    // default 0
variant_id: String
variant_name: String
quantity: Number
remained_quantity: Number       // stock snapshot at order time (for advanced inventory)
sku: String
vat_type: String
discount_amount: Number         // default 0 — per-line discount
custom_fields: [String]
categories: [String]
```

**Order-level `discount` object**: `{ discount_id, code, d_value, d_type }` where `d_type` is the numeric `discount` enum (`FLAT:1 | PERCENT:2 | SHIPPING:3`).

### partial_payment_amount handling (summary across handlers)

- **`adminCreateOrder`**: clamped to `min(amount, product_total)`. Only kept when `payment_status='Partial'` and must be `> 0`.
- **`posCreateOrder`**: for `split`, `partial_payment_amount = cash_amount`.
- **`changeOrderItems`**: `-1` = leave unchanged; `0` = clear (marks `Unpaid` if was `Partial`); `>0` = set + mark `Partial`.
- **Global integrity rule everywhere**: `discount.d_value + partial_payment_amount <= product_total` (`+ delivery_charge` in `changeOrderItems`).

## Transactions (mount `/payment`)

Transactions are **gateway payment records** (one per online payment attempt) — separate from the order's own `payment_method` string. Model: `Transaction` (collection `transactions`).

### Routes

| Method | Path | Roles | Purpose |
|---|---|---|---|
| GET | `/payment/transactions/:store_id?status=<n>&page=<n>` | owner/manager | List transactions |
| GET | `/payment/transactions/:store_id/settlement_history` | owner/manager | Settlement runs |
| GET | `/payment/transactions/:store_id/settlement/:settlement_id` | owner/manager | Settlement detail |
| GET | `/payment/dynamic_qr/check/:trans_id` | public | Boolean paid-yet check |
| GET | `/payment/subscription/:store_id` | owner/manager | Subscription plan + purchases |
| POST | `/payment/{fonepay,static_qr,dynamic_qr,card,esewa,khalti,npx,nabil_card}/init` | varies | Create a Transaction and start gateway flow |

### List transactions — `GET /payment/transactions/:store_id`

```
→ { total: { c: <count>, a: <sumAmount>, sc: <sumServiceCharge> },
    transactions: [
      { _id, order:{customer_full_name,customer_phone_number,order_number},
        payment_method, amount, service_charge, with, wallet_referance_code,
        status, created_at }
    ] }
```

**⚠ Filters are only `status` + `page`.** No date-range filter, no type filter, no order-side filter exist in code. `status` default is `2` (RECEIVED) if omitted or unparseable. Page size = 50. Sort `_id: -1`. **There is no "get one full transaction" endpoint** — the closest is the QR boolean check.

```
GET /payment/dynamic_qr/check/:trans_id       (public)
→ { "success": true }   // throws "Payment not received" unless status == RECEIVED
```

### Settlement history / detail

```
GET /payment/transactions/:store_id/settlement_history
→ { meta:{page,per_page,total},
    transactions:[ Settlement{ settlement_id, total_paid, total_service_charge, total_transactions, created_at } ] }

GET /payment/transactions/:store_id/settlement/:settlement_id
→ { settlement:{…}, transactions:[ {…full incl. dump, quick_receipt_id} ] }
```

Errors with `not_allowed` if the settlement doesn't belong to the store.

### Subscription

```
GET /payment/subscription/:store_id
→ { subscription:{plan, last_billing_amount, last_billed, next_billing, status},
    purchases:[…20 recent PurchaseHistory entries] }
```

Subscription/SMS purchases live in `PurchaseHistory` (collection `purchase_history`) — **separate model** from `Transaction`. Fields: `store, user, payment_method, amount, wallet_referance, status, txn_for (SUBSCRIPTION|SMS), txn_key (premium_quaterly|premium_yearly|platinum|premium|plus), source_verified, purchase_code, dump, timestamps`. Plan durations via `extractPlanDuration`: `premium_quaterly` = 3 months, `premium_yearly` = 12 months.

### How a Transaction gets created (`initForPayment`)

Every `POST /payment/*/init` endpoint routes into `initForPayment(payload, type)`:

- `amount = product_total_price + customization_total + delivery_charge - discount.d_value`
- **Service-charge rate by plan**: default `0.039`, `platinum: 0.0275`, `premium: 0.03`, `plus: 0.03`.
- `service_charge = 0 when with == STORE`, else `rate * amount`.
- Creates `Transaction` with `status = AWAITING_PAYMENT (1)`, `with = tsnWith || BLANXER`, `payment_method` mapped from the init type.
- Sets `order.transaction = trans._id`, `order.payment_status = "Processing"`.

On confirmation (`onPaymentSuccess`), a SYSTEM comment is logged and `onOrderPaid` fires.

### Transaction model fields

`store` (ref Store, required), `order` (ref Order, required), `payment_method` (Number, default `COD`=1), `amount` (Number), `service_charge` (Number), `settlement_session` (String), `settlement_id` (ref Settlement), `is_billed` (Bool), `wallet_referance_code` (String, gateway trace id), `return_url` (String), `status` (Number, default `AWAITING_PAYMENT`=1), `with` (Number, default `BLANXER`=1), `source_verified` (Bool), `purchase_code`, `purchase_code_active`, `quick_receipt_id`, `dump` (Mixed — raw gateway payload), `created_at`/`updated_at`.

Indexes: `{order}`, `{store}`, `{status,with,_id,created_at}`, `{status,store,_id}`.

### Transaction enums

**`transaction_status`**:

| Value | Name | Meaning |
|---|---|---|
| 1 | AWAITING_PAYMENT | Default on create |
| 2 | RECEIVED | Payment confirmed by gateway |
| 3 | FAILED | Payment failed |
| 4 | SETTLED | Funds settled to store |
| 5 | REFUNDED | Refunded |
| 6 | BILLED | Billed |
| 7 | AWAITING_SETTLEMENT | Received, pending settlement |

**`transaction_with`**: `1` BLANXER (Blanxer collects, service charge applies) · `2` STORE (own gateway, `service_charge = 0`).

**`transaction_for`** (on `PurchaseHistory`, not `Transaction`): `1` SUBSCRIPTION · `2` SMS.

**`payment_methods`** (numeric, gateway layer): `0` NONE · `1` COD · `2` FONE_PAY · `3` CONNECT_IPS · `4` CARD · `5` ESEWA · `6` BANK_DEPOSIT · `7` KHALTI · `8` QR · `9` CASH · `10` NPS · `11` NABIL_CARD · `20` OTHERS · `99` EARLY_ADOPTER_REWARD.

Reverse lookups (`invertBy` maps) exposed for `transaction_status`, `payment_methods`, `transaction_with`.

## Analytics / Reporting

Spread across 5 mounts. Date-range handling differs per feature — noted per endpoint.

### `/analytics` (storefront + dashboard)

```
GET /analytics/:store_id?from=&to=&mode=&outlet=       (auth; ⚠ NO Zod validation)
  mode: 1=ORDER, 2=PRODUCT, 3=STORE_VIEW
→ { data: [{ _id, ordered_products[], product_total_price, delivery_charge, net_profit, created_at }],
    visitors }   // visitors populated only when mode==ORDER

GET /analytics/dashboard/:store_id                     (auth; fixed today/7d/14d windows, no params)
→ { visitors, week_day, day,
    order: { today[], last_week[], two_week_timeseries[] } }

GET /analytics/dashboard/daily/:store_id?start_date=&end_date=   (any member; default last 7d)
→ { day, last_updated,
    basic_stats: { revenue, discount, delivery_charge, cod_amount, quantity },
    status_breakdown, payment_status_breakdown, payment_method_breakdown, payment_method_revenue,
    logistics_breakdown, most_ordered_products[top10], low_stocks[<5] }

GET /analytics/app/dashboard/:store_id                 (any member; current month + today)
→ { current_month:{name, total_order, revenue, delivery_charge},
    today:{total_order, average_order_value, revenue, delivery_charge},
    analytics:{pending, processing, delivered, dispatched},
    recent_orders[30 non-POS] }

POST /analytics/ping/:store_id                         (⚠ public; records STORE_VIEW)
→ { "s": 1 }
```

Excludes `Cancelled`/`Returned`/`Inactive` orders from all counts. Dates: `from → startOf day`, `to → endOf day`.

### `/sales_overview/:store_id?from=&to=&outlet=`

**⚠ Public — no auth middleware.** Returns a **raw unwrapped array** of order objects (not `{orders: [...]}`). Date filter applies only if both `from` and `to` parse as valid ISO strings. `outlet` applies only if a valid Mongo id. Excludes cancelled/returned/inactive.

Fields per order: `order_number, partial_payment_amount, logistics, customer, review, labels, payment_status, payment_method, discount.d_value, customer_phone_number, customer_full_name, customer_address_city, product_total_quantity, product_total_price, delivery_charge, status, slug, created_at, updated_at, ordered_products, customer_email, channel, referred (full_name, role)`.

### `/pos-reports` (owner/manager · default range epoch→now · timezone Asia/Kathmandu)

All match POS-channel orders with `status != 'Cancelled'`. Shared expressions in `task/utils/report-helpers.ts`:

```
NET_REVENUE_EXPR = max(0, product_total_price − Σ item.discount_amount − cart discount.d_value)
TAX_EXPR         = pos_tax_amount
AMOUNT_PAID_EXPR = Σ PAID pos_payments.amount
```

| Endpoint | Query | Returns |
|---|---|---|
| `GET /pos-reports/sales-summary/:store_id` | `from, to, groupBy(day\|week\|month), format(json\|csv)` | `{buckets[], totals}` — `total_sales, order_count, items_sold, taxAmount, itemDiscountTotal, cartDiscountAmount, amountPaid, total_refunded, returnsCount, netSales, balance, cogs, grossProfit`. Refunds merged from `PosReturn` by return date. |
| `GET /pos-reports/sales-by-product/:store_id` | `from, to, format` | `{products[]}` — `product_id, variant_id, product_name, variant_name, sku, quantity_sold, total_revenue, discount, tax, total_cost, gross_profit`. Tax apportioned per line by revenue share. |
| `GET /pos-reports/sales-by-location/:store_id` | `from, to` | `{locations[]}` per outlet — `outlet_id, outlet_name, total_sales, amountPaid, order_count, items_sold`. |
| `GET /pos-reports/sales-by-staff/:store_id` | `from, to` | `{staff[]}` — `user_id, name, email, total_sales, amountPaid, order_count, items_sold, avg_order_value, returns`. |
| `GET /pos-reports/sales-by-payment/:store_id` | `from, to` | `{methods[]}` — `method_type, method_name, total_amount, transaction_count, credit_count`. Normalizes CASH/COD→CASH, QR→QR. |
| `GET /pos-reports/inventory-value/:store_id` | `outlet?` (no dates) | `{outlets[], grand_total}` — `total_units, total_cost_value, sku_count` from active batches with quantity > 0. |
| `GET /pos-reports/expenses-by-category/:store_id` | `from, to` | `{categories[], grand_total}` — `category_id, category_name, total_amount, count`. |
| `GET /pos-reports/profit-loss/:store_id` | `from, to` | Flat P&L: `gross_revenue, total_discounts, taxCollected, total_refunds, return_count, net_revenue, total_cogs, gross_profit, total_expenses, net_profit, order_count, margin_percent`. Combines orders + PosReturn + Expense. |

### `/pos` shift reports (owner/manager/csr)

```
GET  /pos/shift/:store_id/open                    → currently-open shift for this cashier
GET  /pos/shift/:store_id/:id/preview             → { shift, defaultCashAccount, preview }
GET  /pos/shifts/:store_id                        → list shifts
POST /pos/shift/:store_id/:id/close               → same reconciliation object as preview
```

Uses `reconcileShift` — returns `IShiftReconciliation`:

```
{ sales, cash_sales, bank_sales, qr_sales, other_sales, items_sold,
  voids, cash_refunds, cash_expenses, paid_in, paid_out, returns,
  expected_cash (= opening_cash + cash_sales − cash_refunds − cash_expenses + paid_in − paid_out),
  order_count (non-cancelled) }
```

`GET /pos/activity/:store_id` (owner/manager) — audit log, not metrics.

### `/pos-finance` per-entity balances/ledgers (not dashboards)

All any-store-member reads:

- `GET /pos-finance/supplier-balance/:store_id/:id`
- `GET /pos-finance/supplier-ledger/:store_id/:id`
- `GET /pos-finance/customer-balance/:store_id/:id`
- `GET /pos-finance/customer-ledger/:store_id/:id`

Reporting-adjacent (financially aggregated) but per-entity, not store-wide dashboards.

## Cross-cutting caveats to code around

- **Transaction list has no date filter** — only `status` + `page`. For date-scoped payment analytics, use `/pos-reports/sales-by-payment` or `/analytics/dashboard/daily`.
- **`/sales_overview` is public and unwrapped** — don't rely on it for authed contexts; treat with care. No auth means no store-role validation.
- **`/analytics/:store_id` skips Zod** — send clean params. `mode` is numeric (`1`/`2`/`3`), not string.
- **Custom line items only work on admin/POS/lead/change endpoints** — never public checkout, which requires real catalog `product_id`s.
- **Order `payment_method` (string) ≠ `payment_methods` (numeric)**. The string lives on the order; the number lives on the transaction/gateway layer. Don't cross-reference them.
- **`payment_method` change is blocked** on `/status` once a gateway `Transaction` already exists — can't overwrite gateway records.
- **`/inventory/*` returns empty on non-advanced stores** — use `/product/pos/{store_id}` for stock reads instead (this is separate from the "no auth on `/sales_overview`" caveat).
- **Date-range semantics differ per feature**: `pos-reports` uses `new Date(from)` with defaults epoch→now; `sales_overview` requires both `from` and `to` as valid ISO or the filter is skipped; `store_analytics` applies `startOf`/`endOf` day.
- **`outlet` filter** only exists in `/analytics/:store_id`, `/sales_overview`, `/pos-reports/inventory-value`. Other `pos-reports` group by outlet but don't filter by it.
