"""The composition root: reads settings, constructs adapters, runs, writes outputs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from kupuna_bench.agreement import agreement as _agreement
from kupuna_bench.agreement import judge_labels, load_labels
from kupuna_bench.chart import render_chart
from kupuna_bench.chat import AnthropicChat, Chat, OpenRouterChat, ScriptedChat
from kupuna_bench.coder import audit, incidents_from_result, render_memos, scripted_coder_responder
from kupuna_bench.coder import code as _code
from kupuna_bench.gate import PLUMBING_GATE, Gate, check_gate, gate_metrics, load_gate_from_meta
from kupuna_bench.judge import Judge, LLMJudge, ScriptedJudge
from kupuna_bench.records import facts_from_result, next_record_path, write_record
from kupuna_bench.rubric import Rubric, load_rubric
from kupuna_bench.run import JudgeFamilyConflict, NothingToRun, RunResult
from kupuna_bench.run import regrade as _regrade
from kupuna_bench.run import run as _run
from kupuna_bench.scenarios import Scenario, ScenarioError, load_scenarios
from kupuna_bench.settings import Settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="KŪPUNA-Bench harness.")
GOLDEN = Path("golden/kupuna_golden.json")


def chat_for(model_id: str, settings: Settings) -> Chat:
    if "/" in model_id:
        if not settings.openrouter_api_key:
            raise typer.BadParameter(
                f"{model_id} needs OPENROUTER_API_KEY; set it in the environment or .env"
            )
        return OpenRouterChat(model_id, api_key=settings.openrouter_api_key)
    if not settings.anthropic_api_key:
        raise typer.BadParameter(
            f"{model_id} needs ANTHROPIC_API_KEY; set it, or use the OpenRouter id anthropic/<model>"
        )
    return AnthropicChat(model_id, api_key=settings.anthropic_api_key)


def roster(
    settings: Settings,
    *,
    models: str | None = None,
    judge: str | None = None,
    fake: bool = False,
    rubric: Rubric,
) -> tuple[list[Chat], Judge]:
    if fake:
        return (
            [ScriptedChat("fake-a", family="fake-a"), ScriptedChat("fake-b", family="fake-b")],
            ScriptedJudge("fake-judge", family="fake-judge"),
        )
    ids = [m.strip() for m in models.split(",")] if models else settings.model_ids()
    judge_id = judge or settings.kupuna_judge
    return [chat_for(m, settings) for m in ids], LLMJudge(chat_for(judge_id, settings), rubric)


def _golden_meta() -> tuple[Gate, bool]:
    if not GOLDEN.is_file():
        return PLUMBING_GATE, False
    meta = json.loads(GOLDEN.read_text(encoding="utf-8")).get("_meta", {})
    gate = load_gate_from_meta(meta) if isinstance(meta.get("thresholds"), dict) else PLUMBING_GATE
    return gate, bool(meta.get("promoted"))


def write_outputs(
    result: RunResult,
    out_dir: Path,
    *,
    gate_name: str,
    verdict: str,
    shortfalls: list[str],
    driver: str,
    draft: bool,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = next_record_path(out_dir)
    json_path = record_path.with_suffix(".json")
    json_path.write_text(result.model_dump_json(indent=1), encoding="utf-8")
    facts = facts_from_result(
        result,
        gate_name=gate_name,
        verdict=verdict,
        shortfalls=shortfalls,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        driver=driver,
        draft=draft,
    )
    write_record(facts, out_dir, path=record_path)
    return record_path, json_path


def _load(scenarios_dir: Path) -> list[Scenario]:
    try:
        return load_scenarios(scenarios_dir)
    except ScenarioError as exc:
        for message in exc.messages:
            typer.echo(message)
        raise typer.Exit(code=2) from None


def _finish(result: RunResult, out: Path, *, n_scenarios: int, driver: str, fake: bool) -> None:
    try:
        gate, promoted = _golden_meta()
    except (OSError, ValueError) as exc:
        typer.echo(f"golden file is invalid: {exc}")
        raise typer.Exit(code=2) from None
    gate_name = "PLUMBING_GATE" if fake or not promoted else "golden"
    metrics = gate_metrics(result, n_scenarios=n_scenarios)
    ok, shortfalls = check_gate(metrics, PLUMBING_GATE if gate_name == "PLUMBING_GATE" else gate)
    record_path, json_path = write_outputs(
        result,
        out,
        gate_name=gate_name,
        verdict="PASS" if ok else "FAIL",
        shortfalls=shortfalls,
        driver=driver,
        draft=(not promoted) or result.allow_draft,
    )
    typer.echo(result.summary().table())
    typer.echo(f"record: {record_path}\njson: {json_path}\nverdict: {'PASS' if ok else 'FAIL'}")
    for item in shortfalls:
        typer.echo(f"  - {item}")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def validate(
    scenarios: Annotated[
        Path, typer.Argument(help="Directory of scenario YAML files")
    ] = Path("scenarios/v0"),
) -> None:
    """Validate every scenario file and report PI-facing messages."""
    loaded = _load(scenarios)
    promoted = sum(1 for s in loaded if s.status == "promoted")
    typer.echo(f"OK: {len(loaded)} scenarios ({promoted} promoted, {len(loaded) - promoted} draft)")


@app.command()
def run(
    fake: Annotated[bool, typer.Option(help="Scripted adapters, no API keys")] = False,
    scenarios: Annotated[Path | None, typer.Option(help="Scenario directory")] = None,
    allow_draft: Annotated[bool, typer.Option(help="Include unpromoted scenarios")] = False,
    runs: Annotated[int, typer.Option(min=1)] = 3,
    spend_cap: Annotated[float | None, typer.Option(help="USD cap on model-under-test spend")] = None,
    out: Annotated[Path | None, typer.Option(help="Results directory")] = None,
    models: Annotated[str | None, typer.Option(help="Comma-separated model ids")] = None,
    judge: Annotated[str | None, typer.Option(help="Judge model id")] = None,
    system_prompt: Annotated[str | None, typer.Option(help="System prompt for models under test")] = None,
) -> None:
    """Run the benchmark and write an append-only record plus JSON."""
    settings = Settings()
    rubric = load_rubric()
    scenarios_dir = scenarios or Path(settings.kupuna_scenarios)
    out_dir = out or Path(settings.kupuna_results)
    loaded = _load(scenarios_dir)
    try:
        chats, the_judge = roster(settings, models=models, judge=judge, fake=fake, rubric=rubric)
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    cap = 0.0 if fake else (spend_cap if spend_cap is not None else settings.kupuna_spend_cap_usd)
    try:
        result = _run(
            loaded,
            models=chats,
            judge=the_judge,
            rubric=rubric,
            runs=runs,
            allow_draft=allow_draft,
            spend_cap_usd=None if fake else cap,
            system_prompt=system_prompt,
            on_row=lambda row: typer.echo(
                f"row {row.scenario_id}/{row.variant}/{row.model}/{row.run_index}"
                + (f" ERROR {row.error.stage}" if row.error else "")
            ),
        )
    except (JudgeFamilyConflict, NothingToRun) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    n_scenarios = len(loaded) if allow_draft else sum(1 for s in loaded if s.status == "promoted")
    _finish(result, out_dir, n_scenarios=n_scenarios, driver="kupuna-bench run", fake=fake)


@app.command()
def regrade(
    result_json: Annotated[Path, typer.Argument(help="A results JSON written by `run`")],
    fake: Annotated[bool, typer.Option()] = False,
    scenarios: Annotated[Path | None, typer.Option()] = None,
    judge: Annotated[str | None, typer.Option(help="Judge model id")] = None,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Re-judge the kept transcripts of a previous run with a different judge."""
    settings = Settings()
    rubric = load_rubric()
    loaded = _load(scenarios or Path(settings.kupuna_scenarios))
    try:
        previous = RunResult.model_validate(json.loads(result_json.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load {result_json}: {exc}")
        raise typer.Exit(code=2) from None
    try:
        the_judge = (
            ScriptedJudge("fake-judge-2", family="fake-judge-2")
            if fake
            else LLMJudge(chat_for(judge or settings.kupuna_judge, settings), rubric)
        )
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    try:
        result = _regrade(previous, loaded, the_judge, rubric=rubric)
    except (JudgeFamilyConflict, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    n_scenarios = len({row.scenario_id for row in result.rows})
    _finish(
        result,
        out or Path(settings.kupuna_results),
        n_scenarios=n_scenarios,
        driver="kupuna-bench regrade",
        fake=fake,
    )


def _fmt_overlap(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


@app.command()
def code(
    result_json: Annotated[Path, typer.Argument(help="A results JSON written by `run`")],
    fake: Annotated[bool, typer.Option()] = False,
    coders: Annotated[str | None, typer.Option(help="Comma-separated coder model ids")] = None,
    orders: Annotated[int, typer.Option(min=1)] = 2,
    seed: Annotated[int, typer.Option()] = 0,
    human_codes: Annotated[Path | None, typer.Option(help="Text file, one blind human code per line")] = None,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Blind multi-family grounded-theory coding of a run's transcripts, with a forcing audit."""
    settings = Settings()
    try:
        previous = RunResult.model_validate(json.loads(result_json.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load {result_json}: {exc}")
        raise typer.Exit(code=2) from None
    if fake:
        chats: list[Chat] = [
            ScriptedChat(f"fake-coder-{f}", family=f"fake-{f}", responder=scripted_coder_responder)
            for f in ("a", "b", "c")
        ]
    else:
        ids = [c.strip() for c in coders.split(",")] if coders else settings.coder_ids()
        chats = [chat_for(c, settings) for c in ids]
    coding = _code(incidents_from_result(previous), coders=chats, orders=orders, seed=seed)
    humans = (
        [line.strip() for line in human_codes.read_text(encoding="utf-8").splitlines() if line.strip()]
        if human_codes
        else None
    )
    report = audit(coding, human_codes=humans)
    out_dir = out or Path(settings.kupuna_results)
    out_dir.mkdir(parents=True, exist_ok=True)
    coding_path = out_dir / f"{result_json.stem}-coding.json"
    coding_path.write_text(coding.model_dump_json(indent=1), encoding="utf-8")
    memo_dir = Path("docs/memos")
    memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memo_dir / f"{date.today().isoformat()}-ai-coding-{result_json.stem}.md"
    memo_path.write_text(render_memos(coding), encoding="utf-8")
    typer.echo(f"coding: {coding_path}\nmemos: {memo_path}")
    typer.echo(
        f"categories: {len(coding.categories)}  codes: {len(coding.codes)}  errors: {len(coding.errors)}"
    )
    typer.echo(
        f"theory vocabulary in categories: {_fmt_overlap(report.theory_overlap)} of "
        f"{report.n_categories} distinct categories (vocabulary leakage, not conceptual forcing)"
    )
    typer.echo(f"construct vocabulary in categories: {_fmt_overlap(report.construct_overlap)}")
    for family, value in report.per_family.items():
        typer.echo(f"  {family}: theory vocabulary {_fmt_overlap(value)}")
    typer.echo(f"coder errors: {report.n_errors}")
    if report.human_overlap is None:
        typer.echo("human comparator: none (prototype built, audit method specified)")
    else:
        typer.echo(
            f"human comparator: {report.human_overlap:.2f} of {report.human_codes} blind human "
            f"codes matched by {report.human_match_rule}"
        )


@app.command()
def agreement(
    labels: Annotated[list[Path], typer.Argument(help="Human label CSV files")],
    result: Annotated[Path, typer.Option(help="Results JSON whose judge verdicts join the comparison")],
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Human–human and judge–human agreement: weighted κ on severity, plain κ on pass/fail."""
    settings = Settings()
    try:
        previous = RunResult.model_validate(json.loads(result.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load {result}: {exc}")
        raise typer.Exit(code=2) from None
    try:
        human_labels = load_labels(labels)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    all_labels = human_labels + judge_labels(previous)
    report = _agreement(all_labels, pass_max_severity=previous.pass_max_severity)
    out_dir = out or Path(settings.kupuna_results)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.stem}-agreement.json"
    path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    typer.echo(report.table())
    typer.echo(f"agreement: {path}")


@app.command()
def chart(
    result_json: Annotated[Path, typer.Argument(help="Results JSON written by `run`")],
    out: Annotated[Path | None, typer.Option(help="Output .svg path (default: next to the JSON)")] = None,
) -> None:
    """Render the A/B failure-rate chart for a run."""
    try:
        previous = RunResult.model_validate(json.loads(result_json.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load {result_json}: {exc}")
        raise typer.Exit(code=2) from None
    target = out or result_json.with_suffix(".svg")
    target.write_text(
        render_chart(previous.summary(), title=f"KŪPUNA-Bench {result_json.stem}"),
        encoding="utf-8",
    )
    typer.echo(f"chart: {target}")
