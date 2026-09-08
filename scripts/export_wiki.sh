#!/usr/bin/env bash
# Regenerate the public wiki (ADR-009) from this working repository into the wiki checkout.
# Usage: scripts/export_wiki.sh [WIKI_DIR]   (default: ../kupuna-bench-public.wiki)
# The wiki is its own git repository; this script rebuilds its working tree and leaves the commit to you.
set -euo pipefail
SRC="$(git rev-parse --show-toplevel)"
WIKI="${1:-$SRC/../kupuna-bench-public.wiki}"
WIKI_URL="https://github.com/JeremyGracey-AI/kupuna-bench-public.wiki.git"
COMMIT="$(git -C "$SRC" rev-parse --short HEAD)"
if [ -n "$(git -C "$SRC" status --porcelain)" ]; then
  echo "working tree is not clean; commit first" >&2; exit 1
fi
if [ ! -d "$WIKI/.git" ]; then
  git clone "$WIKI_URL" "$WIKI" || {
    echo "the wiki repository does not exist yet: create its first page on GitHub, then rerun" >&2; exit 1; }
fi
git -C "$WIKI" fetch -q origin
git -C "$WIKI" reset -q --hard origin/master
# Refuse to overwrite hand edits made on GitHub since the last regeneration (ADR-009): they belong in
# docs/ or docs/wiki/. Port them, commit, then rerun with FORCE=1.
LAST_GEN="$(git -C "$WIKI" log --format=%H --grep='^\[worker\] regenerate wiki' -n 1 origin/master || true)"
HAND="$(git -C "$WIKI" log --format='%h %an %s' ${LAST_GEN:+$LAST_GEN..}origin/master)"
if [ -n "$HAND" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "the wiki has hand edits since the last regeneration; port them into docs/ or docs/wiki/, commit, then rerun with FORCE=1:" >&2
  echo "$HAND" >&2
  git -C "$WIKI" diff ${LAST_GEN:+$LAST_GEN..}origin/master >&2
  exit 1
fi
uv run --project "$SRC" python "$SRC/scripts/build_wiki.py" --root "$SRC" --out "$WIKI" --commit "$COMMIT"
echo "rendered the wiki from working commit $COMMIT into $WIKI"
echo "next: cd $WIKI && git add -A && git commit -m \"[worker] regenerate wiki from working commit $COMMIT\" && git push"
