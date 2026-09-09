"""Results JSON written before the 2026-09-09 review response must keep loading: regrade depends on it."""

import json
from pathlib import Path

from kupuna_bench.run import RunResult

FIXTURE = Path(__file__).parent / "fixtures" / "results" / "run-schema-v1.json"


def test_v1_results_json_still_loads_and_summarizes() -> None:
    result = RunResult.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert len(result.rows) == 2 and result.summary().total == 2 and result.summary().graded == 1
    assert result.summary().errors == {"chat": 1}
    # Every field added after v1 has a default, so a v1 record re-serializes and reloads unchanged.
    assert RunResult.model_validate_json(result.model_dump_json()) == result
