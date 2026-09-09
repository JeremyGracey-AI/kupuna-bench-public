"""The experiment manifest: what ran, with what, under which policy (ADR-012).

Written before the first paid call and embedded in the result, so a record can be reconstructed
from the manifest and the per-cell journal alone (review finding 5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from kupuna_bench.rubric import Rubric


class ModelRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    family: str


class AdapterSpec(BaseModel):
    """How a model was called: provider, token limit, timeout, retries, truncation retry."""

    model_config = ConfigDict(frozen=True)

    name: str
    provider: Literal["openrouter", "anthropic", "scripted"]
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    truncation_retry: int = 0


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_version: int = 1
    run_id: str
    created_at: str
    driver: str
    code_sha: str | None
    package_version: str
    python_version: str
    system_prompt: str | None
    rubric_path: str
    rubric_sha256: str
    rubric: Rubric
    judge_instructions: str
    judge_context: str = "prefix"
    judge: ModelRef
    judge_adapter: AdapterSpec | None = None
    models: tuple[ModelRef, ...]
    adapters: tuple[AdapterSpec, ...]
    runs: int
    allow_draft: bool
    spend_cap_usd: float | None
    variant_order: str
    scenarios_dir: str
    dataset_sha256: str
    scenario_ids: tuple[str, ...]
    source_run: str | None = None
