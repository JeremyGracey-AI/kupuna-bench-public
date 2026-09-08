from pathlib import Path

from typer.testing import CliRunner

from kupuna_bench.cli import app
from kupuna_bench.workbench import build_workbench

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
REPO = Path(__file__).resolve().parents[1]


def test_workbench_renders_docs_scenarios_and_latest_results(tmp_path: Path) -> None:
    results = tmp_path / "results"
    CliRunner().invoke(
        app,
        [
            "run",
            "--fake",
            "--scenarios",
            str(FIXTURES),
            "--allow-draft",
            "--runs",
            "1",
            "--out",
            str(results),
        ],
    )
    out = build_workbench(
        scenarios_dir=FIXTURES, results_dir=results, docs_dir=REPO / "docs", out=tmp_path / "index.html"
    )
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<title>KŪPUNA-AI Bench Workbench</title>")
    assert "<html" not in html and "<body" not in html
    assert "t2-meds-statin" in html and "I'm 84 and have taken atorvastatin" in html
    assert "paternalistic withholding" in html.lower() and "ADR-003" in html
    assert "<svg" in html and "Direction A" in html
    assert html.count("<h1>") == 1
    assert "<h3>The construct: paternalistic withholding</h3>" in html


def test_workbench_without_results(tmp_path: Path) -> None:
    out = build_workbench(
        scenarios_dir=FIXTURES, results_dir=tmp_path / "none", docs_dir=REPO / "docs", out=tmp_path / "i.html"
    )
    assert "No run recorded yet" in out.read_text(encoding="utf-8")


def test_workbench_picks_numerically_latest_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    CliRunner().invoke(
        app,
        [
            "run",
            "--fake",
            "--scenarios",
            str(FIXTURES),
            "--allow-draft",
            "--runs",
            "1",
            "--out",
            str(source),
        ],
    )
    (json_path,) = sorted(source.glob("run-*.json"))
    results = tmp_path / "results"
    results.mkdir()
    for name in ("run-2026-09-08-9.json", "run-2026-09-08-10.json"):
        (results / name).write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    out = build_workbench(
        scenarios_dir=FIXTURES, results_dir=results, docs_dir=REPO / "docs", out=tmp_path / "index.html"
    )
    html = out.read_text(encoding="utf-8")
    assert "run-2026-09-08-10.json" in html
