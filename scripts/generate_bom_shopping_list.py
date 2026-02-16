#!/usr/bin/env python3
"""
Generate an HTML shopping list from the BOM with clickable search links
to Digi-Key, Mouser, and LCSC so you can look up prices and know what to buy.
Run after extract_bom_from_pcb.py. Then open manufacturing/BOM_shopping_list.html.
"""

import csv
import urllib.parse
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLIDATED = REPO_ROOT / "BillOfMaterials_consolidated.csv"
OUT_HTML = REPO_ROOT / "manufacturing" / "BOM_shopping_list.html"


def search_urls(value: str, footprint: str) -> dict:
    """Build distributor search URLs. Prefer part number (value) for ICs."""
    # Use value as main search term; add footprint for passives if it helps
    term = value.strip()
    if not term:
        term = footprint
    encoded = urllib.parse.quote_plus(term)
    return {
        "digikey": f"https://www.digikey.com/en/products?keywords={encoded}",
        "mouser": f"https://www.mouser.com/c/?q={encoded}",
        "lcsc": f"https://www.lcsc.com/search?q={encoded}",
    }


def main():
    if not CONSOLIDATED.exists():
        print(f"Run extract_bom_from_pcb.py first. Missing: {CONSOLIDATED}")
        return

    rows = []
    with open(CONSOLIDATED, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Aggregate by (Value, Footprint) for "one full set" (one of each board)
    totals = defaultdict(lambda: {"qty": 0, "boards": [], "refs": set()})
    for r in rows:
        key = (r["Value"], r["Footprint"])
        totals[key]["qty"] += int(r.get("Quantity") or 0)
        totals[key]["boards"].append(r["Board"])
        refs = r.get("References", "")
        if refs:
            totals[key]["refs"].update(refs.replace(",", " ").split())

    # Build unique rows for shopping (one row per Value+Footprint)
    unique = []
    seen = set()
    for r in rows:
        key = (r["Value"], r["Footprint"])
        if key in seen:
            continue
        seen.add(key)
        urls = search_urls(r["Value"], r["Footprint"])
        total_qty = totals[key]["qty"]
        unique.append({
            "value": r["Value"],
            "footprint": r["Footprint"],
            "qty": total_qty,
            "boards": ", ".join(sorted(set(totals[key]["boards"]))),
            "refs": ", ".join(sorted(totals[key]["refs"]))[:60] + ("..." if len(totals[key]["refs"]) > 4 else ""),
            **urls,
        })

    # Sort by value then footprint
    unique.sort(key=lambda x: (x["value"].upper(), x["footprint"]))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SiPM Bias Control – BOM Shopping List</title>
  <style>
    body { font-family: sans-serif; max-width: 1200px; margin: 1rem auto; padding: 0 1rem; }
    h1 { font-size: 1.3rem; }
    p { color: #444; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }
    th { background: #eee; }
    tr:nth-child(even) { background: #f9f9f9; }
    .links a { margin-right: 0.5rem; }
    .qty { text-align: right; }
    .price { min-width: 4rem; }
    input.price { width: 4rem; }
  </style>
</head>
<body>
  <h1>BOM Shopping List – What to Buy &amp; Cost</h1>
  <p><strong>How to use:</strong> Click the Digi-Key / Mouser / LCSC links to search for each part and get the price. 
  Enter the unit price in the last column; total cost will update. 
  Then buy from your chosen distributor (or copy part numbers into JLCPCB/LCSC for assembly).</p>
  <p>Quantities below are for <strong>one full set</strong> (one of each board). Multiply by how many sets you want.</p>
  <table>
    <thead>
      <tr>
        <th>Value / Part number</th>
        <th>Footprint</th>
        <th>Qty (1 set)</th>
        <th>Used on boards</th>
        <th>Search for price</th>
        <th>Unit price (USD)</th>
        <th>Total (USD)</th>
      </tr>
    </thead>
    <tbody>
"""
    for u in unique:
        unit_id = f"unit-{urllib.parse.quote(u['value'] + u['footprint'], safe='')}"[:80]
        total_id = f"total-{urllib.parse.quote(u['value'] + u['footprint'], safe='')}"[:80]
        html += f"""
      <tr>
        <td>{html_esc(u['value'])}</td>
        <td>{html_esc(u['footprint'])}</td>
        <td class="qty">{u['qty']}</td>
        <td>{html_esc(u['boards'])}</td>
        <td class="links">
          <a href="{u['digikey']}" target="_blank" rel="noopener">Digi-Key</a>
          <a href="{u['mouser']}" target="_blank" rel="noopener">Mouser</a>
          <a href="{u['lcsc']}" target="_blank" rel="noopener">LCSC</a>
        </td>
        <td class="price"><input type="number" step="0.01" min="0" class="price" id="{unit_id}" placeholder="0.00" oninput="updateTotal('{unit_id}', '{total_id}', {u['qty']})"></td>
        <td class="price"><span id="{total_id}">—</span></td>
      </tr>
"""
    html += """
    </tbody>
  </table>
  <p style="margin-top: 1.5rem;"><strong>Grand total:</strong> <span id="grand-total">0.00</span> USD</p>
  <script>
    function updateTotal(unitId, totalId, qty) {
      var unit = document.getElementById(unitId);
      var totalEl = document.getElementById(totalId);
      var u = parseFloat(unit.value) || 0;
      totalEl.textContent = (u * qty).toFixed(2);
      updateGrandTotal();
    }
    function updateGrandTotal() {
      var sum = 0;
      document.querySelectorAll('tbody tr').forEach(function(tr) {
        var totalSpan = tr.querySelector('td:last-child span');
        if (totalSpan && totalSpan.textContent !== '—') sum += parseFloat(totalSpan.textContent) || 0;
      });
      document.getElementById('grand-total').textContent = sum.toFixed(2);
    }
  </script>
</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")
    print("Open that file in a browser. Use the links to look up prices, then type unit price to see totals.")


def html_esc(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    main()
