#!/usr/bin/env python3
"""
Find and fix variant names the website cannot match (Blanxer products with colours / sizes).

The storefront builds a shopper's pick as the EXACT string "<colour>/<size>" from
the product's `colors` / `sizes` lists (just the value when one list is empty) and
finds the variant's price, photo, stock and id by `option_name ==` that string.
A variant named "Pink / 4 yrs" (spaces) is stored as sent, so the colours show,
the Size row is EMPTY and add-to-cart carries no variant (Rimjhim, 2026-10-28).

For every product with variants this script:
  - rewrites names that differ only in spacing / capitals to the lists' own
    spelling ("Pink / 4 yrs" -> "Pink/4 yrs");
  - adds a colour / size a variant uses that its list lacks;
  - empties a second list no variant uses (colour-only variants "Black" with a
    stray sizes ["Black"] -> the storefront looked for "Black/Black");
  - stores a swatch colour "Name|#hex" as the storefront's "Name:#hex";
  - lists, never touches, a product whose names it cannot place.

Each fix resends the product through POST /product/variant_inventory with every
variant's _id (keeps its stock, batches and barcode) and expected_quantity equal
to the stock read, so no stock moves.

Usage (dry run first, always):
  BLANXER_API_KEY=sk_... python3 fix_variant_names.py [--product ID]
  BLANXER_API_KEY=sk_... python3 fix_variant_names.py --apply [--product ID]

Owner / manager key for --apply. A re-run is safe: fixed products are no longer
flagged. Never print or log the key or the token.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request

BASE = os.environ.get("BLANXER_BASE", "https://api.blanxer.com").rstrip("/")
API_KEY = os.environ.get("BLANXER_API_KEY") or sys.exit("BLANXER_API_KEY required")
if len(API_KEY) != 59 or not API_KEY.startswith("sk_"):
    sys.exit("API key must be 59 chars starting with sk_")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--product")
args = ap.parse_args()

# ── auth (Cloudflare needs browser headers on every request, the exchange too) ──
browser = {"User-Agent": UA, "Origin": "https://app.blanxer.com", "Referer": "https://app.blanxer.com/",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}
req = urllib.request.Request(f"{BASE}/api-key/check", data=json.dumps({"api_key": API_KEY}).encode(),
                             headers={**browser, "Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=30) as r:
    exchange = json.loads(r.read())
if not exchange.get("success"):
    sys.exit(f"api-key/check failed: {exchange.get('message') or 'unknown error'}")
STORE_ID, STORE_NAME = exchange["store"]["_id"], exchange["store"]["name"]
HEADERS = {**browser, "Authorization": f"Bearer {exchange['token']}", "Content-Type": "application/json"}
print(f"Store: {STORE_NAME} ({STORE_ID})", flush=True)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(f"{BASE}{path}", data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")[:500]
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"message": text}
    except Exception as e:  # network
        return 0, {"message": f"{type(e).__name__}: {e}"}


# ── names: same rules as BlanxerMCP src/variant-names.ts ──
def key(s):
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    return re.sub(r"\s*/\s*", "/", s)


def colour_entry(raw):
    s = str(raw or "").strip()
    m = re.match(r"^([^|:]+)\|\s*(#.*)$", s)
    return f"{m.group(1).strip()}:{m.group(2).strip()}" if m else s


def colour_name(entry):
    return entry.split(":", 1)[0].strip()


def unique(items, k):
    seen, out = set(), []
    for x in items:
        kk = k(x)
        if kk and kk not in seen:
            seen.add(kk)
            out.append(x)
    return out


def align(raw_names, raw_colors, raw_sizes):
    """-> (names, colors, sizes, notes, problem)"""
    colors = unique([colour_entry(c) for c in raw_colors], lambda c: key(colour_name(c)))
    sizes = unique([str(s or "").strip() for s in raw_sizes], key)
    names = [re.sub(r"\s+", " ", str(n or "").strip()) for n in raw_names]
    notes = []
    cnames = lambda: [colour_name(c) for c in colors]
    segs = lambda s: [p.strip() for p in s.split("/")]

    if not colors and not sizes:
        parts = [segs(n) for n in names]
        if all(len(p) == 2 and p[0] and p[1] for p in parts):
            colors = unique([p[0] for p in parts], key)
            sizes = unique([p[1] for p in parts], key)
            notes.append("built the colour and size lists from the names")
        elif all(len(p) == 1 and p[0] for p in parts):
            sizes = unique(names, key)
            notes.append("built the option list from the names")
        else:
            return names, colors, sizes, notes, "names do not follow one shape"

    if colors and sizes and all("/" not in n for n in names):
        if all(key(n) in {key(c) for c in cnames()} for n in names):
            notes.append(f"cleared the stray size list {sizes}")
            sizes = []
        elif all(key(n) in {key(s) for s in sizes} for n in names):
            notes.append(f"cleared the stray colour list {cnames()}")
            colors = []

    def place(name):
        parts = segs(name)
        both = bool(colors) and bool(sizes)
        if not both:
            for c in cnames():
                if key(c) == key(name):
                    return (c, None)
            for s in sizes:
                if key(s) == key(name):
                    return (None, s)
        if len(parts) == 1:
            return None if both else ((name, None) if colors else (None, name))
        for c in sorted(cnames(), key=len, reverse=True):
            n = len(segs(c))
            if n < len(parts) and key("/".join(parts[:n])) == key(c):
                return (c, "/".join(parts[n:]))
        for s in sorted(sizes, key=len, reverse=True):
            n = len(segs(s))
            if n < len(parts) and key("/".join(parts[-n:])) == key(s):
                return ("/".join(parts[:-n]), s)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])
        return None

    placed = [place(n) for n in names]
    if any(p is None for p in placed):
        bad = [n for n, p in zip(names, placed) if p is None]
        return names, colors, sizes, notes, f"cannot place {bad[:5]} in colours {cnames()} / sizes {sizes}"
    for c, s in placed:
        if c is not None and key(c) not in {key(x) for x in cnames()}:
            colors.append(c)
            notes.append(f"added colour {c!r}")
        if s is not None and key(s) not in {key(x) for x in sizes}:
            sizes.append(s)
            notes.append(f"added size {s!r}")
    if colors and sizes and any(c is None or s is None for c, s in placed):
        return names, colors, sizes, notes, "some names have a colour and a size, others one value"

    canon_c = lambda c: next(x for x in cnames() if key(x) == key(c))
    canon_s = lambda s: next(x for x in sizes if key(x) == key(s))
    out = []
    for c, s in placed:
        c2 = canon_c(c) if c is not None else None
        s2 = canon_s(s) if s is not None else None
        out.append(f"{c2}/{s2}" if c2 is not None and s2 is not None else (c2 if c2 is not None else s2))
    if len(set(out)) != len(out):
        return names, colors, sizes, notes, "two variants would get the same name"
    return out, colors, sizes, notes, None


def payload(doc, names, colors, sizes):
    """The full variant_inventory body (safe on every backend): every field, every
    variant by _id, expected_quantity = the stock read so nothing moves."""
    num = lambda v: float(v or 0)
    qty = num(doc.get("quantity"))
    return {
        "continue_selling": doc.get("continue_selling") is not False,
        "price": num(doc.get("price")), "compare_at_price": num(doc.get("compare_at_price")),
        "cost_per_item": num(doc.get("cost_per_item")), "weight": num(doc.get("weight")),
        "quantity": qty, "expected_quantity": qty,
        "sku": doc.get("sku") or "", "exim_code": doc.get("exim_code") or "", "alt_barcode": doc.get("alt_barcode") or "",
        "color_name": doc.get("color_name") or ("Colour" if colors else ""),
        "size_name": doc.get("size_name") or ("Size" if sizes else ""),
        "colors": colors, "sizes": sizes,
        "image_urls": doc.get("image_urls") or [],
        "variants": [{
            "_id": v["_id"], "option_name": n,
            "price": num(v.get("price")), "compare_at_price": num(v.get("compare_at_price")),
            "cost_per_item": num(v.get("cost_per_item")),
            "quantity": num(v.get("quantity")), "expected_quantity": num(v.get("quantity")),
            "weight": num(v.get("weight")), "sku": v.get("sku") or "", "exim_code": v.get("exim_code") or "",
            "alt_barcode": v.get("alt_barcode") or "", "image_url": v.get("image_url") or "",
        } for v, n in zip(doc["variants"], names)],
    }


code, listing = call("GET", f"/product/{STORE_ID}")
if code != 200 or not isinstance(listing, list):
    sys.exit(f"Could not list products: {code} {listing}")
# The admin list may not project variants/options; then read every product rather
# than report a store with broken names as clean.
projects_options = any(k in p for p in listing for k in ("variants", "colors", "sizes"))
ids = [args.product] if args.product else [
    p["_id"] for p in listing if not projects_options or p.get("variants") or p.get("colors") or p.get("sizes")]
print(f"Checking {len(ids)} product(s) with options…", flush=True)

fixes, stuck = [], []
for pid in ids:
    code, doc = call("GET", f"/product/{STORE_ID}/{pid}")
    if code != 200 or not isinstance(doc, dict) or not doc.get("variants"):
        continue
    raw = [v.get("option_name") or "" for v in doc["variants"]]
    names, colors, sizes, notes, problem = align(raw, doc.get("colors") or [], doc.get("sizes") or [])
    if problem:
        stuck.append((doc, problem))
        continue
    if names == raw and colors == (doc.get("colors") or []) and sizes == (doc.get("sizes") or []):
        continue
    fixes.append((doc, names, colors, sizes, notes))

for doc, names, colors, sizes, notes in fixes:
    renamed = [(a, b) for a, b in zip([v.get("option_name") for v in doc["variants"]], names) if a != b]
    print(f"\n{doc['name']} ({doc['_id']})")
    for a, b in renamed:
        print(f"   {a!r} -> {b!r}")
    for n in notes:
        print(f"   {n}")
for doc, problem in stuck:
    print(f"\nNEEDS A PERSON: {doc['name']} ({doc['_id']}): {problem}")

print(f"\n{len(fixes)} product(s) to fix, {len(stuck)} need a person.")
if not args.apply:
    if fixes:
        print("Dry run. Re-run with --apply to save these.")
    sys.exit(0)

failed = 0
for doc, names, colors, sizes, _ in fixes:
    code, resp = call("POST", f"/product/variant_inventory/{STORE_ID}/{doc['_id']}", payload(doc, names, colors, sizes))
    if code != 200:
        failed += 1
        print(f"FAILED {doc['name']}: {code} {resp.get('message') or resp}")
        continue
    _, after = call("GET", f"/product/{STORE_ID}/{doc['_id']}")
    got = [v.get("option_name") for v in (after or {}).get("variants") or []]
    ok = got == names and [v.get("_id") for v in after["variants"]] == [v["_id"] for v in doc["variants"]]
    print(f"{'saved' if ok else 'SAVED BUT CHECK'} {doc['name']}: {got if not ok else 'names, ids and stock kept'}")
    failed += 0 if ok else 1
    time.sleep(0.5)
sys.exit(1 if failed else 0)
