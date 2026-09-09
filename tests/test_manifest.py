from kupuna_bench.chat import ScriptedChat
from kupuna_bench.manifest import AdapterSpec, Manifest, ModelRef
from kupuna_bench.rubric import load_rubric


def test_manifest_round_trips_and_names_the_composition() -> None:
    rubric = load_rubric()
    manifest = Manifest(
        run_id="run-2026-09-09-1",
        created_at="2026-09-09T00:00:00+00:00",
        driver="pytest",
        code_sha="abc",
        package_version="0.1.1",
        python_version="3.12.0",
        system_prompt=None,
        rubric_path="docs/rubric.yaml",
        rubric_sha256="0" * 64,
        rubric=rubric,
        judge_instructions=rubric.judge_instructions(),
        judge=ModelRef(name="j", family="j"),
        models=(ModelRef(name="a", family="a"),),
        adapters=(ScriptedChat("a", family="a").spec(),),
        runs=1,
        allow_draft=True,
        spend_cap_usd=None,
        variant_order="counterbalanced",
        scenarios_dir="tests/fixtures/scenarios",
        dataset_sha256="d",
        scenario_ids=("x",),
    )
    assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.adapters[0] == AdapterSpec(name="a", provider="scripted")
    assert manifest.judge_context == "prefix" and manifest.rubric.version == rubric.version
    assert manifest.manifest_version == 1 and manifest.source_run is None
