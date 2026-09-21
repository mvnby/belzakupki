from __future__ import annotations

import json

import httpx
import pytest

from worker.analyzer import ai_providers


class FakeResponse:
    def __init__(self, body: bytes = b"", status_code: int = 200):
        self.body = body
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.invalid/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def iter_bytes(self):
        yield self.body


class FakeClient:
    def __init__(self, outcomes, calls, **_kwargs):
        self.outcomes = outcomes
        self.calls = calls
        self.timeout = _kwargs["timeout"]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, method, url, *, json, headers):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": json,
                "headers": headers,
                "timeout": self.timeout,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response_for(analysis: dict) -> FakeResponse:
    body = {"choices": [{"message": {"content": json.dumps(analysis)}}]}
    return FakeResponse(json.dumps(body).encode())


@pytest.fixture(autouse=True)
def clear_provider_environment(monkeypatch):
    for name in (
        "AI_PROVIDER_ORDER",
        "DEEPSEEK_TOKEN",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "QWEN_MODEL",
        "ZAI_API_KEY",
        "ZAI_BASE_URL",
        "ZAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def use_client(monkeypatch, outcomes):
    calls = []
    monkeypatch.setattr(
        ai_providers.httpx,
        "Client",
        lambda **kwargs: FakeClient(outcomes, calls, **kwargs),
    )
    return calls


def configure_deepseek_and_qwen(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_ORDER", "deepseek,qwen")
    monkeypatch.setenv("DEEPSEEK_TOKEN", "deepseek-key")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://workspace.example/compatible-mode/v1")


@pytest.mark.parametrize("status_code", [401, 429, 400, 404])
def test_http_failure_uses_next_configured_provider(monkeypatch, status_code):
    configure_deepseek_and_qwen(monkeypatch)
    calls = use_client(monkeypatch, [FakeResponse(status_code=status_code), response_for({"relevant": True})])

    analysis = ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=30)

    assert analysis == {"relevant": True, "provider": "qwen", "model": "qwen3.5-flash-2026-02-23"}
    assert [call["url"] for call in calls] == [
        "https://api.deepseek.com/chat/completions",
        "https://workspace.example/compatible-mode/v1/chat/completions",
    ]
    assert calls[1]["payload"]["enable_thinking"] is False
    assert calls[1]["payload"]["response_format"] == {"type": "json_object"}
    assert calls[0]["payload"]["thinking"] == {"type": "disabled"}
    assert calls[0]["payload"]["max_tokens"] == ai_providers.MAX_OUTPUT_TOKENS


def test_timeout_uses_next_configured_provider(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    timeout = httpx.ReadTimeout("timed out", request=httpx.Request("POST", "https://provider.invalid"))
    calls = use_client(monkeypatch, [timeout, response_for({"relevant": True})])

    assert ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=30)["provider"] == "qwen"
    assert len(calls) == 2


@pytest.mark.parametrize("first_response", [FakeResponse(b"not json"), response_for({"relevant": "yes"})])
def test_malformed_or_invalid_schema_uses_next_provider(monkeypatch, first_response):
    configure_deepseek_and_qwen(monkeypatch)
    calls = use_client(monkeypatch, [first_response, response_for({"relevant": True})])

    assert ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=30)["provider"] == "qwen"
    assert len(calls) == 2


def test_all_provider_failures_leave_analysis_pending(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    calls = use_client(monkeypatch, [FakeResponse(status_code=401), FakeResponse(status_code=503)])

    assert ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=30) is None
    assert len(calls) == 2


def test_valid_negative_response_does_not_use_fallback(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    calls = use_client(monkeypatch, [response_for({"relevant": False, "explanation": "not suitable"})])

    analysis = ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=30)

    assert analysis["relevant"] is False
    assert analysis["provider"] == "deepseek"
    assert len(calls) == 1


def test_explicit_tenant_key_never_falls_back_to_system_credentials(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    calls = use_client(monkeypatch, [FakeResponse(status_code=401), response_for({"relevant": True})])

    assert ai_providers.analyze_json(
        [{"role": "user", "content": "test"}],
        timeout=30,
        api_key="tenant-owned-key",
    ) is None
    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer tenant-owned-key"


def test_provider_order_is_known_and_unique(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_ORDER", "qwen,unknown,qwen,deepseek,zai,deepseek")
    monkeypatch.setenv("DEEPSEEK_TOKEN", "deepseek-key")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://workspace.example/compatible-mode/v1")
    monkeypatch.setenv("ZAI_API_KEY", "zai-key")

    providers = ai_providers.configured_providers()

    assert [provider.name for provider in providers] == ["qwen", "deepseek", "zai"]
    assert "zai-key" not in repr(providers[-1])


@pytest.mark.parametrize(
    "base_url",
    [
        "http://workspace.example/compatible-mode/v1",
        "https://user:pass@workspace.example/compatible-mode/v1",
        "https://workspace.example/compatible-mode/v1?debug=true",
        "https://workspace.example/compatible-mode/v1#fragment",
        "https://:443/compatible-mode/v1",
        "https://[invalid",
    ],
)
def test_provider_url_must_be_plain_https(monkeypatch, base_url):
    monkeypatch.setenv("AI_PROVIDER_ORDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv("QWEN_BASE_URL", base_url)

    assert ai_providers.configured_providers() == ()


def test_stage_deadline_shares_remaining_time_between_unique_providers(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_ORDER", "deepseek,qwen,zai,deepseek")
    monkeypatch.setenv("ZAI_API_KEY", "zai-key")
    monkeypatch.setattr(ai_providers.time, "monotonic", lambda: 0.0)
    calls = use_client(
        monkeypatch,
        [FakeResponse(status_code=401), FakeResponse(status_code=401), response_for({"relevant": True})],
    )

    analysis = ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=60)

    assert analysis["provider"] == "zai"
    assert [call["timeout"] for call in calls] == [20.0, 30.0, 60.0]


def test_stage_deadline_is_checked_while_streaming_response(monkeypatch):
    configure_deepseek_and_qwen(monkeypatch)
    ticks = iter([0.0, 0.0, 60.0, 60.0])
    monkeypatch.setattr(ai_providers.time, "monotonic", lambda: next(ticks))
    calls = use_client(monkeypatch, [response_for({"relevant": True}), response_for({"relevant": True})])

    assert ai_providers.analyze_json([{"role": "user", "content": "test"}], timeout=60) is None
    assert len(calls) == 1
