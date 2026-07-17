from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMConfigError(RuntimeError):
    """Raised when LLM API configuration is missing or invalid."""


class LLMRequestError(RuntimeError):
    """Raised when the LLM API request fails."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60
    verify_ssl: bool = True
    response_format: str = "json_object"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


class OpenAICompatibleClient:
    """Small OpenAI-compatible chat-completions client using the standard library."""

    def __init__(self, config: LLMConfig):
        self.config = config

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        if self.config.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            self.config.chat_completions_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ProjectRadar/0.1",
            },
            method="POST",
        )
        context = None if self.config.verify_ssl else ssl._create_unverified_context()

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
                context=context,
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise LLMRequestError(f"LLM API request failed: {exc}") from exc

        data = json.loads(response_body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError(f"LLM API response missing message content: {response_body}") from exc
        return parse_json_content(content)


def config_from_env(
    api_key_env: str,
    base_url: str | None,
    model: str | None,
    timeout_seconds: int,
    verify_ssl: bool,
    response_format: str,
) -> LLMConfig:
    api_key = os.getenv(api_key_env, "").strip()
    selected_model = model or os.getenv("PROJECT_RADAR_LLM_MODEL", "").strip()
    selected_base_url = base_url or os.getenv("PROJECT_RADAR_LLM_BASE_URL", "").strip()
    if not api_key:
        raise LLMConfigError(f"缺少 API Key，请先设置环境变量：{api_key_env}")
    if not selected_model:
        raise LLMConfigError("缺少模型名称，请设置 PROJECT_RADAR_LLM_MODEL 或使用 --llm-model")
    return LLMConfig(
        api_key=api_key,
        model=selected_model,
        base_url=selected_base_url or "https://api.openai.com/v1",
        timeout_seconds=timeout_seconds,
        verify_ssl=verify_ssl,
        response_format=response_format,
    )


def parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise

