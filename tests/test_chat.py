import json
from collections.abc import Sequence

import httpx

from kupuna_bench.chat import (
    AnthropicChat,
    Chat,
    Message,
    OpenRouterChat,
    Reply,
    ScriptedChat,
    Usage,
    family_of,
)


def _messages(text: str) -> list[Message]:
    return [{"role": "user", "content": text}]


def test_family_of_uses_vendor_prefix_or_anthropic() -> None:
    assert family_of("openai/gpt-5.1") == "openai"
    assert family_of("mistralai/mistral-large") == "mistralai"
    assert family_of("claude-sonnet-4-5") == "anthropic"


def test_scripted_chat_echoes_by_default_and_satisfies_protocol() -> None:
    chat = ScriptedChat("a", family="scripted-a")
    assert isinstance(chat, Chat)
    reply = chat.complete(_messages("hello"))
    assert reply.ok and "hello" in reply.text
    assert reply.usage.cost_usd == 0.0


def test_scripted_chat_fail_when_returns_error_reply() -> None:
    chat = ScriptedChat("a", fail_when=lambda m: "boom" if "fail" in m[-1]["content"] else None)
    assert chat.complete(_messages("ok")).ok
    reply = chat.complete(_messages("please fail"))
    assert reply == Reply(ok=False, error="boom")


def test_usage_adds() -> None:
    total = Usage(input_tokens=1, output_tokens=2, cost_usd=0.5) + Usage(
        input_tokens=3, output_tokens=4, cost_usd=None
    )
    assert total == Usage(input_tokens=4, output_tokens=6, cost_usd=None)
    assert (Usage(cost_usd=0.1) + Usage(cost_usd=0.2)).cost_usd == 0.30000000000000004


def _openrouter_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def _ok_body(text: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }


def test_openrouter_success_parses_text_and_usage() -> None:
    transport = _openrouter_transport([httpx.Response(200, json=_ok_body("hi"))])
    chat = OpenRouterChat("openai/gpt-5.1", api_key="k", transport=transport, sleep=lambda s: None)
    reply = chat.complete(_messages("x"), json_mode=True)
    assert reply == Reply(ok=True, text="hi", usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.001))
    sent = json.loads(transport.calls[0].content)  # type: ignore[attr-defined]
    assert sent["response_format"] == {"type": "json_object"}
    assert transport.calls[0].headers["authorization"] == "Bearer k"  # type: ignore[attr-defined]
    assert chat.family == "openai"


def test_openrouter_retries_transient_then_succeeds() -> None:
    transport = _openrouter_transport(
        [httpx.Response(429, text="slow down"), httpx.Response(200, json=_ok_body("ok"))]
    )
    slept: list[float] = []
    chat = OpenRouterChat("openai/gpt-5.1", api_key="k", transport=transport, sleep=slept.append)
    reply = chat.complete(_messages("x"))
    assert reply.ok and reply.text == "ok"
    assert len(transport.calls) == 2 and slept == [1.5]  # type: ignore[attr-defined]


def test_openrouter_does_not_retry_client_error() -> None:
    transport = _openrouter_transport([httpx.Response(400, text="bad request")])
    chat = OpenRouterChat("openai/gpt-5.1", api_key="k", transport=transport, sleep=lambda s: None)
    reply = chat.complete(_messages("x"))
    assert not reply.ok and reply.error is not None and reply.error.startswith("HTTP 400")
    assert len(transport.calls) == 1  # type: ignore[attr-defined]


def test_openrouter_gives_up_after_retries_without_raising() -> None:
    transport = _openrouter_transport([httpx.Response(503, text="down")])
    chat = OpenRouterChat(
        "openai/gpt-5.1", api_key="k", max_retries=1, transport=transport, sleep=lambda s: None
    )
    reply = chat.complete(_messages("x"))
    assert reply == Reply(ok=False, error="HTTP 503: down")
    assert len(transport.calls) == 2  # type: ignore[attr-defined]


def test_openrouter_bad_shape_returns_error_reply() -> None:
    transport = _openrouter_transport([httpx.Response(200, json=_ok_body("x") | {"usage": "n/a"})])
    chat = OpenRouterChat("openai/gpt-5.1", api_key="k", transport=transport, sleep=lambda s: None)
    reply = chat.complete(_messages("x"))
    assert not reply.ok and reply.error is not None and reply.error.startswith("unexpected response shape")


def test_anthropic_bad_shape_returns_error_reply() -> None:
    transport = _openrouter_transport([httpx.Response(200, json={"content": "oops", "usage": {}})])
    chat = AnthropicChat("claude-sonnet-4-5", api_key="k", transport=transport, sleep=lambda s: None)
    reply = chat.complete(_messages("x"))
    assert not reply.ok and reply.error is not None and reply.error.startswith("unexpected response shape")


def test_anthropic_json_mode_appends_instruction() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})

    chat = AnthropicChat(
        "claude-sonnet-4-5", api_key="k", transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    messages: Sequence[Message] = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "x"},
    ]
    chat.complete(messages, json_mode=True)
    sent = json.loads(captured[0].content)
    assert sent["system"] == "be brief\nRespond with a single JSON object and nothing else."


def test_anthropic_success_moves_system_and_parses_blocks() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    chat = AnthropicChat(
        "claude-sonnet-4-5",
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )
    messages: Sequence[Message] = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "x"},
    ]
    reply = chat.complete(messages)
    assert reply == Reply(ok=True, text="ab", usage=Usage(input_tokens=7, output_tokens=3, cost_usd=None))
    sent = json.loads(captured[0].content)
    assert sent["system"] == "be brief" and sent["messages"] == [{"role": "user", "content": "x"}]
    assert captured[0].headers["x-api-key"] == "k" and chat.family == "anthropic"
