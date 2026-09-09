"""CITATION.cff is read by GitHub's "Cite this repository" widget and by Zenodo on every release; it has to
parse, and its version has to move with the package."""

from importlib.metadata import version
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CITATION = ROOT / "CITATION.cff"


def test_citation_file_parses_and_tracks_the_package() -> None:
    # 2026-09-08: the tagline landed in the title with unescaped inner quotes, which is not YAML.
    meta = yaml.safe_load(CITATION.read_text(encoding="utf-8"))
    assert meta["cff-version"] == "1.2.0"
    assert meta["version"] == version("kupuna-bench")
    assert meta["title"].startswith('KŪPUNA-AI Bench "Let\'s talk story."')
    assert meta["doi"].startswith("10.5281/zenodo.")
    assert meta["repository-code"] == "https://github.com/JeremyGracey-AI/kupuna-bench-public"
