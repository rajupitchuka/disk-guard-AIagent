#!/usr/bin/env bash
# Regenerate the Word version of the whitepaper from the canonical
# markdown source. Run from the repo root:
#
#     ./scripts/build_docx.sh
#
# Requires pandoc:  brew install pandoc

set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v pandoc >/dev/null 2>&1; then
    echo "ERROR: pandoc is not installed."
    echo "  install with:  brew install pandoc"
    exit 1
fi

INPUT="docs/disk-guard-whitepaper.md"
OUTPUT="docs/disk-guard-whitepaper.docx"

if [[ ! -f "$INPUT" ]]; then
    echo "ERROR: source markdown not found at $INPUT"
    exit 1
fi

echo "Converting $INPUT → $OUTPUT ..."

pandoc "$INPUT" \
    --output "$OUTPUT" \
    --toc \
    --toc-depth=3 \
    --resource-path=docs:assets:. \
    --metadata title="Disk Guard AI Agent — A Predictive Multi-AI Architecture" \
    --metadata author="Naga Raju Pitchuka, TCS" \
    --metadata date="May 2026"

echo "  ✓ wrote $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
echo ""
echo "Open with:"
echo "    open $OUTPUT"
