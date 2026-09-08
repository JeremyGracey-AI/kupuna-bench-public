from pathlib import Path

from kupuna_bench.chart import PALETTE, render_chart
from kupuna_bench.chat import ScriptedChat
from kupuna_bench.judge import ScriptedJudge
from kupuna_bench.rubric import load_rubric
from kupuna_bench.run import Cell, Summary, run
from kupuna_bench.scenarios import load_scenarios

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
RUBRIC = load_rubric()


def test_chart_has_one_bar_per_cell_per_direction() -> None:
    models = [ScriptedChat("fake-a", family="a"), ScriptedChat("fake-b", family="b")]
    result = run(
        load_scenarios(FIXTURES),
        models=models,
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
        allow_draft=True,
    )
    summary = result.summary()
    svg = render_chart(summary, title="fixture run")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count('class="bar"') == 2 * sum(1 for c in summary.cells if c.rate_a is not None)
    assert "fixture run" in svg and "Direction A" in svg and "Direction B" in svg
    assert len(PALETTE) >= 4


def test_chart_handles_missing_rates() -> None:
    summary = Summary(
        total=1,
        graded=0,
        cells=(
            Cell(
                model="m",
                tier="T1",
                variant="age_cue",
                n=1,
                graded=0,
                rate_a=None,
                rate_b=None,
                mean_a=None,
                mean_b=None,
            ),
        ),
        age_cue_delta=(),
        spread_by_tier={"T1": None},
        errors={"chat": 1},
    )
    svg = render_chart(summary, title="empty")
    assert 'class="bar"' not in svg and "n/a" in svg


def test_chart_legend_stays_inside_viewbox() -> None:
    import re

    models = [
        ScriptedChat("openai/gpt-5.1", family="openai"),
        ScriptedChat("anthropic/claude-opus-4.5", family="anthropic"),
        ScriptedChat("google/gemini-3-pro-preview", family="google"),
        ScriptedChat("meta-llama/llama-4-maverick", family="meta"),
    ]
    result = run(
        load_scenarios(FIXTURES),
        models=models,
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
        allow_draft=True,
    )
    summary = result.summary()
    svg = render_chart(summary, title="long names")
    height_match = re.search(r'height="(\d+)"', svg)
    assert height_match, "SVG must have a height attribute"
    height = int(height_match.group(1))
    x_matches = re.findall(r'(?:x|y)="([\d.]+)"', svg)
    numeric_coords = [float(m) for m in x_matches]
    for coord in numeric_coords:
        if "x" in svg[svg.find(f'"{coord}"') - 5 : svg.find(f'"{coord}"')]:
            assert coord <= 960, f"x coordinate {coord} exceeds WIDTH 960"
        else:
            assert coord <= height, f"y coordinate {coord} exceeds height {height}"


def test_chart_text_is_theme_aware() -> None:
    import re

    models = [ScriptedChat("fake-a", family="a"), ScriptedChat("fake-b", family="b")]
    result = run(
        load_scenarios(FIXTURES),
        models=models,
        judge=ScriptedJudge(),
        rubric=RUBRIC,
        runs=1,
        allow_draft=True,
    )
    summary = result.summary()
    svg = render_chart(summary, title="theme test")
    text_matches = re.findall(r'<text[^>]*>', svg)
    for text_elem in text_matches:
        assert 'fill="currentColor"' in text_elem, (
            f"All <text> elements must have fill=\"currentColor\", got: {text_elem}"
        )
    assert not re.search(r'fill="#666"', svg), "No literal #666 fill colors allowed"
    assert not re.search(r'fill="#999"', svg), "No literal #999 fill colors allowed"
