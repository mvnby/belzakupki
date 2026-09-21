"""Bounded OpenAI-compatible provider fallback for worker AI analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from loguru import logger


MAX_STAGE_SECONDS = 60
MAX_RESPONSE_BYTES = 1_000_000
MAX_OUTPUT_TOKENS = 1_024
DEFAULT_PROVIDER_ORDER = ("deepseek", "qwen", "zai")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str = field(repr=False)
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
    order: list[str] = []
    for name in configured.split(","):
        normalized = name.strip().lower()
        if normalized in DEFAULT_PROVIDER_ORDER and normalized not in order:
            order.append(normalized)
    return tuple(order)


def _valid_base_url(value: str | None) -> bool:
    if not _configured(value):
        return False
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and parsed.hostname
        and (port is None or port > 0)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _system_provider(name: str) -> ProviderConfig | None:
    if name == "deepseek":
        token = os.getenv("DEEPSEEK_TOKEN")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if _configured(token) and _valid_base_url(base_url):
            return ProviderConfig(
                name="deepseek",
                api_key=token,
                base_url=base_url,
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                extra_payload={"thinking": {"type": "disabled"}},
            )
    elif name == "qwen":
        token = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL")
        if _configured(token) and _valid_base_url(base_url):
            return ProviderConfig(
                name="qwen",
                api_key=token,
                base_url=base_url,
                model=os.getenv("QWEN_MODEL", "qwen3.5-flash-2026-02-23"),
                extra_payload={"enable_thinking": False},
            )
    elif name == "zai":
        token = os.getenv("ZAI_API_KEY")
        base_url = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
        if _configured(token) and _valid_base_url(base_url):
            return ProviderConfig(
                name="zai",
                api_key=token,
                base_url=base_url,
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
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not _configured(api_key) or not _valid_base_url(base_url):
            return ()
        return (
            ProviderConfig(
                name="deepseek",
                api_key=api_key,
                base_url=base_url,
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


def _read_response(response: httpx.Response, deadline: float) -> bytes:
    response.raise_for_status()
    payload = bytearray()
    for chunk in response.iter_bytes():
        if time.monotonic() >= deadline:
            raise ProviderFailure("StageDeadlineExceeded")
        payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("ResponseTooLarge")
    return bytes(payload)


def _post_json(
    provider: ProviderConfig,
    payload: dict[str, Any],
    timeout: float,
    deadline: float,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=max(timeout, 0.1)) as client:
            with client.stream(
                "POST",
                provider.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                raw = _read_response(response, deadline)
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
    """Return the first valid analysis within a stage budget checked per chunk."""
    providers = configured_providers(api_key)
    deadline = time.monotonic() + min(max(timeout, 1), MAX_STAGE_SECONDS)
    for index, provider in enumerate(providers):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("AI provider stage deadline exhausted")
            break
        attempt_timeout = remaining / (len(providers) - index)
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            **provider.extra_payload,
        }
        try:
            analysis = _post_json(provider, payload, attempt_timeout, deadline)
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
