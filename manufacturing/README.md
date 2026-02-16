# SiPM Bias Control – Manufacturing

This folder contains **Bill of Materials (BOM)** and, for the power-supply board, **Gerber** outputs for fabrication and assembly.

## Bill of Materials (what to buy and costs)

The CSVs list every part but don’t include prices. To **see what to buy and estimate cost**:

1. **Open the shopping list (easiest):**  
   Open **`manufacturing/BOM_shopping_list.html`** in a browser. It has:
   - Every part needed for **one full set** of boards (one of each PCB), with quantity.
   - **Digi-Key**, **Mouser**, and **LCSC** search links for each part — click to look up the price.
   - A **Unit price** box: type the price you find, and it shows the line total and **grand total** at the bottom.

2. **Optional – keep a record in CSV:**  
   After you look up prices, you can fill **Unit_Price_Est_USD** and **Total_Est_USD** (and **Supplier_Part_Number**) in:
   - **`../BillOfMaterials_consolidated.csv`** (all boards), or  
   - **`bom/BOM_<board>.csv`** (per board).

3. **Auto-fill prices in the CSV (optional):**  
   Prefer **LCSC** (same ecosystem as JLCPCB) so prices match where you can order parts:
   ```bash
   export LCSC_API_KEY="your_key"
   export LCSC_API_SECRET="your_secret"
   python3 scripts/fetch_bom_prices.py
   ```
   Get API key at [LCSC Agent](https://www.lcsc.com/agent). Alternatively, use **Nexar** (Digi-Key, Mouser, LCSC, etc.): sign up at [portal.nexar.com](https://portal.nexar.com), create an app, then `export NEXAR_CLIENT_ID=... NEXAR_CLIENT_SECRET=...` and run the same script. After running, the BOM CSVs will have **Unit_Price_Est_USD**, **Total_Est_USD**, and **Supplier_Part_Number** filled where the API returned a price.

4. **Regenerate lists after design changes:**  
   ```bash
   python3 scripts/extract_bom_from_pcb.py
   python3 scripts/generate_bom_shopping_list.py
   ```

## Gerber files (with components on / off)

For each PCB you can provide two Gerber sets:

| Set | Use | Contents |
|-----|-----|----------|
| **gerber-with-silkscreen** (components on) | Assembly / placement | Copper, mask, **silkscreen** (refs and outlines), drill, edge. Use for assembly or when the fab needs component positions. |
| **gerber-bare** (components off) | Bare-board fabrication | Copper, mask, drill, edge. **No silkscreen.** Use when ordering bare PCBs only. |

### Power-supply board

Pre-generated Gerbers are under:

- `power-supply/manufacturing/gerber/gerber-with-silkscreen/` – with silkscreen  
- `power-supply/manufacturing/gerber/gerber-bare/` – without silkscreen  

Upload the appropriate folder to your PCB vendor (e.g. JLCPCB, PCBWay, Seeed Fusion).

### Other boards (bias-control-lt8362, tiav3_*, power-supply-alternate)

1. Install **KiCad 7 or 8** (with `kicad-cli` in your PATH).
2. From the repo root, run:

   ```bash
   bash scripts/export_gerbers.sh
   ```

   This creates for each board:

   - `manufacturing/gerber-with-silkscreen/` – full set including silkscreen  
   - `manufacturing/gerber-bare/` – set without silkscreen  

3. Zip the folder you need and upload to your fab.

If `kicad-cli` is not installed, open each project in KiCad and use **File → Plot** (or the equivalent Gerber export), then copy the generated files into `gerber-with-silkscreen` (all layers) or `gerber-bare` (omit F.Silkscreen and B.Silkscreen).

## Ordering

- **Boards:** Use the Gerber (and drill) files as above. For bare boards only, use the **gerber-bare** set.
- **Parts:** Use the BOM CSVs; fill **Unit_Price_Est_USD** and **Supplier_Part_Number** from your distributor to track cost and ordering.
