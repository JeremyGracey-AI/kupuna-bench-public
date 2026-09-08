"""The Chat seam: one protocol, three adapters.

Production adapters never raise. A failed call returns Reply(ok=False, error=...), so one
dead model cannot abort a run; the runner turns it into a row. Retries cover only transient
statuses (408, 429, 5xx), lifted from llm-council-mcp's OpenRouter client.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, TypedDict, cast, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict

RETRY_STATUSES: tuple[int, ...] = (408, 429, 500, 502, 503, 504)


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None

    def __add__(self, other: Usage) -> Usage:
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd + other.cost_usd
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=cost,
        )

    def __sub__(self, other: Usage) -> Usage:
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd - other.cost_usd
        return Usage(
            input_tokens=self.input_tokens - other.input_tokens,
            output_tokens=self.output_tokens - other.output_tokens,
            cost_usd=cost,
        )


class Reply(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    text: str = ""
    usage: Usage = Usage()
    error: str | None = None


@runtime_checkable
class Chat(Protocol):
    name: str
    family: str

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply: ...


def family_of(model_id: str) -> str:
    """Vendor prefix of an OpenRouter id; a bare id is a direct Anthropic model."""
    return model_id.split("/", 1)[0] if "/" in model_id else "anthropic"


def _last_user(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


class ScriptedChat:
    """Deterministic adapter for tests and keyless CI."""

    def __init__(
        self,
        name: str = "scripted",
        family: str = "scripted",
        *,
        responder: Callable[[Sequence[Message]], str] | None = None,
        fail_when: Callable[[Sequence[Message]], str | None] | None = None,
    ) -> None:
        self.name = name
        self.family = family
        self._responder = responder
        self._fail_when = fail_when

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
        if self._fail_when is not None:
            error = self._fail_when(messages)
            if error:
                return Reply(ok=False, error=error)
        text = (
            self._responder(messages)
            if self._responder
            else f"[{self.name}] reply to: {_last_user(messages)}"
        )
        tokens_in = sum(len(m["content"].split()) for m in messages)
        return Reply(
            ok=True,
            text=text,
            usage=Usage(
                input_tokens=tokens_in, output_tokens=len(text.split()), cost_usd=0.0
            ),
        )


def _post_with_retries(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    max_retries: int,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (json_body, None) on success or (None, error) after retries. Never raises."""
    last_error = "unknown error"
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.post(url, headers=headers, json=payload)
            if response.status_code in RETRY_STATUSES:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            elif response.status_code >= 400:
                return None, f"HTTP {response.status_code}: {response.text[:300]}"
            else:
                return cast(dict[str, Any], response.json()), None
        except Exception as exc:  # noqa: BLE001 - every failure mode becomes data
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < max_retries:
            sleep(1.5 * (attempt + 1))
    return None, last_error


class OpenRouterChat:
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        family: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = model
        self.family = family or family_of(model)
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
        payload: dict[str, Any] = {"model": self.name, "messages": [dict(m) for m in messages]}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/JeremyGracey-AI/kupuna-bench",
            "X-Title": "kupuna-bench",
        }
        body, error = _post_with_retries(
            self.URL,
            headers=headers,
            payload=payload,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
            sleep=self._sleep,
        )
        if body is None:
            return Reply(ok=False, error=error)
        try:
            message = cast(dict[str, Any], cast(list[Any], body["choices"])[0]["message"])
            usage = cast(dict[str, Any], body.get("usage") or {})
            cost = usage.get("cost")
            return Reply(
                ok=True,
                text=str(message.get("content") or ""),
                usage=Usage(
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or 0),
                    cost_usd=float(cost) if cost is not None else None,
                ),
            )
        except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
            return Reply(ok=False, error=f"unexpected response shape: {type(exc).__name__}: {exc}")


class AnthropicChat:
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        timeout: float = 120.0,
        max_retries: int = 2,
        max_tokens: int = 1024,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = model
        self.family = "anthropic"
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._transport = transport
        self._sleep = sleep

    def complete(self, messages: Sequence[Message], *, json_mode: bool = False) -> Reply:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        if json_mode:
            system_parts.append("Respond with a single JSON object and nothing else.")
        payload: dict[str, Any] = {
            "model": self.name,
            "max_tokens": self._max_tokens,
            "messages": [dict(m) for m in messages if m["role"] != "system"],
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body, error = _post_with_retries(
            self.URL,
            headers=headers,
            payload=payload,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
            sleep=self._sleep,
        )
        if body is None:
            return Reply(ok=False, error=error)
        try:
            blocks = cast(list[dict[str, Any]], body.get("content") or [])
            text = "".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
            usage = cast(dict[str, Any], body.get("usage") or {})
            return Reply(
                ok=True,
                text=text,
                usage=Usage(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                ),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return Reply(ok=False, error=f"unexpected response shape: {type(exc).__name__}: {exc}")
