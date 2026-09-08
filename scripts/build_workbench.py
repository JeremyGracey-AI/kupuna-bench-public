"""Build workbench/index.html from the repo.

Usage: uv run python scripts/build_workbench.py [scenarios_dir].
"""

from __future__ import annotations

import sys
from pathlib import Path

from kupuna_bench.workbench import build_workbench

if __name__ == "__main__":
    scenarios = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scenarios/v0")
    target = build_workbench(
        scenarios_dir=scenarios,
        results_dir=Path("results"),
        docs_dir=Path("docs"),
        out=Path("workbench/index.html"),
    )
    print(target)
