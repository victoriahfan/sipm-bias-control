#!/usr/bin/env python3
"""
Extract Bill of Materials from KiCad PCB files (.kicad_pcb).
Outputs CSV with Board, Reference, Value, Footprint, Qty (per board), and cost columns.
Run from repo root: python3 scripts/extract_bom_from_pcb.py
"""

import re
import csv
import os
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Main (non-obsolete) PCB projects: (relative path to .kicad_pcb, display name)
BOARDS = [
    ("bias-control-lt8362/bias_generator_LT8362.kicad_pcb", "bias-control-lt8362"),
    ("power-supply/kicad/psu.kicad_pcb", "power-supply"),
    ("power-supply-alternate/kicad/psu.kicad_pcb", "power-supply-alternate"),
    ("tiav3_s14420/tiav3.kicad_pcb", "tiav3_s14420"),
    ("tiav3_s13360_30XXVE/tiav3_s13360_3030VE.kicad_pcb", "tiav3_s13360_3030VE"),
    ("tiav3_s14160/kicad/tiav3_s14160.kicad_pcb", "tiav3_s14160"),
]


def parse_pcb_bom(pcb_path: Path) -> List[Dict[str, Any]]:
    """Extract (Reference, Value, Footprint) from a .kicad_pcb file."""
    text = pcb_path.read_text(encoding="utf-8", errors="replace")
    entries = []
    # Split by "(footprint " so each part (after first) is one footprint block
    parts = text.split("(footprint ")
    for i, block in enumerate(parts):
        if i == 0:
            continue
        fp_m = re.match(r'"([^"]*)"', block)
        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', block)
        val_m = re.search(r'\(property\s+"Value"\s+"([^"]*)"', block)
        fp_prop_m = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
        if not ref_m or not val_m:
            continue
        ref = ref_m.group(1)
        value = val_m.group(1)
        if fp_prop_m:
            fp_full = fp_prop_m.group(1)
        elif fp_m:
            fp_full = fp_m.group(1)
        else:
            fp_full = ""
        footprint = fp_full.split(":")[-1] if fp_full and ":" in fp_full else (fp_full or "")
        entries.append({"Reference": ref, "Value": value, "Footprint": footprint})
    return entries


def aggregate_by_value_footprint(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate to unique Value+Footprint with refs list and qty."""
    by_key = defaultdict(list)
    for e in entries:
        key = (e["Value"], e["Footprint"])
        by_key[key].append(e["Reference"])
    out = []
    for (value, footprint), refs in sorted(by_key.items(), key=lambda x: (x[0][0], x[0][1])):
        out.append({
            "Value": value,
            "Footprint": footprint,
            "References": ",".join(sorted(refs)),
            "Quantity": len(refs),
        })
    return out


def main():
    all_rows = []
    board_boms = {}

    for rel_path, board_name in BOARDS:
        pcb_path = REPO_ROOT / rel_path
        if not pcb_path.is_file():
            print(f"Skip (not found): {rel_path}")
            continue
        entries = parse_pcb_bom(pcb_path)
        board_boms[board_name] = entries
        agg = aggregate_by_value_footprint(entries)
        for a in agg:
            all_rows.append({
                "Board": board_name,
                "References": a["References"],
                "Value": a["Value"],
                "Footprint": a["Footprint"],
                "Quantity": a["Quantity"],
                "Unit_Price_Est_USD": "",
                "Total_Est_USD": "",
                "Supplier_Part_Number": "",
                "Notes": "",
            })

    # Write per-board BOM CSVs
    bom_dir = REPO_ROOT / "manufacturing" / "bom"
    bom_dir.mkdir(parents=True, exist_ok=True)

    for board_name, entries in board_boms.items():
        agg = aggregate_by_value_footprint(entries)
        path = bom_dir / f"BOM_{board_name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "References", "Value", "Footprint", "Quantity",
                "Unit_Price_Est_USD", "Total_Est_USD", "Supplier_Part_Number", "Notes",
            ])
            w.writeheader()
            for a in agg:
                w.writerow({
                    "References": a["References"],
                    "Value": a["Value"],
                    "Footprint": a["Footprint"],
                    "Quantity": a["Quantity"],
                    "Unit_Price_Est_USD": "",
                    "Total_Est_USD": "",
                    "Supplier_Part_Number": "",
                    "Notes": "",
                })
        print(f"Wrote {path}")

    # Consolidated BOM (all boards)
    consolidated_path = REPO_ROOT / "BillOfMaterials_consolidated.csv"
    with open(consolidated_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "Board", "References", "Value", "Footprint", "Quantity",
            "Unit_Price_Est_USD", "Total_Est_USD", "Supplier_Part_Number", "Notes",
        ])
        w.writeheader()
        w.writerows(all_rows)
    print(f"Wrote {consolidated_path}")

    # Summary by board
    summary_path = REPO_ROOT / "BillOfMaterials_summary_by_board.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Board", "Total_Parts_Count", "Unique_Parts_Count"])
        for board_name, entries in board_boms.items():
            agg = aggregate_by_value_footprint(entries)
            w.writerow([board_name, len(entries), len(agg)])
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
