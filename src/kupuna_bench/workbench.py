"""Render the review page Melissa reads: docs, scenario cards, the latest run, the chart, ADRs.

It is a rendering of repo files, never a second source of truth. Output is body-only HTML
(title and style first) so the claude.ai Artifact tool can wrap it.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

import markdown

from kupuna_bench.chart import render_chart
from kupuna_bench.run import RunResult
from kupuna_bench.scenarios import Scenario, ScenarioError, load_scenarios

STYLE = """
<style>
:root{--bg:#fafaf7;--fg:#1f2328;--muted:#6b7280;--card:#ffffff;--line:#e5e7eb;--accent:#1f5f8b;
color-scheme:light dark}
@media (prefers-color-scheme: dark){
:root:not([data-theme="light"]){--bg:#0f1115;--fg:#e6e6e6;--muted:#9aa0a6;--card:#171a21;
--line:#2a2f3a;--accent:#7fb3d5}
}
:root[data-theme="dark"]{--bg:#0f1115;--fg:#e6e6e6;--muted:#9aa0a6;--card:#171a21;
--line:#2a2f3a;--accent:#7fb3d5}
body{background:var(--bg);color:var(--fg);max-width:1040px;margin:0 auto;padding:24px;line-height:1.5}
h1,h2,h3{line-height:1.2} h2{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin:12px 0}
.meta{color:var(--muted);font-size:.9em}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
.badge{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 8px;
font-size:.8em;margin-left:6px}
.wide{overflow-x:auto} nav a{margin-right:14px;color:var(--accent)}
</style>
"""


_HEADING_RE = re.compile(r"<(/?)h([1-6])(?=[ >])")


def _demote_headings(fragment: str, *, by: int = 2) -> str:
    """Shift `<h1>`..`<h6>` (open and close tags) down `by` levels, capped at `<h6>`.

    Keeps a doc's own `# Title` nested under the page's `<h2>` section headings instead of
    outranking them.
    """

    def _shift(match: re.Match[str]) -> str:
        level = min(6, int(match.group(2)) + by)
        return f"<{match.group(1)}h{level}"

    return _HEADING_RE.sub(_shift, fragment)


# docs/*.md is repo-authored content behind the same write boundary as the code, not user
# input, so raw HTML embedded in it passes through markdown.markdown() unescaped by design.
def _md(path: Path) -> str:
    if not path.is_file():
        return f"<p class='meta'>missing: {escape(path.name, quote=False)}</p>"
    rendered = markdown.markdown(path.read_text(encoding="utf-8"), extensions=["tables"])
    return _demote_headings(rendered)


def _scenario_card(scenario: Scenario) -> str:
    # quote=False: this text lands inside element content, not an attribute value, so the
    # apostrophes clinicians write ("I'm 84...") stay literal instead of becoming &#x27;.
    rows = "".join(
        f"<tr><td>{i}</td><td>{escape(t.age_cue, quote=False)}</td><td>{escape(t.neutral, quote=False)}</td>"
        f"<td>{escape(scenario.key_for(i).expected, quote=False)}</td></tr>"
        for i, t in enumerate(scenario.turns)
    )
    return (
        f"<div class='card' id='{escape(scenario.id)}'><h3>"
        f"{escape(scenario.title or scenario.id, quote=False)}"
        f"<span class='badge'>{escape(scenario.domain, quote=False)}</span>"
        f"<span class='badge'>{escape(scenario.tier, quote=False)}</span>"
        f"<span class='badge'>{escape(scenario.status, quote=False)}</span></h3>"
        f"<p class='meta'>{escape(scenario.id, quote=False)} · reviewed by "
        f"{escape(scenario.reviewed_by or 'nobody yet', quote=False)}</p>"
        f"<p>{escape(scenario.situation, quote=False)}</p><div class='wide'><table><tr><th>turn</th>"
        f"<th>age cue</th><th>neutral</th><th>answer key</th></tr>{rows}</table></div></div>"
    )


# run-YYYY-MM-DD-N.json (records.next_record_path's naming). N is unpadded, so a lexical sort
# would put "-10.json" before "-9.json"; sort by the parsed (date, N) key instead.
_RUN_JSON_RE = re.compile(r"^run-(\d{4}-\d{2}-\d{2})-(\d+)\.json$")


def _latest_result(results_dir: Path) -> tuple[RunResult | None, Path | None]:
    candidates: list[tuple[tuple[str, int], Path]] = []
    if results_dir.is_dir():
        for path in results_dir.glob("run-*.json"):
            match = _RUN_JSON_RE.match(path.name)
            if match is not None:
                candidates.append(((match.group(1), int(match.group(2))), path))
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda candidate: candidate[0])[1]
    return RunResult.model_validate(json.loads(latest.read_text(encoding="utf-8"))), latest


def build_workbench(*, scenarios_dir: Path, results_dir: Path, docs_dir: Path, out: Path) -> Path:
    try:
        scenarios = load_scenarios(scenarios_dir)
        scenario_html = "".join(_scenario_card(s) for s in scenarios)
    except ScenarioError as exc:
        scenario_html = "<div class='card'><h3>Scenario validation errors</h3><ul>" + "".join(
            f"<li>{escape(m, quote=False)}</li>" for m in exc.messages
        ) + "</ul></div>"
    result, latest = _latest_result(results_dir)
    if result is None:
        results_html = "<p class='meta'>No run recorded yet.</p>"
    else:
        summary = result.summary()
        results_html = (
            f"<p class='meta'>{escape(latest.name if latest else '', quote=False)} · "
            f"judge {escape(result.judge.name, quote=False)} · "
            f"runs {result.runs} · rubric {escape(result.rubric_version, quote=False)}</p>"
            f"<div class='wide'>{render_chart(summary, title='Latest run')}</div>"
            f"<div class='wide'>{markdown.markdown(summary.table(), extensions=['tables'])}</div>"
        )
    adrs = (
        "".join(
            f"<li><a href='#{escape(p.stem)}'>{escape(p.stem, quote=False)}</a></li>"
            for p in sorted((docs_dir / "decisions").glob("ADR-*.md"))
        )
        if (docs_dir / "decisions").is_dir()
        else ""
    )
    adr_bodies = (
        "".join(
            f"<div class='card' id='{escape(p.stem)}'>{_md(p)}</div>"
            for p in sorted((docs_dir / "decisions").glob("ADR-*.md"))
        )
        if (docs_dir / "decisions").is_dir()
        else ""
    )
    html = (
        "<title>KŪPUNA-AI Bench Workbench</title>"
        + STYLE
        + "<h1>KŪPUNA-AI Bench Workbench</h1><p class='meta'>Rendered from the repo. Comment here; "
        "changes land in the repo.</p>"
        "<nav><a href='#construct'>Construct</a><a href='#rubric'>Rubric</a><a href='#method'>Method</a>"
        "<a href='#scenarios'>Scenarios</a><a href='#results'>Results</a><a href='#decisions'>Decisions</a>"
        "<a href='#sampling'>Sampling log</a></nav>"
        f"<h2 id='construct'>Construct</h2>{_md(docs_dir / 'construct.md')}"
        f"<h2 id='rubric'>Rubric</h2>{_md(docs_dir / 'rubric.md')}"
        f"<h2 id='method'>Method</h2>{_md(docs_dir / 'method.md')}"
        f"<h2 id='scenarios'>Scenarios</h2>{scenario_html}"
        f"<h2 id='results'>Results</h2>{results_html}"
        f"<h2 id='decisions'>Decisions</h2><ul>{adrs}</ul>{adr_bodies}"
        f"<h2 id='sampling'>Sampling log</h2>{_md(docs_dir / 'sampling-log.md')}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
