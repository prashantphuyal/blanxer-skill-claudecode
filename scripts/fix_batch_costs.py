#!/usr/bin/env python3
"""
Find and fix stock batches saved with the wrong cost (Blanxer advanced inventory).

Profit in every report uses the cost of the BATCH each unit came from, not the
product's Cost Price. Until 20 Sep 2026 the dashboard's stock-in screen pre-filled
the SELLING price as the batch cost, and a product created without a cost was
stocked in at 0. Either one makes profit look like ~0% or 100%. This script finds those batches and,
with --apply, corrects them through Blanxer's own batch-cost correction, which
also restates the cost of every past sale from those batches on its own date.

Same rules as the backend's scripts/fix-prefilled-batch-costs.ts
(src/features/inventory/utils/prefilled-cost-fix.ts):
  - Candidates: a batch at cost 0 (any date), or one received before --before
    (default 2026-09-21) whose cost is within -3% / +5% of the selling price.
  - New cost, in order: (1) the product's / variant's Cost Price when above 0
    and below the selling price; (2) the newest correctly costed batch of the
    same item (above 0, below 97% of the price); (3) none, so the user must enter it.
  - A cost more than 5% above the selling price is a typo: listed, never
    fixed automatically.
  - Supplier balances are not changed (supplier_adjust false) unless
    --supplier-adjust is passed.

Usage (dry run first, always):
  BLANXER_API_KEY=sk_... python3 fix_batch_costs.py [--out batch-costs.csv] [--before 2026-09-21] [--preview]
  BLANXER_API_KEY=sk_... python3 fix_batch_costs.py --apply [--supplier-adjust]

  --out FILE         CSV of every flagged batch (default: batch-costs-<store>.csv)
  --before DAY       price-like costs only on batches received before this day
  --preview          dry run also asks Blanxer what each fix changes (sales, profit)
  --apply            correct the auto-fixable batches (owner / manager key only)
  --supplier-adjust  also post supplier debit/credit notes for each correction
  --product ID       only this product

Needs the Blanxer backend with /inventory/item-costs and
/inventory/batch-cost/preview-many|correct-many (Oct 2026). A re-run is safe:
corrected batches are no longer flagged, and every correct-many call carries a
deterministic client_request_id. Never print or log the key or the token.
"""
import argparse, csv, hashlib, json, os, sys, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BLANXER_BASE", "https://api.blanxer.com").rstrip("/")
API_KEY = os.environ.get("BLANXER_API_KEY") or sys.exit("BLANXER_API_KEY required")
if len(API_KEY) != 59 or not API_KEY.startswith("sk_"):
    sys.exit("API key must be 59 chars starting with sk_")

LOW_PCT, HIGH_PCT, GOOD_PCT = 97, 105, 97
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REASON = {
    "product_cost": "Stock-in pre-filled the selling price / 0 as cost; set to the product's cost price",
    "last_good_batch": "Stock-in pre-filled the selling price / 0 as cost; set to the last correct batch cost",
}

ap = argparse.ArgumentParser()
ap.add_argument("--out")
ap.add_argument("--before", default="2026-09-21")
ap.add_argument("--preview", action="store_true")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--supplier-adjust", action="store_true")
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


def msg(resp):
    return resp.get("message") or resp.get("error") or json.dumps(resp)[:200]


paisa = lambda v: round((float(v or 0)) * 100)
ms = lambda s: datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() if s else 0.0


def is_correct_cost(cost, price):
    c, p = paisa(cost), paisa(price)
    return c > 0 and p > 0 and c * 100 < p * GOOD_PCT


def prefill_reason(cost, price):
    c, p = paisa(cost), paisa(price)
    if c == 0:
        return "zero_cost"
    if p > 0 and p * LOW_PCT <= c * 100 <= p * HIGH_PCT:
        return "equals_price"
    return None


def plan_item(item, before_ts):
    """The flagged batches of one item (product / variant) from /inventory/item-costs."""
    price = float(item.get("price") or 0)
    batches = item.get("batches") or []
    good = [b for b in batches if is_correct_cost(b.get("cost_price"), price)]
    newest_good = max(good, key=lambda b: ms(b.get("received_at"))) if good else None
    pc = float(item.get("product_cost") or 0)
    out = []
    for b in batches:
        cost = float(b.get("cost_price") or 0)
        if price > 0 and paisa(cost) * 100 > paisa(price) * HIGH_PCT:
            why = "above_price"
        else:
            why = prefill_reason(cost, price)
            if why == "equals_price" and ms(b.get("received_at")) >= before_ts:
                why = None
        if not why:
            continue
        row = {"batch": b, "price": price, "old_cost": cost, "why": why, "new_cost": None, "source": None, "client": None}
        if why == "above_price":
            row["client"] = "above_price"
        elif pc > 0 and paisa(pc) < paisa(price):
            row.update(new_cost=pc, source="product_cost")
        elif newest_good:
            row.update(new_cost=float(newest_good["cost_price"]), source="last_good_batch",
                       good_batch=newest_good.get("batch_no"))
        else:
            row["client"] = "no_source"
        out.append(row)
    return out


# ── 1. every item that has a batch (sold-out batches included) ──
items, page = {}, 1
while True:
    q = f"/inventory/batch/{STORE_ID}?page={page}&per_page=500" + (f"&product={args.product}" if args.product else "")
    code, resp = call("GET", q)
    if code != 200:
        sys.exit(f"Could not list batches ({code}): {msg(resp)}")
    rows = resp.get("items") or []
    for b in rows:
        prod = b.get("product")
        if not isinstance(prod, dict) or not prod.get("_id"):
            continue  # product deleted
        key = (prod["_id"], b.get("variant_id") or None)
        names = items.setdefault(key, {"product_name": prod.get("name", ""), "variant_name": ""})
        if key[1]:
            for v in prod.get("variants") or []:
                if str(v.get("_id")) == str(key[1]):
                    names["variant_name"] = v.get("option_name") or v.get("name") or ""
    total = (resp.get("meta") or {}).get("total", 0)
    if page * 500 >= total or not rows:
        break
    page += 1
print(f"{len(items)} items with batches", flush=True)

# ── 2. price, product cost and every batch per item ──
def item_costs(keys):
    body = {"store_id": STORE_ID, "include_batches": True,
            "items": [{"product_id": p, **({"variant_id": v} if v else {})} for p, v in keys]}
    return call("POST", "/inventory/item-costs", body)


costs, skipped_items = [], []
keys = list(items)
for i in range(0, len(keys), 200):
    chunk = keys[i:i + 200]
    code, resp = item_costs(chunk)
    if code == 404:
        sys.exit("This Blanxer backend has no /inventory/item-costs yet (needs the Oct 2026 release).")
    if code == 200:
        costs.extend(resp.get("items") or [])
        continue
    for k in chunk:  # one unknown product / variant fails the whole call: retry one by one
        c1, r1 = item_costs([k])
        if c1 == 200:
            costs.extend(r1.get("items") or [])
        else:
            skipped_items.append((k, msg(r1)))

# ── 3. plan ──
before_ts = datetime.fromisoformat(args.before).replace(tzinfo=timezone(timedelta(hours=5, minutes=45))).timestamp()
plan = []
for it in costs:
    key = (it["product_id"], it.get("variant_id") or None)
    for row in plan_item(it, before_ts):
        row.update(key=key, **items.get(key, {"product_name": "", "variant_name": ""}))
        plan.append(row)
plan.sort(key=lambda r: (r["client"] is not None, r["product_name"].lower(), r["batch"].get("batch_no") or 0))

auto = [r for r in plan if r["new_cost"] is not None]
client = [r for r in plan if r["new_cost"] is None]

# group the auto fixes: one correct-many per item and new cost
groups = {}
for r in auto:
    groups.setdefault((r["key"], r["new_cost"], r["source"]), []).append(r)

# ── 4. optional preview (what Blanxer would restate) ──
if args.preview and groups:
    for (key, new_cost, _), rows in groups.items():
        code, resp = call("POST", "/inventory/batch-cost/preview-many",
                          {"store_id": STORE_ID, "batch_ids": [r["batch"]["_id"] for r in rows], "new_cost": new_cost})
        t = resp.get("totals") or {}
        for r in rows:
            r["preview"] = (f"{t.get('orders', 0)} sales, cost change Rs {t.get('cogs_change', 0)}"
                            if code == 200 else f"preview failed: {msg(resp)}")

# ── 5. CSV + summary ──
out = args.out or f"batch-costs-{STORE_ID}.csv"
with open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["product", "variant", "batch_no", "batch_id", "received", "selling_price", "cost_now", "problem",
                "new_cost", "source", "units_sold", "in_stock", "client_must_enter", "preview"])
    for r in plan:
        b = r["batch"]
        src = r["source"] or ""
        if src == "last_good_batch":
            src = f"last correct batch #{r.get('good_batch')}"
        w.writerow([r["product_name"], r["variant_name"], b.get("batch_no"), b.get("_id"), str(b.get("received_at", ""))[:10],
                    r["price"], r["old_cost"], r["why"], "" if r["new_cost"] is None else r["new_cost"], src,
                    b.get("sold", ""), b.get("quantity", ""), r["client"] or "", r.get("preview", "")])

count = lambda rows, k, v: sum(1 for r in rows if r[k] == v)
print(f"\nFlagged batches: {len(plan)}  (cost 0: {count(plan, 'why', 'zero_cost')}, "
      f"cost = selling price: {count(plan, 'why', 'equals_price')}, above price: {count(plan, 'why', 'above_price')})")
print(f"  auto-fix: {len(auto)}  (product cost: {count(auto, 'source', 'product_cost')}, "
      f"last correct batch: {count(auto, 'source', 'last_good_batch')})")
print(f"  user must enter: {len(client)}  (no source: {count(client, 'client', 'no_source')}, "
      f"above price: {count(client, 'client', 'above_price')})")
if skipped_items:
    print(f"  items not read ({len(skipped_items)}): " + "; ".join(f"{p}/{v or '-'}: {m}" for (p, v), m in skipped_items[:5]))
print(f"CSV: {out}", flush=True)

if not args.apply:
    print("\nDry run: nothing changed. Show the CSV to the user; re-run with --apply once they agree.")
    sys.exit(0)

# ── 6. apply ──
done = skipped = failed = 0
for (key, new_cost, source), rows in groups.items():
    ids = sorted(r["batch"]["_id"] for r in rows)
    rid = "skill-fixcost-" + hashlib.sha1(f"{STORE_ID}|{key}|{new_cost}|{','.join(ids)}".encode()).hexdigest()[:24]
    code, resp = call("POST", "/inventory/batch-cost/correct-many", {
        "store_id": STORE_ID, "batch_ids": ids, "new_cost": new_cost, "reason": REASON[source],
        "supplier_adjust": bool(args.supplier_adjust), "client_request_id": rid,
    })
    name = rows[0]["product_name"] + (f" · {rows[0]['variant_name']}" if rows[0]["variant_name"] else "")
    if code != 200:
        failed += len(ids)
        print(f"FAIL {name}: {msg(resp)}", flush=True)
        continue
    for res in resp.get("results") or []:
        if res.get("skipped"):
            skipped += 1
        elif res.get("success"):
            done += 1
        else:
            failed += 1
            print(f"FAIL {name} batch {res.get('batch_id')}: {res.get('error')}", flush=True)
    print(f"OK   {name}: {len(ids)} batch(es) -> Rs {new_cost}", flush=True)

print(f"\nCorrected {done}, already right {skipped}, failed {failed}. "
      f"Analytics catch up within minutes; download reports again to see the new profit.")
