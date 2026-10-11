#!/usr/bin/env bash
# Download the Lichess chess-openings dataset (CC0) into the package.
set -euo pipefail
DEST="$(dirname "$0")/../src/chess_mcp/data/openings"
mkdir -p "$DEST"
for f in a b c d e; do
  curl -fsSL "https://raw.githubusercontent.com/lichess-org/chess-openings/master/$f.tsv" -o "$DEST/$f.tsv"
done
curl -fsSL "https://raw.githubusercontent.com/lichess-org/chess-openings/master/COPYING.md" -o "$DEST/LICENSE" \
  || echo "CC0 1.0 - https://github.com/lichess-org/chess-openings" > "$DEST/LICENSE"
wc -l "$DEST"/*.tsv | tail -1
