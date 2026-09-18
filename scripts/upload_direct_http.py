#!/usr/bin/env python3
"""
Direct-HTTP Blanxer bulk product uploader.

Companion to upload_loop.js. Use this when you have an sk_ API key rather than
a live Chrome tab. Reads a CSV with columns product_name, qty, cost_rate,
selling_rate (plus an optional tags column) and does create-product +
stock-in for each row.

Environment variables:
  BLANXER_API_KEY   sk_… key (59 chars, starts with sk_). Required.
  BLANXER_OUTLET_ID Mongo _id of the target outlet. Required.
  BLANXER_CSV       Path to CSV. Default: ./products.csv
  BLANXER_CHANNEL   1=All, 2=Website, 3=POS. Default: 3 (POS).
  BLANXER_DELAY_S   Seconds between products. Default: 3.
  BLANXER_TAGS      Comma-separated tags applied to EVERY product in the run,
                    e.g. "seller:acme,brand:nike". Optional.
  BLANXER_BARCODE_PDF  Output path for the barcode PDF. Default: <BLANXER_CSV
                       directory>/barcodes.pdf. Set to "" to skip generation.

After create + stock-in, this also generates a barcode PDF (one page per unit
of current on-hand stock) so the user can print labels immediately. The PDF is
written next to the source CSV.

Tags: the optional per-row `tags` CSV column is semicolon- or pipe-separated
(NOT comma — that would break plain CSV), e.g. "coming_soon;color:red". Row
tags are merged onto BLANXER_TAGS, global first, duplicates dropped, order
preserved. Tags are sent in the create body, which is the only place they can
be set without a second round-trip. To change tags on products that already
exist, use manage_tags.py instead.

The store_id is derived from the API key (chars 3..27) and confirmed via
/api-key/check. Never print or log the key or the exchanged token.
"""
import csv, json, os, sys, time, urllib.request, urllib.error, urllib.parse

BASE = "https://api.blanxer.com"
API_KEY = os.environ.get("BLANXER_API_KEY") or sys.exit("BLANXER_API_KEY required")
OUTLET_ID = os.environ.get("BLANXER_OUTLET_ID") or sys.exit("BLANXER_OUTLET_ID required")
CSV_PATH = os.environ.get("BLANXER_CSV", "products.csv")
CHANNEL = int(os.environ.get("BLANXER_CHANNEL", "3"))
DELAY_S = float(os.environ.get("BLANXER_DELAY_S", "3"))
GLOBAL_TAGS = [t.strip() for t in os.environ.get("BLANXER_TAGS", "").split(",") if t.strip()]


def merge_tags(row_value):
    """Global tags + this row's tags, de-duplicated, order preserved."""
    row_tags = [t.strip() for t in (row_value or "").replace("|", ";").split(";") if t.strip()]
    out = []
    for t in GLOBAL_TAGS + row_tags:
        if t not in out:
            out.append(t)
    return out


if len(API_KEY) != 59 or not API_KEY.startswith("sk_"):
    sys.exit("API key must be 59 chars starting with sk_")

# 1. Exchange the sk_ key for a Bearer JWT.
#    Cloudflare gates this route too — must send browser headers on the exchange.
exchange_req = urllib.request.Request(
    f"{BASE}/api-key/check",
    data=json.dumps({"api_key": API_KEY}).encode(),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Origin": "https://app.blanxer.com",
        "Referer": "https://app.blanxer.com/",
    },
    method="POST",
)
with urllib.request.urlopen(exchange_req, timeout=30) as r:
    exchange = json.loads(r.read())
if not exchange.get("success"):
    sys.exit(f"api-key/check failed: {exchange}")
TOKEN = exchange["token"]
STORE_ID = exchange["store"]["_id"]
STORE_NAME = exchange["store"]["name"]
print(f"Store: {STORE_NAME} ({STORE_ID})", flush=True)

# 2. Browser-like headers — Cloudflare blocks plain HTTP clients with error 1010.
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://app.blanxer.com",
    "Referer": "https://app.blanxer.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:500]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def create_product(name, selling, tags=None):
    return post(f"{BASE}/product/{STORE_ID}", {
        "name": name, "description": "", "long_description": "",
        "continue_selling": True, "channel": CHANNEL,
        "price": selling, "compare_at_price": 0, "cost_per_item": 0,
        "weight": 0, "quantity": 0,
        "showVariant": False, "showColorPreview": False,
        "slug": "", "brand": "", "categories": [],
        "images": [], "image_urls": [],
        "sku": "", "color_name": "", "size_name": "",
        "color_codes": [], "colors": [], "sizes": [],
        "variants": [], "custom_fields": [], "tags": tags or [],
        "releaseDate": None, "similar_products": [],
    })


def stock_in(product_id, qty, cost):
    return post(f"{BASE}/inventory/stock-in", {
        "store_id": STORE_ID, "outlet_id": OUTLET_ID, "reference_number": "",
        "items": [{"product_id": product_id, "variant_id": "", "quantity": qty,
                   "cost_price": cost, "bin_location": ""}]
    })


rows = list(csv.DictReader(open(CSV_PATH)))
print(f"Uploading {len(rows)} products with {DELAY_S}s delay (~{len(rows) * DELAY_S / 60:.1f} min)", flush=True)
if GLOBAL_TAGS:
    print(f"Global tags on every product: {GLOBAL_TAGS}", flush=True)
ok, fail = 0, 0
uploaded_pids = []  # for the barcode step
for i, r in enumerate(rows, 1):
    name = r["product_name"]
    qty, cost, sell = int(r["qty"]), int(r["cost_rate"]), int(r["selling_rate"])
    tags = merge_tags(r.get("tags"))
    t0 = time.time()
    code, resp = create_product(name, sell, tags)
    if code == 200 and resp.get("success"):
        pid = resp["product"]["_id"]
        scode, sresp = stock_in(pid, qty, cost)
        if scode == 200:
            ok += 1
            uploaded_pids.append(pid)
            tagnote = f", tags={'+'.join(tags)}" if tags else ""
            print(f"[{i:3d}/{len(rows)}] OK  {name}  (id={pid}, qty={qty}, cost={cost}, sell={sell}{tagnote})", flush=True)
        else:
            fail += 1
            print(f"[{i:3d}/{len(rows)}] STOCK-IN FAIL {name}  code={scode}  {sresp}", flush=True)
    else:
        fail += 1
        print(f"[{i:3d}/{len(rows)}] CREATE FAIL   {name}  code={code}  {resp}", flush=True)
    if i < len(rows):
        time.sleep(max(0, DELAY_S - (time.time() - t0)))

print(f"\n=== UPLOAD DONE: {ok} ok, {fail} fail ===")

# --- Barcode PDF generation (auto) ---
default_pdf = os.path.join(os.path.dirname(os.path.abspath(CSV_PATH)) or ".", "barcodes.pdf")
pdf_path = os.environ.get("BLANXER_BARCODE_PDF", default_pdf)
if not uploaded_pids or pdf_path == "":
    print("Skipping barcode PDF (nothing uploaded or output path empty).")
    sys.exit(0 if fail == 0 else 1)

print(f"\nGenerating barcode PDF for {len(uploaded_pids)} products...", flush=True)

# 1. Fetch authoritative current_stock per product (post-adjustment source of truth).
qmap = {}
page = 1
while True:
    inv_url = f"{BASE}/inventory/list/{STORE_ID}?outlet={OUTLET_ID}&page={page}&per_page=100"
    inv_req = urllib.request.Request(inv_url, headers=HEADERS)
    inv = json.loads(urllib.request.urlopen(inv_req, timeout=30).read())
    for it in inv.get("items", []):
        pid = it["_id"]["product"]
        if pid in uploaded_pids:
            qmap[pid] = it["current_stock"]
    m = inv.get("meta", {})
    if not m or page * m.get("per_page", 100) >= m.get("total", 0):
        break
    page += 1
total_labels = sum(qmap.values())
print(f"Label counts fetched: {len(qmap)}/{len(uploaded_pids)} products, {total_labels} labels total")

# 2. Create print request (POST — needs CF headers).
pr_code, pr_resp = post(f"{BASE}/order/print_request/{STORE_ID}",
                        {"orders": uploaded_pids, "print_for": 2})
if pr_code != 200 or not (pr_resp.get("success") or pr_resp.get("id")):
    print(f"Print request failed: {pr_code}  {pr_resp}")
    sys.exit(1)
print_id = pr_resp.get("id") or pr_resp.get("_id")
print(f"print_id: {print_id}")

# 3. Download the PDF (GET with token in query — also needs CF headers).
#    show_name=true + show_store=false → product name (not store name) on top.
qs = urllib.parse.urlencode({
    "token": TOKEN,
    "quantities": json.dumps(qmap),
    "show_name": "true",
    "show_store": "false",
    "show_price": "true",
    "show_barcode": "true",
})
pdf_url = f"{BASE}/product/generate_barcode_quantity/{STORE_ID}/{print_id}?{qs}"
pdf_req = urllib.request.Request(pdf_url, headers={
    "User-Agent": HEADERS["User-Agent"],
    "Origin": HEADERS["Origin"],
    "Referer": HEADERS["Referer"],
    "Accept": "application/pdf,*/*",
})
try:
    with urllib.request.urlopen(pdf_req, timeout=60) as r:
        pdf = r.read()
except urllib.error.HTTPError as e:
    print(f"PDF download failed: HTTP {e.code}  {e.read()[:200]}")
    sys.exit(1)

os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
with open(pdf_path, "wb") as f:
    f.write(pdf)
print(f"Saved {len(pdf):,} bytes to {pdf_path}")

sys.exit(0 if fail == 0 else 1)
