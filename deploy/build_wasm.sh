#!/usr/bin/env bash
# Build the static WASM bundle for the FFM citation-network notebook.
#
# Output:  dist/                (gitignored — regenerable from source)
# Run from the repo root:      bash deploy/build_wasm.sh
#
# Flags:
#   --skip-extract    skip the DuckDB refresh step; build from committed
#                     public/data/{nodes,edges}.csv. Required for CI on a
#                     fresh checkout (no private DB available).
#
# Without --skip-extract, set CN_SEEDS_CSV and CN_DB_PATH (see extract.py).

set -euo pipefail

SKIP_EXTRACT=0
for arg in "$@"; do
    case "$arg" in
        --skip-extract) SKIP_EXTRACT=1 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

THIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$THIS_DIR"

if [[ "$SKIP_EXTRACT" -eq 1 ]]; then
    echo "→ Skipping subgraph extraction (--skip-extract); using committed CSVs."
else
    echo "→ (Re-)extracting subgraph from portfolio.duckdb ..."
    python extract.py --top-k 150
fi

if [[ ! -s public/vendor/vis-network-9.1.9.min.js ]]; then
    echo "→ Fetching vendored vis-network 9.1.9 (one-time) ..."
    mkdir -p public/vendor
    curl -sSL -o public/vendor/vis-network-9.1.9.min.js \
        https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js
fi

echo "→ Exporting WASM bundle to dist/ ..."
python -m marimo export html-wasm notebook.py \
    -o dist \
    --mode run \
    --no-show-code
# marimo ships a generic AI-assistant CLAUDE.md with every WASM export; it is
# not part of this notebook, so keep it off the public site.
rm -f dist/CLAUDE.md

echo "→ Building standalone HTML to dist/standalone.html ..."
python build_html.py --out dist/standalone.html

echo
echo "→ Bundle ready at:  $THIS_DIR/dist/"
echo "→ Smoke-test locally:"
echo "    python -m http.server --directory dist 8000"
echo "    then open http://localhost:8000/  (WASM)  or"
echo "         open http://localhost:8000/standalone.html  (pure HTML)"
