#!/usr/bin/env bash
# The gate: the four steps of .github/workflows/ci.yml, one per line, run in the tree this script lives in.
# `set -e` stops at the first failing line. A chain (`a && b`) would not, which is how a ruff error
# reached both mains on 2026-09-08. tests/test_gate_script.py runs this script with a stand-in `uv` to
# prove it stops at the first failure and runs CI's steps in CI's order.
# Run it before claiming done; .githooks/pre-commit runs it on the exported index of every commit.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RESULTS="$(mktemp -d)"
trap 'rm -rf "$RESULTS"' EXIT
uv run ruff check .
uv run pyright
uv run pytest
uv run kupuna-bench run --fake --scenarios tests/fixtures/scenarios --allow-draft --out "$RESULTS"
echo "gate: green"
