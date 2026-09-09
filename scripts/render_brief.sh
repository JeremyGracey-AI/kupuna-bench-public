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
SHOT_PROFILE="$PROFILE-shot"
trap 'pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true; sleep 1; rm -rf "$PROFILE" "$SHOT_PROFILE" 2>/dev/null || true' EXIT
rm -f "$OUT"
"$BIN" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$PROFILE" --no-pdf-header-footer \
  --print-to-pdf="$OUT" "file://$SRC" >/dev/null 2>&1 &
for _ in $(seq 1 60); do sleep 1; [ -s "$OUT" ] && break; done
sleep 2
[ -s "$OUT" ] || { echo "render failed: $OUT not written" >&2; exit 1; }
echo "rendered $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"

# Social preview (1280x640) for the GitHub repository: Fig. 1 from the brief under the project name.
SOCIAL="$ROOT/docs/brief/social-preview.png"
mkdir -p "$SHOT_PROFILE"
TMPHTML="$SHOT_PROFILE/social-preview.html"
python3 - "$SRC" "$TMPHTML" <<'PY'
import re, sys
from pathlib import Path
brief = Path(sys.argv[1]).read_text(encoding="utf-8")
svg = re.search(r'<svg viewBox="0 0 760 130".*?</svg>', brief, re.S).group(0)
Path(sys.argv[2]).write_text(f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0}} body{{width:1280px;height:640px;overflow:hidden;background:#ffffff;font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:#1f2328;position:relative}}
.wrap{{padding:54px 72px 0}} h1{{font-size:52px;margin:0 0 8px;letter-spacing:-0.01em;color:#111}} h1 span{{font-weight:400;color:#5b6470}}
p.tag{{font-size:27px;color:#5b6470;margin:0 0 30px;line-height:1.25}} svg{{width:1136px;height:auto;display:block}}
.foot{{position:absolute;bottom:34px;left:72px;right:72px;display:flex;justify-content:space-between;font-size:21px;color:#1f3a5f}}
</style></head><body><div class="wrap"><h1>KŪPUNA-AI Bench <span>"Let's talk story."</span></h1><p class="tag">Measuring overrefusal and harmful compliance in AI conversations with older adults</p>{svg}</div>
<div class="foot"><span>github.com/JeremyGracey-AI/kupuna-bench-public</span><span>The Gerontechnology Group, LLC</span></div></body></html>""", encoding="utf-8")
PY
rm -f "$SOCIAL"
"$BIN" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$SHOT_PROFILE" --hide-scrollbars --window-size=1280,640 \
  --screenshot="$SOCIAL" "file://$TMPHTML" >/dev/null 2>&1 &
for _ in $(seq 1 60); do sleep 1; [ -s "$SOCIAL" ] && break; done
sleep 2
[ -s "$SOCIAL" ] || { echo "render failed: $SOCIAL not written" >&2; exit 1; }
echo "rendered $SOCIAL ($(wc -c < "$SOCIAL" | tr -d ' ') bytes)"
