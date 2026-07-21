#!/usr/bin/env python3
"""
Reprint Blanxer barcode labels for existing products (no upload needed).

Use this when the user wants labels for products that already exist in the
store — e.g. "reprint labels for last week's batch", "give me 3 spare tags
for row 22", or "print labels for everything matching '12/7'". Fully
independent of any upload session.

Two modes (auto-picked based on whether BLANXER_QUANTITIES is set):
  - Simple mode (default): one label per current stock unit. Uses
    GET /product/generate_barcode/{store_id}/{print_id}. No bookkeeping.
  - By-quantity mode: caller specifies exact copies per product/variant.
    Uses GET /product/generate_barcode_quantity/...

Environment variables:
  BLANXER_API_KEY      sk_… key. Required.
  BLANXER_PRODUCT_IDS  Comma-separated product IDs to print. Mutually exclusive with BLANXER_PRODUCT_QUERY.
  BLANXER_PRODUCT_QUERY Substring to match against product.name (case-insensitive). Uses GET /product/pos/{store_id}.
  BLANXER_QUANTITIES   Optional JSON: {"<product_id_or_variant_id>": <count>, ...}. Triggers by-quantity mode.
  BLANXER_BARCODE_PDF  Output path. Default: ./barcodes.pdf
  BLANXER_LABEL_FLAGS  Optional JSON: {"show_name": "true", ...}. Defaults: show_name=true, show_store=false (the user's sticky preference — product name on top, no store name), show_price=true, show_barcode=true.
"""
import json, os, sys, urllib.request, urllib.error, urllib.parse

BASE = "https://api.blanxer.com"
API_KEY = os.environ.get("BLANXER_API_KEY") or sys.exit("BLANXER_API_KEY required")
if len(API_KEY) != 59 or not API_KEY.startswith("sk_"):
    sys.exit("API key must be 59 chars starting with sk_")

PID_LIST = [p.strip() for p in os.environ.get("BLANXER_PRODUCT_IDS", "").split(",") if p.strip()]
QUERY = os.environ.get("BLANXER_PRODUCT_QUERY", "").strip().lower()
QMAP_RAW = os.environ.get("BLANXER_QUANTITIES", "").strip()
OUT_PATH = os.environ.get("BLANXER_BARCODE_PDF", "barcodes.pdf")
DEFAULT_FLAGS = {"show_name": "true", "show_store": "false", "show_price": "true", "show_barcode": "true"}
FLAGS = {**DEFAULT_FLAGS, **json.loads(os.environ.get("BLANXER_LABEL_FLAGS", "{}"))}

if not PID_LIST and not QUERY:
    sys.exit("Set BLANXER_PRODUCT_IDS (comma list) OR BLANXER_PRODUCT_QUERY (name substring)")
if PID_LIST and QUERY:
    sys.exit("Set only one of BLANXER_PRODUCT_IDS or BLANXER_PRODUCT_QUERY")

# Exchange sk_ key. Cloudflare gates this route too — send browser headers.
exchange = json.loads(urllib.request.urlopen(urllib.request.Request(
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
), timeout=30).read())
if not exchange.get("success"):
    sys.exit(f"api-key/check failed: {exchange}")
TOKEN = exchange["token"]
STORE_ID = exchange["store"]["_id"]
STORE_NAME = exchange["store"]["name"]
print(f"Store: {STORE_NAME} ({STORE_ID})")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://app.blanxer.com",
    "Referer": "https://app.blanxer.com/",
    "Accept": "application/json, text/plain, */*",
}


def get(url, extra=None):
    req = urllib.request.Request(url, headers={**HEADERS, **(extra or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read())


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:500]}


# Resolve product IDs from name query if needed.
if QUERY:
    code, listing = get(f"{BASE}/product/pos/{STORE_ID}")
    if code != 200:
        sys.exit(f"Product listing failed: {code} {listing}")
    items = listing.get("products") or listing.get("items") or listing.get("data") or []
    matches = [p for p in items if QUERY in str(p.get("name", "")).lower()]
    if not matches:
        sys.exit(f"No products match '{QUERY}'")
    PID_LIST = [p["_id"] for p in matches]
    print(f"Query '{QUERY}' matched {len(PID_LIST)} products:")
    for p in matches:
        print(f"  {p['_id']}  {p.get('name')}")

# Create print request.
pr_code, pr_resp = post(f"{BASE}/order/print_request/{STORE_ID}",
                        {"orders": PID_LIST, "print_for": 2})
if pr_code != 200 or not (pr_resp.get("success") or pr_resp.get("id")):
    sys.exit(f"Print request failed: {pr_code} {pr_resp}")
print_id = pr_resp.get("id") or pr_resp.get("_id")
print(f"print_id: {print_id}")

# Pick mode.
if QMAP_RAW:
    endpoint = "generate_barcode_quantity"
    qs_extra = {"quantities": QMAP_RAW}
    print(f"Mode: by-quantity  ({len(json.loads(QMAP_RAW))} explicit counts)")
else:
    endpoint = "generate_barcode"
    qs_extra = {}
    print("Mode: simple (one label per current stock unit)")

qs = urllib.parse.urlencode({"token": TOKEN, **qs_extra, **FLAGS})
pdf_url = f"{BASE}/product/{endpoint}/{STORE_ID}/{print_id}?{qs}"
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
    sys.exit(f"PDF download failed: HTTP {e.code}  {e.read()[:200]}")

os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
open(OUT_PATH, "wb").write(pdf)
print(f"Saved {len(pdf):,} bytes to {OUT_PATH}")
