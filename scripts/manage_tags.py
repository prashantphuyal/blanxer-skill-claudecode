#!/usr/bin/env python3
"""
Blanxer product-tag manager — add / remove / replace tags across a catalogue.

Tags are the only place Blanxer stores per-product feature flags (coming_soon,
no_price, main, team_order, show_color_chips, mirrago_tryon, rd_/ard_ redirect
buttons) and filter facets (key:value, seller:<name>). They can be set in the
create-product body; afterwards there are two write paths:

    POST /product/{store_id}/bulk_update              <- what this script uses
    POST /product/custom_fields/{store_id}/{product_id}

bulk_update patches up to 500 products per call and writes ONLY the fields
named in `set`, so it cannot wipe custom_fields or similar_products. The
single-product custom_fields route is a FULL REPLACE whose `tags`,
`custom_fields` and `similar_products` all default to [] — posting just
{"tags": [...]} there destroys the other two. Pass --legacy-writes to use it
anyway (one product per call, with the three arrays echoed back).

Reading is still per product: the admin list `GET /product/{store_id}` projects
a fixed field set that excludes `tags`, so the current tag set of each product
has to come from `GET /product/{store_id}/{product_id}`. So: N reads, then
ceil(N/500) writes.

Bulk routes share one budget of 30 requests per minute per store across every
bulk endpoint, so the writes are paced (--delay, default 2s between chunks).

Usage:
  manage_tags.py list                          [selector]
  manage_tags.py add    "tag1,tag2"            [selector] [--apply]
  manage_tags.py remove "tag1,tag2"            [selector] [--apply]
  manage_tags.py set    "tag1,tag2"            selector   --apply

Selectors (combine freely; they AND together). With none, only `list` runs —
add/remove/set refuse to touch the whole catalogue unless you pass --all.
  --all                       every product in the store
  --ids a,b,c                 explicit product _ids
  --name-contains <substr>    case-insensitive product-name match
  --has-tag <tag>             products that already carry this exact tag
  --channel <1|2|3>           1=All, 2=Website, 3=POS

Flags:
  --apply          actually write. Without it the script dry-runs and prints
                   the before -> after diff for every product it would touch.
  --delay <s>      seconds between write calls (default 2.0; bulk routes allow
                   30/min per store, shared with every other bulk caller)
  --chunk <n>      products per bulk_update call (default 500, the server cap)
  --legacy-writes  write one product at a time via the custom_fields route
                   instead of bulk_update (older backends)

Environment:
  BLANXER_API_KEY   sk_… key (59 chars). Required.

Examples:
  BLANXER_API_KEY=sk_… python3 manage_tags.py list
  BLANXER_API_KEY=sk_… python3 manage_tags.py add "seller:acme" --all --apply
  BLANXER_API_KEY=sk_… python3 manage_tags.py add "coming_soon" --name-contains diwali
  BLANXER_API_KEY=sk_… python3 manage_tags.py remove "coming_soon" --has-tag coming_soon --apply

Never prints the API key or the exchanged JWT.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

BASE = "https://api.blanxer.com"

# Tags Blanxer gives special meaning to. Anything else is free-form and merely
# joins the product's text search key.
KNOWN_TAGS = {
    "coming_soon": 'Shows "Coming Soon", disables Add to Cart',
    "no_price": "Hides price, compare price and discount badges",
    "show_color_chips": "Colour chip dots on cards (needs hex colour variants)",
    "team_order": "Team/group ordering mode on the detail page",
    "main": "Sorts first under auto-sort",
    "mirrago_tryon": "Virtual Try-On button (needs the Mirrago plugin)",
}
KNOWN_PREFIXES = {
    "rd_": "Redirect button — rd_<Label>_<Link>, + stands for a space",
    "ard_": "Alternate-style redirect button",
    "seller:": "Seller/vendor facet on the admin Products page",
}

# Cloudflare blocks plain HTTP clients with `403 error code: 1010` unless the
# request looks like a browser. Sent on every call, GET included.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://app.blanxer.com",
    "Referer": "https://app.blanxer.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def split_tags(raw):
    """Accept comma- or semicolon-separated tags, de-duplicated, order kept."""
    out = []
    for t in (raw or "").replace(";", ",").split(","):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


def describe_tag(tag):
    if tag in KNOWN_TAGS:
        return KNOWN_TAGS[tag]
    for prefix, desc in KNOWN_PREFIXES.items():
        if tag.startswith(prefix):
            return desc
    if ":" in tag:
        return f"Faceted filter on key '{tag.split(':', 1)[0]}' (excluded from text search)"
    return "free-form tag (joins the text search key)"


def request(method, url, token, body=None):
    headers = dict(BROWSER_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:300]}
    except Exception as e:  # noqa: BLE001 — surface transport errors as data
        return 0, {"error": f"{type(e).__name__}: {e}"}


def exchange_key(api_key):
    req = urllib.request.Request(
        f"{BASE}/api-key/check",
        data=json.dumps({"api_key": api_key}).encode(),
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read())
    if not payload.get("success"):
        sys.exit(f"api-key/check failed: {payload}")
    return payload["token"], payload["store"]["_id"], payload["store"]["name"]


def select_products(token, store_id, args):
    """Admin list -> candidate products. This projection has no `tags`, so the
    --has-tag filter is applied later, after the per-product detail read."""
    code, listing = request("GET", f"{BASE}/product/{store_id}", token)
    if code != 200 or not isinstance(listing, list):
        sys.exit(f"Could not list products: {code} {listing}")

    wanted_ids = set(i.strip() for i in (args.ids or "").split(",") if i.strip())
    picked = []
    for p in listing:
        if wanted_ids and p.get("_id") not in wanted_ids:
            continue
        if args.name_contains and args.name_contains.lower() not in (p.get("name") or "").lower():
            continue
        if args.channel is not None and p.get("channel") != args.channel:
            continue
        picked.append(p)

    if wanted_ids:
        missing = wanted_ids - {p["_id"] for p in picked}
        if missing:
            print(f"WARNING: {len(missing)} id(s) not found in this store: {', '.join(sorted(missing))}")
    return picked


def read_product(token, store_id, product_id):
    code, doc = request("GET", f"{BASE}/product/{store_id}/{product_id}", token)
    if code != 200 or not isinstance(doc, dict) or "_id" not in doc:
        return None, f"read failed: {code} {doc}"
    return doc, None


def new_tag_set(mode, current, subject):
    if mode == "add":
        out = list(current)
        for t in subject:
            if t not in out:
                out.append(t)
        return out
    if mode == "remove":
        return [t for t in current if t not in subject]
    return list(subject)  # set


def write_tags_legacy(token, store_id, doc, tags):
    """One product via the full-replace route — custom_fields and
    similar_products MUST be echoed back or the handler's `.default([])`
    wipes them."""
    body = {
        "tags": tags,
        "custom_fields": doc.get("custom_fields") or [],
        "similar_products": doc.get("similar_products") or [],
    }
    if doc.get("release_date"):
        body["release_date"] = doc["release_date"]
    return request("POST", f"{BASE}/product/custom_fields/{store_id}/{doc['_id']}", token, body)


def write_tags_bulk(token, store_id, chunk):
    """One bulk_update call for up to 500 products. `set` carries tags only,
    so nothing else on the product is touched — no echo-back needed.

    chunk: [(doc, target_tags), ...]
    Returns (status, response).
    """
    body = {
        "updates": [
            {"product_id": doc["_id"], "set": {"tags": tags}} for doc, tags in chunk
        ]
    }
    return request("POST", f"{BASE}/product/{store_id}/bulk_update", token, body)


def main():
    ap = argparse.ArgumentParser(add_help=True, description="Manage Blanxer product tags")
    ap.add_argument("mode", choices=["list", "add", "remove", "set"])
    ap.add_argument("tags", nargs="?", default="", help="comma-separated tags (not used by `list`)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--name-contains", default="")
    ap.add_argument("--has-tag", default="")
    ap.add_argument("--channel", type=int, choices=[1, 2, 3])
    ap.add_argument("--apply", action="store_true")
    # Bulk routes share 30 req/min per store across every bulk endpoint.
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--legacy-writes", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("BLANXER_API_KEY") or sys.exit("BLANXER_API_KEY required")
    if len(api_key) != 59 or not api_key.startswith("sk_"):
        sys.exit("API key must be 59 chars starting with sk_")

    subject = split_tags(args.tags)
    has_selector = bool(args.all or args.ids or args.name_contains or args.has_tag or args.channel)

    if args.mode != "list":
        if not subject:
            sys.exit(f"`{args.mode}` needs a tag list, e.g. manage_tags.py {args.mode} \"seller:acme\"")
        if not has_selector:
            sys.exit("Refusing to run without a selector. Pass --all to mean the whole catalogue.")
        if args.mode == "set" and args.all and not args.apply:
            print("NOTE: `set --all` replaces every product's tag array wholesale.")

    token, store_id, store_name = exchange_key(api_key)
    print(f"Store: {store_name} ({store_id})")
    if args.mode != "list":
        print("Tags: " + "; ".join(f"{t} — {describe_tag(t)}" for t in subject))

    candidates = select_products(token, store_id, args)
    print(f"Reading {len(candidates)} product(s)…", flush=True)

    changed, unchanged, failed = [], 0, []
    inventory = {}

    for p in candidates:
        doc, err = read_product(token, store_id, p["_id"])
        if err:
            failed.append((p.get("name"), err))
            continue
        current = list(doc.get("tags") or [])
        if args.has_tag and args.has_tag not in current:
            continue
        inventory[doc["_id"]] = (doc.get("name"), current)
        if args.mode == "list":
            continue
        target = new_tag_set(args.mode, current, subject)
        if target == current:
            unchanged += 1
            continue
        changed.append((doc, current, target))

    if args.mode == "list":
        for pid, (name, tags) in inventory.items():
            print(f"  {pid}  {name}\n      tags: {tags if tags else '(none)'}")
        print(f"\n{len(inventory)} product(s); {sum(1 for _, t in inventory.values() if t)} carry at least one tag.")
        return 0

    print(f"\n{len(changed)} to change, {unchanged} already correct, {len(failed)} unreadable.")
    for doc, current, target in changed:
        print(f"  {doc['_id']}  {doc.get('name')}\n      {current}  ->  {target}")
    for name, err in failed:
        print(f"  SKIP {name}: {err}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return 0
    if not changed:
        print("\nNothing to write.")
        return 0

    ok = 0
    write_failed: list = []  # read failures already printed above
    if args.legacy_writes:
        print(f"\nWriting {len(changed)} product(s), one call each (legacy route)…", flush=True)
        for i, (doc, _current, target) in enumerate(changed, 1):
            code, resp = write_tags_legacy(token, store_id, doc, target)
            if code == 200 and resp.get("success"):
                ok += 1
                print(f"[{i:3d}/{len(changed)}] OK   {doc.get('name')}", flush=True)
            else:
                write_failed.append((doc.get("name"), f"write failed: {code} {resp}"))
                print(f"[{i:3d}/{len(changed)}] FAIL {doc.get('name')}  {code} {resp}", flush=True)
            if i < len(changed):
                time.sleep(args.delay)
    else:
        size = max(1, min(args.chunk, 500))
        chunks = [
            [(doc, target) for doc, _current, target in changed[i : i + size]]
            for i in range(0, len(changed), size)
        ]
        print(
            f"\nWriting {len(changed)} product(s) in {len(chunks)} bulk_update call(s)…",
            flush=True,
        )
        for n, chunk in enumerate(chunks, 1):
            code, resp = write_tags_bulk(token, store_id, chunk)
            if code == 429:
                # Shared 30/min bulk budget for the whole store. Wait it out once.
                print(f"[{n}/{len(chunks)}] rate-limited; waiting 60s", flush=True)
                time.sleep(60)
                code, resp = write_tags_bulk(token, store_id, chunk)
            if code != 200 or not resp.get("success"):
                for doc, _t in chunk:
                    write_failed.append((doc.get("name"), f"write failed: {code} {resp}"))
                print(f"[{n}/{len(chunks)}] FAIL {len(chunk)} product(s)  {code} {resp}", flush=True)
            else:
                # Per-item results: an item can fail while the call succeeds.
                by_id = {doc["_id"]: doc for doc, _t in chunk}
                for r in resp.get("results") or []:
                    doc = by_id.get(r.get("product_id"), {})
                    if r.get("ok"):
                        ok += 1
                    else:
                        write_failed.append((doc.get("name"), r.get("error") or "rejected"))
                print(
                    f"[{n}/{len(chunks)}] {len(chunk)} sent, "
                    f"{resp.get('updated')} modified"
                    + (f", {len([r for r in resp.get('results') or [] if not r.get('ok')])} rejected" if any(not r.get("ok") for r in resp.get("results") or []) else ""),
                    flush=True,
                )
            if n < len(chunks):
                time.sleep(args.delay)

    for name, err in write_failed:
        print(f"  FAILED {name}: {err}")
    print(f"\n=== TAGS DONE: {ok} written, {len(changed) - ok} not written, {unchanged} already correct, {len(failed)} unreadable ===")
    return 0 if ok == len(changed) and not failed and not write_failed else 1


if __name__ == "__main__":
    sys.exit(main())
