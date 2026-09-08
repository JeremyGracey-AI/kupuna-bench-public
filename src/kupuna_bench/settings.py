"""Environment-backed settings. Keys and rosters are read here and in cli.py only."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    kupuna_models: str = (
        "anthropic/claude-sonnet-4.6,openai/gpt-5,google/gemini-2.5-pro,meta-llama/llama-4-maverick"
    )
    kupuna_judge: str = "mistralai/mistral-large-2512"
    kupuna_coders: str = "mistralai/mistral-large-2512,openai/gpt-5,google/gemini-2.5-pro"
    kupuna_spend_cap_usd: float = 40.0
    kupuna_scenarios: str = "scenarios/v0"
    kupuna_results: str = "results"

    def model_ids(self) -> list[str]:
        return [item.strip() for item in self.kupuna_models.split(",") if item.strip()]

    def coder_ids(self) -> list[str]:
        return [item.strip() for item in self.kupuna_coders.split(",") if item.strip()]
