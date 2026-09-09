"""The composition root: reads settings, constructs adapters, runs, writes outputs."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import subprocess
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml

from kupuna_bench.agreement import agreement as _agreement
from kupuna_bench.agreement import check_label_directions, decode_items, judge_labels, load_labels
from kupuna_bench.chart import render_chart
from kupuna_bench.chat import AnthropicChat, Chat, OpenRouterChat, ScriptedChat
from kupuna_bench.coder import audit, incidents_from_result, render_memos, scripted_coder_responder
from kupuna_bench.coder import code as _code
from kupuna_bench.gate import PLUMBING_GATE, Gate, check_gate, gate_metrics, load_gate_from_meta
from kupuna_bench.judge import Judge, LLMJudge, ScriptedJudge
from kupuna_bench.manifest import Manifest, ModelRef
from kupuna_bench.records import RunPaths, allocate_run, facts_from_result, write_json_atomic, write_record
from kupuna_bench.rubric import DEFAULT_RUBRIC_PATH, Rubric, load_rubric, rubric_sha256
from kupuna_bench.run import JudgeFamilyConflict, NothingToRun, Row, RunResult
from kupuna_bench.run import regrade as _regrade
from kupuna_bench.run import run as _run
from kupuna_bench.scenarios import Scenario, ScenarioError, dataset_sha256, key_warnings, load_scenarios
from kupuna_bench.settings import Settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="KŪPUNA-AI Bench harness.")
GOLDEN = Path("golden/kupuna_golden.json")


DEFAULT_MAX_TOKENS = 2048  # ADR-013; recorded per adapter in the manifest


def chat_for(model_id: str, settings: Settings, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> Chat:
    if "/" in model_id:
        if not settings.openrouter_api_key:
            raise typer.BadParameter(
                f"{model_id} needs OPENROUTER_API_KEY; set it in the environment or .env"
            )
        return OpenRouterChat(model_id, api_key=settings.openrouter_api_key, max_tokens=max_tokens)
    if not settings.anthropic_api_key:
        raise typer.BadParameter(
            f"{model_id} needs ANTHROPIC_API_KEY; set it, or use the OpenRouter id anthropic/<model>"
        )
    return AnthropicChat(model_id, api_key=settings.anthropic_api_key, max_tokens=max_tokens)


def roster(
    settings: Settings,
    *,
    models: str | None = None,
    judge: str | None = None,
    fake: bool = False,
    rubric: Rubric,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[list[Chat], Judge]:
    if fake:
        return (
            [ScriptedChat("fake-a", family="fake-a"), ScriptedChat("fake-b", family="fake-b")],
            ScriptedJudge("fake-judge", family="fake-judge"),
        )
    ids = [m.strip() for m in models.split(",")] if models else settings.model_ids()
    judge_id = judge or settings.kupuna_judge
    chats = [chat_for(m, settings, max_tokens=max_tokens) for m in ids]
    return chats, LLMJudge(chat_for(judge_id, settings, max_tokens=max_tokens), rubric)


def _golden_meta() -> tuple[Gate, bool]:
    if not GOLDEN.is_file():
        return PLUMBING_GATE, False
    meta = json.loads(GOLDEN.read_text(encoding="utf-8")).get("_meta", {})
    gate = load_gate_from_meta(meta) if isinstance(meta.get("thresholds"), dict) else PLUMBING_GATE
    return gate, bool(meta.get("promoted"))


def _code_sha() -> str | None:
    try:
        command = ["git", "rev-parse", "HEAD"]
        out = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if len(sha) == 40 else None


def _package_version() -> str:
    try:
        return importlib.metadata.version("kupuna-bench")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def build_manifest(
    paths: RunPaths,
    *,
    driver: str,
    chats: Sequence[Chat],
    the_judge: Judge,
    rubric: Rubric,
    rubric_path: Path | None,
    system_prompt: str | None,
    runs: int,
    allow_draft: bool,
    spend_cap_usd: float | None,
    scenarios_dir: Path,
    selected: Sequence[Scenario],
    source_run: str | None = None,
) -> Manifest:
    """Everything a reader needs to reconstruct the run, written before the first call (ADR-012)."""
    judge_chat = the_judge.chat if isinstance(the_judge, LLMJudge) else None
    return Manifest(
        run_id=paths.run_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        driver=driver,
        code_sha=_code_sha(),
        package_version=_package_version(),
        python_version=platform.python_version(),
        system_prompt=system_prompt,
        rubric_path=str(rubric_path or DEFAULT_RUBRIC_PATH),
        rubric_sha256=rubric_sha256(rubric_path),
        rubric=rubric,
        judge_instructions=rubric.judge_instructions(),
        judge=ModelRef(name=the_judge.name, family=the_judge.family),
        judge_adapter=judge_chat.spec() if judge_chat is not None else None,
        models=tuple(ModelRef(name=c.name, family=c.family) for c in chats),
        adapters=tuple(c.spec() for c in chats),
        runs=runs,
        allow_draft=allow_draft,
        spend_cap_usd=spend_cap_usd,
        variant_order="counterbalanced",
        scenarios_dir=str(scenarios_dir),
        dataset_sha256=dataset_sha256(selected),
        scenario_ids=tuple(s.id for s in selected),
        source_run=source_run,
    )


def write_outputs(
    result: RunResult,
    paths: RunPaths,
    *,
    gate_name: str,
    verdict: str,
    shortfalls: list[str],
    driver: str,
    draft: bool,
) -> tuple[Path, Path]:
    """The run id was claimed by `allocate_run` before the first call (ADR-012); this only writes."""
    if paths.record.exists():
        raise FileExistsError(paths.record)
    write_json_atomic(paths.json_path, result.model_dump_json(indent=1))
    facts = facts_from_result(
        result,
        gate_name=gate_name,
        verdict=verdict,
        shortfalls=shortfalls,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        driver=driver,
        draft=draft,
        run_id=result.run_id,
        code_sha=result.manifest.code_sha if result.manifest is not None else None,
        manifest=str(paths.dir / "manifest.json"),
    )
    write_record(facts, paths.record.parent, path=paths.record)
    return paths.record, paths.json_path


def _resume_paths(resume: Path, out_dir: Path) -> RunPaths:
    """A resumed run lives where it was claimed: `--out` must be the directory that holds `resume`."""
    if resume.resolve().parent != out_dir.resolve():
        holder = resume.resolve().parent
        typer.echo(f"cannot resume {resume}: --out must be {holder}, the directory that holds it")
        raise typer.Exit(code=2)
    paths = RunPaths(
        run_id=resume.name,
        dir=resume,
        record=out_dir / f"{resume.name}.md",
        json_path=out_dir / f"{resume.name}.json",
    )
    for artifact in (paths.record, paths.json_path):
        if artifact.exists():
            typer.echo(f"cannot resume {resume}: {artifact} already exists, so this run already completed")
            raise typer.Exit(code=2)
    return paths


def _resume_conflicts(
    manifest: Manifest,
    *,
    runs: int,
    allow_draft: bool,
    system_prompt: str | None,
    chats: Sequence[Chat],
    the_judge: Judge,
    rubric_path: Path | None,
) -> list[str]:
    """What the manifest recorded must be what the resumed run uses, or the record would lie."""
    current = {
        "runs": (manifest.runs, runs),
        "allow_draft": (manifest.allow_draft, allow_draft),
        "system_prompt": (manifest.system_prompt, system_prompt),
        "models": ([m.name for m in manifest.models], [c.name for c in chats]),
        "judge": (manifest.judge.name, the_judge.name),
        "rubric_sha256": (manifest.rubric_sha256, rubric_sha256(rubric_path)),
    }
    return [f"{name} (manifest {was!r}, now {now!r})" for name, (was, now) in current.items() if was != now]


def _journaled_rows(journal_path: Path) -> list[Row]:
    """Every complete line; a torn last line (an interrupted write) is dropped with a notice."""
    if not journal_path.is_file():
        return []
    lines = [line for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows: list[Row] = []
    for index, line in enumerate(lines):
        try:
            rows.append(Row.model_validate_json(line))
        except ValueError as exc:
            if index == len(lines) - 1:
                typer.echo("dropping a partial last journal line (an interrupted write)")
                continue
            typer.echo(f"cannot resume: journal line {index + 1} is not a row: {exc}")
            raise typer.Exit(code=2) from None
    return rows


def _rubric(path: Path | None) -> Rubric:
    try:
        return load_rubric(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        typer.echo(f"cannot load rubric {path or DEFAULT_RUBRIC_PATH}: {exc}")
        raise typer.Exit(code=2) from None


def _load(scenarios_dir: Path) -> list[Scenario]:
    try:
        return load_scenarios(scenarios_dir)
    except ScenarioError as exc:
        for message in exc.messages:
            typer.echo(message)
        raise typer.Exit(code=2) from None


def _finish(result: RunResult, paths: RunPaths, *, n_scenarios: int, driver: str, fake: bool) -> None:
    try:
        gate, promoted = _golden_meta()
    except (OSError, ValueError) as exc:
        typer.echo(f"golden file is invalid: {exc}")
        raise typer.Exit(code=2) from None
    gate_name = "PLUMBING_GATE" if fake or not promoted else "golden"
    metrics = gate_metrics(result, n_scenarios=n_scenarios)
    ok, shortfalls = check_gate(metrics, PLUMBING_GATE if gate_name == "PLUMBING_GATE" else gate)
    try:
        record_path, json_path = write_outputs(
            result,
            paths,
            gate_name=gate_name,
            verdict="PASS" if ok else "FAIL",
            shortfalls=shortfalls,
            driver=driver,
            draft=(not promoted) or result.allow_draft,
        )
    except FileExistsError as exc:
        typer.echo(f"record already exists, this run was already completed: {exc}")
        raise typer.Exit(code=2) from None
    typer.echo(result.summary().table())
    typer.echo(f"record: {record_path}\njson: {json_path}\nmanifest: {paths.dir / 'manifest.json'}")
    typer.echo(f"verdict: {'PASS' if ok else 'FAIL'}")
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
    fixtures = sum(1 for s in loaded if s.fixture)
    suffix = f"; {fixtures} fixture, never reported" if fixtures else ""
    typer.echo(f"OK: {len(loaded)} scenarios ({promoted} promoted, {len(loaded) - promoted} draft{suffix})")
    for scenario in loaded:
        for warning in key_warnings(scenario):
            typer.echo(f"warning: {warning}")


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
    resume: Annotated[
        Path | None, typer.Option(help="A results/run-<id> directory with manifest.json and journal.jsonl")
    ] = None,
    max_tokens: Annotated[
        int, typer.Option(min=1, help="Token limit per reply; a cut-off reply is retried once at double")
    ] = DEFAULT_MAX_TOKENS,
    rubric_path: Annotated[
        Path | None,
        typer.Option("--rubric", help="Rubric YAML (default: the packaged copy of docs/rubric.yaml)"),
    ] = None,
) -> None:
    """Run the benchmark and write an append-only record plus JSON."""
    settings = Settings()
    rubric = _rubric(rubric_path)
    scenarios_dir = scenarios or Path(settings.kupuna_scenarios)
    out_dir = out or Path(settings.kupuna_results)
    loaded = _load(scenarios_dir)
    try:
        chats, the_judge = roster(
            settings, models=models, judge=judge, fake=fake, rubric=rubric, max_tokens=max_tokens
        )
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    cap = 0.0 if fake else (spend_cap if spend_cap is not None else settings.kupuna_spend_cap_usd)
    selected = [s for s in loaded if allow_draft or s.status == "promoted"]
    completed: list[Row] = []
    if resume is not None:
        paths = _resume_paths(resume, out_dir)
        try:
            manifest = Manifest.model_validate_json((resume / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            typer.echo(f"cannot resume {resume}: {exc}")
            raise typer.Exit(code=2) from None
        if manifest.dataset_sha256 != dataset_sha256(selected):
            typer.echo(f"cannot resume {resume}: the selected scenarios differ from the manifest's dataset")
            raise typer.Exit(code=2)
        conflicts = _resume_conflicts(
            manifest,
            runs=runs,
            allow_draft=allow_draft,
            system_prompt=system_prompt,
            chats=chats,
            the_judge=the_judge,
            rubric_path=rubric_path,
        )
        if conflicts:
            joined = "; ".join(conflicts)
            typer.echo(f"cannot resume {resume}: these options differ from the manifest: {joined}")
            raise typer.Exit(code=2)
        completed = _journaled_rows(resume / "journal.jsonl")
        typer.echo(f"resuming {paths.run_id}: {len(completed)} cells already journaled")
    else:
        paths = allocate_run(out_dir)
        manifest = build_manifest(
            paths,
            driver="kupuna-bench run",
            chats=chats,
            the_judge=the_judge,
            rubric=rubric,
            rubric_path=rubric_path,
            system_prompt=system_prompt,
            runs=runs,
            allow_draft=allow_draft,
            spend_cap_usd=None if fake else cap,
            scenarios_dir=scenarios_dir,
            selected=selected,
        )
        write_json_atomic(paths.dir / "manifest.json", manifest.model_dump_json(indent=1))
    with (paths.dir / "journal.jsonl").open("a", encoding="utf-8") as journal:

        def on_row(row: Row) -> None:
            journal.write(row.model_dump_json() + "\n")
            journal.flush()
            suffix = f" ERROR {row.error.stage}" if row.error else ""
            typer.echo(f"row {row.scenario_id}/{row.variant}/{row.model}/{row.run_index}{suffix}")

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
                on_row=on_row,
                manifest=manifest,
                completed=completed,
            )
        except (JudgeFamilyConflict, NothingToRun) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=2) from None
    n_scenarios = len(selected)
    _finish(result, paths, n_scenarios=n_scenarios, driver="kupuna-bench run", fake=fake)


@app.command()
def regrade(
    result_json: Annotated[Path, typer.Argument(help="A results JSON written by `run`")],
    fake: Annotated[bool, typer.Option()] = False,
    scenarios: Annotated[Path | None, typer.Option()] = None,
    judge: Annotated[str | None, typer.Option(help="Judge model id")] = None,
    out: Annotated[Path | None, typer.Option()] = None,
    max_tokens: Annotated[int, typer.Option(min=1, help="Token limit per judge reply")] = DEFAULT_MAX_TOKENS,
    rubric_path: Annotated[
        Path | None,
        typer.Option("--rubric", help="Rubric YAML (default: the packaged copy of docs/rubric.yaml)"),
    ] = None,
) -> None:
    """Re-judge the kept transcripts of a previous run with a different judge."""
    settings = Settings()
    rubric = _rubric(rubric_path)
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
            else LLMJudge(chat_for(judge or settings.kupuna_judge, settings, max_tokens=max_tokens), rubric)
        )
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    out_dir = out or Path(settings.kupuna_results)
    by_id = {s.id: s for s in loaded}
    selected = [by_id[i] for i in sorted({row.scenario_id for row in previous.rows}) if i in by_id]
    paths = allocate_run(out_dir)
    manifest = build_manifest(
        paths,
        driver="kupuna-bench regrade",
        chats=[],
        the_judge=the_judge,
        rubric=rubric,
        rubric_path=rubric_path,
        system_prompt=previous.manifest.system_prompt if previous.manifest is not None else None,
        runs=previous.runs,
        allow_draft=previous.allow_draft,
        spend_cap_usd=None,
        scenarios_dir=scenarios or Path(settings.kupuna_scenarios),
        selected=selected,
        source_run=result_json.stem,
    ).model_copy(update={"models": previous.models, "adapters": ()})
    write_json_atomic(paths.dir / "manifest.json", manifest.model_dump_json(indent=1))
    try:
        result = _regrade(
            previous, loaded, the_judge, rubric=rubric, source_run=result_json.stem, manifest=manifest
        )
    except (JudgeFamilyConflict, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    n_scenarios = len({row.scenario_id for row in result.rows})
    _finish(result, paths, n_scenarios=n_scenarios, driver="kupuna-bench regrade", fake=fake)


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
    typer.echo(
        f"coverage: {_fmt_overlap(coding.coverage)} of incident passes coded "
        f"({coding.uncodeable} marked uncodeable)"
    )
    if report.human_overlap is None:
        typer.echo("human comparator: none (a lexical diagnostic, not conceptual agreement; docs/method.md)")
    else:
        typer.echo(
            f"human comparator: {report.human_overlap:.2f} of {report.human_codes} blind human "
            f"codes matched ({report.human_match_rule})"
        )


@app.command()
def agreement(
    labels: Annotated[list[Path], typer.Argument(help="Human label CSV files")],
    result: Annotated[Path, typer.Option(help="Results JSON whose judge verdicts join the comparison")],
    out: Annotated[Path | None, typer.Option()] = None,
    min_kappa: Annotated[
        float, typer.Option(help="Calibration bar on severity κ and direction κ, judge vs each human")
    ] = 0.70,
    key: Annotated[
        Path | None, typer.Option(help="KEY-<run>.json written by scripts/make_label_templates.py")
    ] = None,
    rubric_path: Annotated[
        Path | None,
        typer.Option("--rubric", help="Rubric YAML (default: the packaged copy of docs/rubric.yaml)"),
    ] = None,
) -> None:
    """Human–human and judge–human agreement on severity, pass/fail, direction, and transcript outcomes."""
    settings = Settings()
    rubric = _rubric(rubric_path)
    try:
        previous = RunResult.model_validate(json.loads(result.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load {result}: {exc}")
        raise typer.Exit(code=2) from None
    try:
        key_map: dict[str, str] = json.loads(key.read_text(encoding="utf-8")) if key is not None else {}
        human_labels = decode_items(load_labels(labels), key_map)
        check_label_directions(human_labels, rubric)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    all_labels = human_labels + judge_labels(previous)
    try:
        report = _agreement(all_labels, pass_max_severity=previous.pass_max_severity)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None
    out_dir = out or Path(settings.kupuna_results)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.stem}-agreement.json"
    path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    typer.echo(report.table())
    ok, reasons = report.calibrated(min_kappa)
    verdict = "yes" if ok else "no"
    typer.echo(f"calibration (severity κ and direction κ >= {min_kappa:.2f}, judge vs each human): {verdict}")
    for reason in reasons:
        typer.echo(f"  - {reason}")
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
    title = f"KŪPUNA-AI Bench {result_json.stem}"
    if previous.fixture_scenarios or previous.allow_draft:
        title += " (draft: fixture or draft scenarios, never reported)"
    target.write_text(render_chart(previous.summary(), title=title), encoding="utf-8")
    typer.echo(f"chart: {target}")
