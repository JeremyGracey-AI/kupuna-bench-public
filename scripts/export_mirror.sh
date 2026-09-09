#!/usr/bin/env bash
# Export the public-mirror allowlist (ADR-008) from this working repository into the mirror checkout.
# Usage: scripts/export_mirror.sh [MIRROR_DIR]   (default: ../kupuna-bench-public)
# The mirror keeps its own git history; this script replaces its working tree and leaves the commit to you.
set -euo pipefail
SRC="$(git rev-parse --show-toplevel)"
MIRROR="${1:-$SRC/../kupuna-bench-public}"
COMMIT="$(git -C "$SRC" rev-parse --short HEAD)"
if [ -n "$(git -C "$SRC" status --porcelain)" ]; then
  echo "working tree is not clean; commit first" >&2; exit 1
fi
mkdir -p "$MIRROR"
# Clear everything in the mirror except its git metadata.
find "$MIRROR" -mindepth 1 -maxdepth 1 ! -name .git ! -name .venv -exec rm -rf {} +
ALLOWLIST=(
  src tests .github .githooks pyproject.toml uv.lock .python-version .gitignore
  README.md CLAUDE.md AI-USE.md CITATION.cff CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md LICENSE LICENSE-DATA
  docs/construct.md docs/method.md docs/rubric.md docs/rubric.yaml docs/decisions
  docs/memos/2026-09-08-rubric-v0-sensitizing-default.md docs/sampling-log.md docs/brief
  labels/README.md scripts golden results/.gitkeep scenarios/probe docs/wiki
)
git -C "$SRC" archive HEAD "${ALLOWLIST[@]}" | tar -x -C "$MIRROR"
# Machine-generated coding memos never travel; the human-written memo above is the only one exported.
find "$MIRROR/docs/memos" -name '*-ai-coding-*' -delete 2>/dev/null || true
echo "exported allowlist from working commit $COMMIT into $MIRROR"
echo "next: cd $MIRROR && git add -A && git commit -m \"[worker] refresh mirror from working commit $COMMIT\" && git push"
