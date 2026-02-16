#!/usr/bin/env python3
"""
Fetch component prices and write them into the BOM CSVs.

Preferred: LCSC (JLCPCB's component distributor) — same place you order boards.
  Get API key at https://www.lcsc.com/agent (LCSC account → Agent/API).
  Set: LCSC_API_KEY, LCSC_API_SECRET

Alternative: Nexar (Octopart) — aggregates Digi-Key, Mouser, LCSC, etc.
  Get credentials at https://portal.nexar.com (free app).
  Set: NEXAR_CLIENT_ID, NEXAR_CLIENT_SECRET

Run: python3 scripts/fetch_bom_prices.py
Then open BillOfMaterials_consolidated.csv and manufacturing/bom/BOM_*.csv.
"""

import csv
import hashlib
import json
import os
import random
import re
import ssl
import string
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Use certifi's CA bundle if available (fixes SSL errors on macOS Python from python.org)
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLIDATED = REPO_ROOT / "BillOfMaterials_consolidated.csv"
BOM_DIR = REPO_ROOT / "manufacturing" / "bom"

LCSC_BASE = "https://wmsc.lcsc.com/rest/wmsc2agent"
NEXAR_TOKEN_URL = "https://identity.nexar.com/connect/token"
NEXAR_GRAPHQL_URL = "https://api.nexar.com/graphql"
SCOPE = "supply.domain"


def _save_debug_response(obj):
    """Write DEBUG response to manufacturing/nexar_debug_response.json."""
    try:
        dump_path = REPO_ROOT / "manufacturing" / "nexar_debug_response.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        print(f"  [Debug] Response saved to {dump_path}", file=sys.stderr)
    except Exception as e:
        print(f"  [Debug] Could not save response: {e}", file=sys.stderr)


# ---------- LCSC (JLCPCB ecosystem) ----------
def _lcsc_signature(key: str, secret: str, nonce: str, timestamp: str) -> str:
    s = f"key={key}&nonce={nonce}&secret={secret}&timestamp={timestamp}"
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def lcsc_search(key: str, secret: str, keyword: str) -> tuple:
    """Search LCSC by keyword. Return (unit_price_usd, lcsc_part_number) or (None, None)."""
    nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    timestamp = str(int(time.time()))
    sig = _lcsc_signature(key, secret, nonce, timestamp)
    params = {
        "key": key,
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": sig,
        "keyword": keyword[:200],
        "currency": "USD",
        "page_size": "10",
        "current_page": "1",
    }
    qs = urllib.parse.urlencode(params)
    url = f"{LCSC_BASE}/search/product?{qs}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None, None
    # Response shape varies; try common keys
    results = data.get("result") or data.get("productList") or data.get("data") or []
    if isinstance(results, dict):
        results = results.get("productList") or results.get("list") or []
    if not results:
        return None, None
    first = results[0] if isinstance(results, list) else results
    # Price can be in productPriceList, price, prices, or nested
    price_list = first.get("productPriceList") or first.get("prices") or first.get("priceList")
    if isinstance(price_list, list) and price_list:
        # Use first tier (often qty 1) or lowest unit price
        best_unit = None
        for p in price_list:
            qty = int(p.get("productNumber") or p.get("quantity") or 1)
            pr = p.get("productPrice") or p.get("price") or p.get("usdPrice")
            if pr is not None and qty > 0:
                try:
                    unit = float(pr) / qty
                    if best_unit is None or unit < best_unit:
                        best_unit = unit
                except (TypeError, ValueError):
                    pass
        if best_unit is not None:
            lcsc_pn = first.get("productCode") or first.get("lcscPartNumber") or first.get("partNumber") or ""
            return (round(best_unit, 4), lcsc_pn)
    # Single price field
    pr = first.get("productPrice") or first.get("usdPrice") or first.get("price")
    if pr is not None:
        try:
            unit = float(pr)
            lcsc_pn = first.get("productCode") or first.get("lcscPartNumber") or first.get("partNumber") or ""
            return (round(unit, 4), lcsc_pn)
        except (TypeError, ValueError):
            pass
    return None, None


# ---------- Nexar (Octopart) ----------
def get_nexar_token():
    client_id = os.environ.get("NEXAR_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NEXAR_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None, "Set NEXAR_CLIENT_ID and NEXAR_CLIENT_SECRET (from portal.nexar.com)."
    data = (
        f"grant_type=client_credentials"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&client_secret={urllib.parse.quote(client_secret)}"
        f"&scope={urllib.parse.quote(SCOPE)}"
    ).encode("utf-8")
    req = urllib.request.Request(
        NEXAR_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
            out = json.loads(resp.read().decode())
            return out.get("access_token"), None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return None, f"Nexar token error: {e.code} {body}"
    except Exception as e:
        err = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err or "SSL" in err:
            return None, (
                "SSL certificate error. Fix with one of:\n"
                "  1. pip install certifi   then run this script again\n"
                "  2. On macOS: run '/Applications/Python 3.x/Install Certificates.command'"
            )
        return None, err


def nexar_graphql(token: str, query: str, variables: dict = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        NEXAR_GRAPHQL_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode())


def _get_price_float(p: dict) -> tuple:
    """Get (price, quantity) from a price tier dict; handle camelCase or snake_case.
    If quantity is missing, treat price as unit price (quantity=1).
    """
    qty = p.get("quantity") or p.get("productNumber")
    try:
        qty = int(qty) if qty is not None else 1
    except (TypeError, ValueError):
        qty = 1
    if qty < 1:
        qty = 1
    raw = p.get("convertedPrice") or p.get("price") or p.get("productPrice")
    try:
        return float(raw), qty
    except (TypeError, ValueError):
        return None, 0


def nexar_search_part_price(token: str, search_term: str, debug: bool = False) -> tuple:
    q = search_term.replace("\\", "\\\\").replace('"', '\\"')[:200]
    query = '''
    query ($q: String!) {
      supSearchMpn(q: $q, limit: 1, currency: "USD") {
        results {
          part {
            mpn
            medianPrice1000 { quantity price currency convertedPrice convertedCurrency }
            sellers {
              company { name }
              offers {
                sku
                prices {
                  quantity
                  price
                  currency
                  convertedPrice
                  convertedCurrency
                }
              }
            }
          }
        }
      }
    }
    '''
    try:
        data = nexar_graphql(token, query, {"q": q})
    except urllib.error.HTTPError as e:
        if debug:
            body = e.read().decode() if e.fp else ""
            print(f"  [API error {e.code}] {body[:300]}", file=sys.stderr)
            _save_debug_response({"error": "HTTPError", "code": e.code, "body": body[:500]})
        return None, None
    except Exception as e:
        if debug:
            print(f"  [Error] {e}", file=sys.stderr)
            _save_debug_response({"error": str(e), "type": type(e).__name__})
        return None, None
    # Always save raw response when DEBUG=1 so we can see what Nexar returned
    if debug:
        _save_debug_response(data)
    errors = data.get("errors") or []
    if errors:
        if debug:
            print(f"  [GraphQL] {errors[0].get('message', errors[0])}", file=sys.stderr)
        return None, None
    results = (data.get("data") or {}).get("supSearchMpn", {}).get("results") or []
    if not results:
        return None, None
    part = results[0].get("part") or {}
    sellers = part.get("sellers") or []
    best_price = None
    best_sku = None
    for s in sellers:
        for offer in (s.get("offers") or []):
            for p in (offer.get("prices") or []):
                price, qty = _get_price_float(p)
                if price is None or price <= 0 or qty <= 0:
                    continue
                unit = price / qty
                if best_price is None or unit < best_price:
                    best_price = round(unit, 4)
                    best_sku = offer.get("sku") or (s.get("company") or {}).get("name") or ""
    # Fallback: median price at 1000 qty (use as rough unit price)
    if best_price is None:
        med = part.get("medianPrice1000") or {}
        if med:
            price, qty = _get_price_float(med)
            if price is not None and qty > 0:
                best_price = round(price / qty, 4)
                best_sku = "median est."
    return (best_price, best_sku) if best_price is not None else (None, None)


def looks_like_mpn(value: str) -> bool:
    if not value or len(value) > 120:
        return False
    if re.match(r"^[\d.]+[RkMpnNuFµ]?F?(\s*\(.*\))?$", value, re.IGNORECASE):
        return False
    if value.startswith("Conn_") or value in ("TestPoint", "ISP", "SIPM"):
        return False
    return True


def main():
    # Force unbuffered output so user sees progress
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None
    sys.stderr.reconfigure(line_buffering=True) if hasattr(sys.stderr, "reconfigure") else None
    print("fetch_bom_prices: starting...", flush=True)
    # Prefer LCSC (JLCPCB ecosystem), then Nexar
    lcsc_key = os.environ.get("LCSC_API_KEY", "").strip() or os.environ.get("LCSC_KEY", "").strip()
    lcsc_secret = os.environ.get("LCSC_API_SECRET", "").strip() or os.environ.get("LCSC_SECRET", "").strip()
    print("Checking Nexar credentials...", flush=True)
    nexar_token, nexar_err = get_nexar_token()
    print("Nexar token: " + ("ok" if nexar_token else str(nexar_err or "none")), flush=True)

    if lcsc_key and lcsc_secret:
        source = "LCSC (JLCPCB)"
        def fetch_price(search_term):
            return lcsc_search(lcsc_key, lcsc_secret, search_term)
    elif nexar_token:
        source = "Nexar (Octopart)"
        debug = os.environ.get("DEBUG", "").strip().lower() in ("1", "true", "yes")
        def fetch_price(search_term, do_debug=False):
            return nexar_search_part_price(nexar_token, search_term, do_debug)
    else:
        print("No pricing API configured.")
        print("\nLCSC (recommended if you use JLCPCB for boards):")
        print("  1. Get API key at https://www.lcsc.com/agent")
        print("  2. export LCSC_API_KEY=... LCSC_API_SECRET=...")
        print("\nNexar (Digi-Key, Mouser, LCSC, etc.):")
        print("  1. Sign up at https://portal.nexar.com and create an app")
        print("  2. export NEXAR_CLIENT_ID=... NEXAR_CLIENT_SECRET=...")
        print("\nThen run this script again.")
        return

    if not CONSOLIDATED.exists():
        print("Run extract_bom_from_pcb.py first to create the BOM CSVs.")
        return

    print(f"Using {source} for prices.\n")
    if source == "Nexar (Octopart)":
        print("If no prices appear, run with DEBUG=1 to save the first API response to manufacturing/nexar_debug_response.json\n")
    price_cache = {}
    rows = []
    with open(CONSOLIDATED, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    seen = set()
    first_nexar = True
    for r in rows:
        key = (r["Value"], r["Footprint"])
        if key in seen:
            continue
        seen.add(key)
        value, footprint = key
        search_term = value if looks_like_mpn(value) else f"{value} {footprint}"
        do_debug = debug and first_nexar and source == "Nexar (Octopart)"
        if do_debug:
            first_nexar = False
        if source == "Nexar (Octopart)":
            unit, sku = fetch_price(search_term, do_debug)
        else:
            unit, sku = fetch_price(search_term)
        price_cache[key] = (unit, sku)
        label = value[:50] + ("..." if len(value) > 50 else "")
        if unit is not None:
            print(f"  {label} -> ${unit:.4f}  ({sku or '—'})")
        else:
            print(f"  {label} -> (no price)")
        time.sleep(0.35)

    fieldnames = [
        "Board", "References", "Value", "Footprint", "Quantity",
        "Unit_Price_Est_USD", "Total_Est_USD", "Supplier_Part_Number", "Notes",
    ]
    out_rows = []
    for r in rows:
        key = (r["Value"], r["Footprint"])
        unit, sku = price_cache.get(key, (None, None))
        qty = int(r.get("Quantity") or 0)
        total = (round(unit * qty, 2) if unit is not None and qty else "")
        unit_str = f"{unit:.4f}" if unit is not None else ""
        out_rows.append({
            **r,
            "Unit_Price_Est_USD": unit_str,
            "Total_Est_USD": total if total != "" else "",
            "Supplier_Part_Number": sku or r.get("Supplier_Part_Number", ""),
        })
    with open(CONSOLIDATED, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    num_filled = sum(1 for r in out_rows if (r.get("Unit_Price_Est_USD") or "").strip())
    print(f"\nUpdated {CONSOLIDATED}  ({num_filled} parts with prices)")
    if num_filled == 0:
        print("  No prices were returned by the API. Check NEXAR_* credentials and network.")
    print("  Open the CSV file (not BillOfMaterials.xlsx) to see costs.")

    for path in sorted(BOM_DIR.glob("BOM_*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            board_rows = list(csv.DictReader(f))
        b_fieldnames = [
            "References", "Value", "Footprint", "Quantity",
            "Unit_Price_Est_USD", "Total_Est_USD", "Supplier_Part_Number", "Notes",
        ]
        out = []
        for r in board_rows:
            key = (r["Value"], r["Footprint"])
            unit, sku = price_cache.get(key, (None, None))
            qty = int(r.get("Quantity") or 0)
            total = (round(unit * qty, 2) if unit is not None and qty else "")
            unit_str = f"{unit:.4f}" if unit is not None else ""
            out.append({
                **r,
                "Unit_Price_Est_USD": unit_str,
                "Total_Est_USD": total if total != "" else "",
                "Supplier_Part_Number": sku or r.get("Supplier_Part_Number", ""),
            })
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=b_fieldnames)
            w.writeheader()
            w.writerows(out)
        print(f"Updated {path}")

    total_sum = 0.0
    for r in out_rows:
        try:
            total_sum += float(r.get("Total_Est_USD") or 0)
        except (TypeError, ValueError):
            pass
    print(f"\nEstimated total (1 of each board): ${total_sum:.2f} USD")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr, flush=True)
        raise
