#!/usr/bin/env bash
# Export Gerber files for each SiPM bias control PCB:
#   - gerber-with-silkscreen/  (components on - for assembly)
#   - gerber-bare/             (components off - bare board fabrication)
# Requires KiCad 7+ (or KiCad 9). On macOS, kicad-cli is inside the app bundle if not in PATH.

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Find kicad-cli: PATH first, then macOS app bundle (KiCad 7/8/9)
KICAD_CLI=""
if command -v kicad-cli &>/dev/null; then
  KICAD_CLI="kicad-cli"
elif [[ -x "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli" ]]; then
  KICAD_CLI="/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
fi

if [[ -z "$KICAD_CLI" ]]; then
  echo "kicad-cli not found. Install KiCad 7, 8, or 9."
  echo "On macOS, KiCad installs kicad-cli inside the app; this script checks /Applications/KiCad/."
  KICAD_AVAILABLE=0
else
  KICAD_AVAILABLE=1
  echo "Using: $($KICAD_CLI version 2>/dev/null || echo "$KICAD_CLI")"
fi

# Layer sets (KiCad 7/8/9 use F.SilkS, B.SilkS)
LAYERS_BARE="F.Cu,B.Cu,F.Mask,B.Mask,Edge.Cuts"
LAYERS_WITH_SILK="F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts"

# PCB projects: path_to_pcb_file:output_name
declare -a BOARDS=(
  "bias-control-lt8362/bias_generator_LT8362.kicad_pcb:bias-control-lt8362"
  "power-supply/kicad/psu.kicad_pcb:power-supply"
  "power-supply-alternate/kicad/psu.kicad_pcb:power-supply-alternate"
  "tiav3_s14420/tiav3.kicad_pcb:tiav3_s14420"
  "tiav3_s13360_30XXVE/tiav3_s13360_3030VE.kicad_pcb:tiav3_s13360_3030VE"
  "tiav3_s14160/kicad/tiav3_s14160.kicad_pcb:tiav3_s14160"
)

for entry in "${BOARDS[@]}"; do
  PCB_PATH="${entry%%:*}"
  NAME="${entry##*:}"
  PCB_DIR="$(dirname "$PCB_PATH")"
  PCB_FILE="$(basename "$PCB_PATH")"

  if [[ ! -f "$REPO_ROOT/$PCB_PATH" ]]; then
    echo "Skip (not found): $PCB_PATH"
    continue
  fi

  echo "--- $NAME ---"

  if [[ $KICAD_AVAILABLE -eq 1 ]]; then
    OUT_WITH="$PCB_DIR/manufacturing/gerber-with-silkscreen"
    OUT_BARE="$PCB_DIR/manufacturing/gerber-bare"
    mkdir -p "$OUT_WITH" "$OUT_BARE"

    "$KICAD_CLI" pcb export gerbers \
      -l "$LAYERS_WITH_SILK" \
      -o "$OUT_WITH" \
      "$REPO_ROOT/$PCB_PATH" || true

    "$KICAD_CLI" pcb export gerbers \
      -l "$LAYERS_BARE" \
      -o "$OUT_BARE" \
      "$REPO_ROOT/$PCB_PATH" || true

    # Export drill file (same for both)
    "$KICAD_CLI" pcb export drill -o "$OUT_WITH" "$REPO_ROOT/$PCB_PATH" 2>/dev/null || true
    for f in "$OUT_WITH"/*.drl "$OUT_WITH"/*.xln; do
      [[ -f "$f" ]] && cp -a "$f" "$OUT_BARE/" 2>/dev/null || true
    done
  fi
done

echo "Done. Upload gerber-with-silkscreen for assembly, gerber-bare for bare PCB only."
