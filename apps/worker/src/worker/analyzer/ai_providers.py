"""Bounded OpenAI-compatible provider fallback for worker AI analysis."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

import httpx
from loguru import logger


MAX_TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 1_000_000
DEFAULT_PROVIDER_ORDER = ("deepseek", "qwen", "zai")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    extra_payload: dict[str, Any]

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


class ProviderFailure(Exception):
    def __init__(self, error_class: str, status_code: int | None = None):
        self.error_class = error_class
        self.status_code = status_code


def _configured(value: str | None) -> bool:
    return bool(value and value.strip() and not value.startswith("your-"))


def _provider_order() -> tuple[str, ...]:
    configured = os.getenv("AI_PROVIDER_ORDER", ",".join(DEFAULT_PROVIDER_ORDER))
    names = tuple(name.strip().lower() for name in configured.split(",") if name.strip())
    return names or DEFAULT_PROVIDER_ORDER


def _system_provider(name: str) -> ProviderConfig | None:
    if name == "deepseek":
        token = os.getenv("DEEPSEEK_TOKEN")
        if _configured(token):
            return ProviderConfig(
                name="deepseek",
                api_key=token,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                extra_payload={"thinking": {"type": "disabled"}},
            )
    elif name == "qwen":
        token = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL")
        if _configured(token) and _configured(base_url):
            return ProviderConfig(
                name="qwen",
                api_key=token,
                base_url=base_url,
                model=os.getenv("QWEN_MODEL", "qwen3.5-flash-2026-02-23"),
                extra_payload={"enable_thinking": False},
            )
    elif name == "zai":
        token = os.getenv("ZAI_API_KEY")
        if _configured(token):
            return ProviderConfig(
                name="zai",
                api_key=token,
                base_url=os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"),
                model=os.getenv("ZAI_MODEL", "glm-4.7-flash"),
                extra_payload={"thinking": {"type": "disabled"}},
            )
    return None


def configured_providers(api_key: str | None = None) -> tuple[ProviderConfig, ...]:
    """Return enabled providers, or only the caller's explicit DeepSeek key.

    An explicit key is tenant-owned. It must never authorize a fallback to
    shared system credentials.
    """
    if api_key is not None:
        if not _configured(api_key):
            return ()
        return (
            ProviderConfig(
                name="deepseek",
                api_key=api_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                extra_payload={"thinking": {"type": "disabled"}},
            ),
        )

    providers: list[ProviderConfig] = []
    for name in _provider_order():
        provider = _system_provider(name)
        if provider is not None:
            providers.append(provider)
    return tuple(providers)


def is_ai_provider_configured() -> bool:
    return bool(configured_providers())


def _read_response(response: httpx.Response) -> bytes:
    response.raise_for_status()
    payload = bytearray()
    for chunk in response.iter_bytes():
        payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("ResponseTooLarge")
    return bytes(payload)


def _post_json(provider: ProviderConfig, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=min(max(timeout, 1), MAX_TIMEOUT_SECONDS)) as client:
            with client.stream(
                "POST",
                provider.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                raw = _read_response(response)
    except ProviderFailure:
        raise
    except httpx.HTTPStatusError as exc:
        raise ProviderFailure(type(exc).__name__, exc.response.status_code) from exc
    except httpx.RequestError as exc:
        raise ProviderFailure(type(exc).__name__) from exc

    try:
        result = json.loads(raw)
        content = result["choices"][0]["message"]["content"]
        analysis = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        raise ProviderFailure(type(exc).__name__) from exc
    if not isinstance(analysis, dict) or type(analysis.get("relevant")) is not bool:
        raise ProviderFailure("InvalidAnalysisSchema")
    return analysis


def analyze_json(
    messages: list[dict[str, str]],
    *,
    timeout: int,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Return the first schema-valid analysis, trying each configured provider once."""
    for provider in configured_providers(api_key):
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            **provider.extra_payload,
        }
        try:
            analysis = _post_json(provider, payload, timeout)
        except ProviderFailure as exc:
            logger.warning(
                "AI provider failed provider={} model={} error_class={} status={}",
                provider.name,
                provider.model,
                exc.error_class,
                exc.status_code,
            )
            continue
        analysis["provider"] = provider.name
        analysis["model"] = provider.model
        return analysis

    logger.warning("No AI provider produced a valid analysis")
    return None
