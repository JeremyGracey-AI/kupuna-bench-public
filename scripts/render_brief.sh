#!/usr/bin/env bash
# Render docs/brief/kupuna-bench-brief.html to docs/brief/kupuna-bench-brief.pdf with a headless Chromium.
# Usage: scripts/render_brief.sh   (set BROWSER_BIN to override the browser binary)
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/docs/brief/kupuna-bench-brief.html"
OUT="$ROOT/docs/brief/kupuna-bench-brief.pdf"
BIN="${BROWSER_BIN:-}"
for c in "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "$(command -v chromium || true)" "$(command -v google-chrome || true)"; do
  [ -z "$BIN" ] && [ -n "$c" ] && [ -x "$c" ] && BIN="$c"
done
[ -n "$BIN" ] || { echo "no Chromium-family browser found; set BROWSER_BIN" >&2; exit 1; }
PROFILE="$(mktemp -d)"
trap 'pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true; sleep 1; rm -rf "$PROFILE" 2>/dev/null || true' EXIT
rm -f "$OUT"
"$BIN" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$PROFILE" --no-pdf-header-footer \
  --print-to-pdf="$OUT" "file://$SRC" >/dev/null 2>&1 &
for _ in $(seq 1 60); do sleep 1; [ -s "$OUT" ] && break; done
sleep 2
[ -s "$OUT" ] || { echo "render failed: $OUT not written" >&2; exit 1; }
echo "rendered $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"
