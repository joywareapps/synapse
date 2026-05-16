from __future__ import annotations

"""LLM provider auto-detection and OpenAI-compatible chat client."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Tool-capable model name heuristics
_TOOL_CAPABLE_KEYWORDS = ("llama3", "qwen2", "mistral", "phi4", "gemma3", "functionary")


def _is_tool_capable(model_name: str) -> bool:
    lower = model_name.lower()
    return any(kw in lower for kw in _TOOL_CAPABLE_KEYWORDS)


@dataclass
class LLMProvider:
    name: str                          # "ollama" | "lm_studio"
    base_url: str
    models: list[str] = field(default_factory=list)
    tool_capable_models: list[str] = field(default_factory=list)


async def detect_providers(
    ollama_url: str = "http://localhost:11434",
    lm_studio_url: str = "http://localhost:1234",
) -> list[LLMProvider]:
    """Probe Ollama and LM Studio; return detected providers."""
    providers: list[LLMProvider] = []

    async with httpx.AsyncClient(timeout=3.0) as client:
        # Probe Ollama
        try:
            resp = await client.get(f"{ollama_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                all_models = [m["name"] for m in data.get("models", [])]
                tool_capable = [m for m in all_models if _is_tool_capable(m)]
                providers.append(LLMProvider(
                    name="ollama",
                    base_url=ollama_url,
                    models=all_models,
                    tool_capable_models=tool_capable,
                ))
        except Exception as exc:
            logger.debug("Ollama not detected at %s: %s", ollama_url, exc)

        # Probe LM Studio
        try:
            resp = await client.get(f"{lm_studio_url}/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                all_models = [m["id"] for m in data.get("data", [])]
                tool_capable = [m for m in all_models if _is_tool_capable(m)]
                providers.append(LLMProvider(
                    name="lm_studio",
                    base_url=lm_studio_url,
                    models=all_models,
                    tool_capable_models=tool_capable,
                ))
        except Exception as exc:
            logger.debug("LM Studio not detected at %s: %s", lm_studio_url, exc)

    return providers


class LLMClient:
    """OpenAI-compatible chat completions client."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
    ) -> dict:
        """POST /v1/chat/completions. Returns full response dict."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
