"""Tests for the embedded agent (§18)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from synapse.agent.llm_client import LLMClient, LLMProvider, detect_providers
from synapse.agent.tool_dispatch import build_tool_schemas, dispatch_tool_call


# ── detect_providers tests ────────────────────────────────────────────────────

OLLAMA_RESPONSE = {
    "models": [
        {"name": "llama3:8b", "details": {}},
        {"name": "nomodel:latest", "details": {}},
    ]
}

LM_STUDIO_RESPONSE = {
    "data": [
        {"id": "qwen2-7b-instruct", "object": "model"},
        {"id": "unknown-model", "object": "model"},
    ]
}


class MockResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class MockHTTPClientBoth:
    """Simulates both Ollama and LM Studio responding."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, url: str) -> MockResponse:
        if "11434" in url:
            return MockResponse(200, OLLAMA_RESPONSE)
        if "1234" in url:
            return MockResponse(200, LM_STUDIO_RESPONSE)
        raise ConnectionError("not found")


class MockHTTPClientOllamaOnly:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, url: str) -> MockResponse:
        if "11434" in url:
            return MockResponse(200, OLLAMA_RESPONSE)
        raise ConnectionError("no lm studio")


class MockHTTPClientNeither:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, url: str) -> MockResponse:
        raise ConnectionError("nothing")


@pytest.mark.asyncio
async def test_detect_providers_both() -> None:
    with patch("synapse.agent.llm_client.httpx.AsyncClient", return_value=MockHTTPClientBoth()):
        providers = await detect_providers()

    assert len(providers) == 2
    names = {p.name for p in providers}
    assert "ollama" in names
    assert "lm_studio" in names

    ollama = next(p for p in providers if p.name == "ollama")
    assert "llama3:8b" in ollama.models
    assert "llama3:8b" in ollama.tool_capable_models
    assert "nomodel:latest" not in ollama.tool_capable_models

    lm = next(p for p in providers if p.name == "lm_studio")
    assert "qwen2-7b-instruct" in lm.tool_capable_models


@pytest.mark.asyncio
async def test_detect_providers_neither() -> None:
    with patch("synapse.agent.llm_client.httpx.AsyncClient", return_value=MockHTTPClientNeither()):
        providers = await detect_providers()
    assert providers == []


@pytest.mark.asyncio
async def test_detect_providers_ollama_only() -> None:
    with patch("synapse.agent.llm_client.httpx.AsyncClient", return_value=MockHTTPClientOllamaOnly()):
        providers = await detect_providers()
    assert len(providers) == 1
    assert providers[0].name == "ollama"


# ── build_tool_schemas tests ──────────────────────────────────────────────────

def test_build_tool_schemas_returns_list() -> None:
    schemas = build_tool_schemas()
    assert isinstance(schemas, list)
    assert len(schemas) > 0


def test_build_tool_schemas_openai_format() -> None:
    schemas = build_tool_schemas()
    for schema in schemas:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params


def test_build_tool_schemas_includes_memory_tools() -> None:
    schemas = build_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "remember" in names
    assert "recall" in names
    assert "forget" in names
    assert "note_observation" in names


def test_build_tool_schemas_get_status_no_required() -> None:
    schemas = build_tool_schemas()
    status_schema = next(s for s in schemas if s["function"]["name"] == "get_status")
    assert status_schema["function"]["parameters"]["required"] == []


def test_build_tool_schemas_get_axis_required() -> None:
    schemas = build_tool_schemas()
    axis_schema = next(s for s in schemas if s["function"]["name"] == "get_axis")
    assert "tcode_id" in axis_schema["function"]["parameters"]["required"]


# ── dispatch_tool_call tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_unknown_tool() -> None:
    result = await dispatch_tool_call("nonexistent_tool", {})
    assert "error" in result
    assert "nonexistent_tool" in result["error"]


@pytest.mark.asyncio
async def test_dispatch_tool_call_happy_path() -> None:
    """Test dispatching get_status with mocked ctx."""
    import time
    mock_engine = MagicMock()
    mock_engine.is_connected.return_value = True
    mock_player = MagicMock()
    mock_player.current_pattern.return_value = None
    mock_player.is_playing.return_value = False

    mock_ctx = MagicMock()
    mock_ctx.start_time = time.monotonic()
    mock_ctx.engines = {"primary": mock_engine}
    mock_ctx.players = {"primary": mock_player}

    import synapse.tools.registry as reg
    with patch.object(reg, "ctx", mock_ctx):
        result = await dispatch_tool_call("get_status", {})

    assert "status" in result
    assert result["status"] == "ok"


# ── SynapseAgent tests ────────────────────────────────────────────────────────

def _make_mock_ctx(tmp_path: Path) -> MagicMock:
    """Build a minimal mock AppContext for agent tests."""
    import time
    from synapse.profiles.store import ProfileStore

    profile_store = ProfileStore(str(tmp_path / "profiles"))
    profile_store.create("testuser")

    mock_engine = MagicMock()
    mock_engine.is_connected.return_value = True
    mock_player = MagicMock()
    mock_player.current_pattern.return_value = None
    mock_player.is_playing.return_value = False

    mock_sensor_mgr = MagicMock()
    mock_sensor_mgr.get_all_with_restim.return_value = []

    mock_ctx = MagicMock()
    mock_ctx.start_time = time.monotonic()
    mock_ctx.engines = {"primary": mock_engine}
    mock_ctx.players = {"primary": mock_player}
    mock_ctx.sensor_manager = mock_sensor_mgr
    mock_ctx.profile_store = profile_store
    mock_ctx.active_profile_name = "testuser"
    mock_ctx.config.agent.system_prompt_extra = ""
    return mock_ctx


@pytest.mark.asyncio
async def test_build_system_prompt_includes_guide(tmp_path: Path) -> None:
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient

    mock_ctx = _make_mock_ctx(tmp_path)

    llm = LLMClient("http://localhost:11434", "llama3")
    agent = SynapseAgent(llm_client=llm, profile_name="testuser")

    guide_content = "# Synapse Operational Guide\nSafety first!"
    guide_path = tmp_path / "docs" / "mcp-guide.md"
    guide_path.parent.mkdir(parents=True)
    guide_path.write_text(guide_content)

    import synapse.agent.agent as agent_mod
    with patch.object(agent_mod, "ctx", mock_ctx):
        with patch("synapse.agent.agent._load_guide", return_value=guide_content):
            prompt = agent.build_system_prompt()

    assert guide_content in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_includes_profile(tmp_path: Path) -> None:
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient

    mock_ctx = _make_mock_ctx(tmp_path)
    mock_ctx.profile_store.update("testuser", notes="Likes slow patterns")

    llm = LLMClient("http://localhost:11434", "llama3")
    agent = SynapseAgent(llm_client=llm, profile_name="testuser")

    import synapse.agent.agent as agent_mod
    with patch.object(agent_mod, "ctx", mock_ctx):
        with patch("synapse.agent.agent._load_guide", return_value=""):
            prompt = agent.build_system_prompt()

    assert "testuser" in prompt
    assert "Likes slow patterns" in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_includes_memories(tmp_path: Path) -> None:
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient

    mock_ctx = _make_mock_ctx(tmp_path)
    mock_ctx.profile_store.add_memory("testuser", "Prefers slow oscillation", "preference")

    llm = LLMClient("http://localhost:11434", "llama3")
    agent = SynapseAgent(llm_client=llm, profile_name="testuser")

    import synapse.agent.agent as agent_mod
    with patch.object(agent_mod, "ctx", mock_ctx):
        with patch("synapse.agent.agent._load_guide", return_value=""):
            prompt = agent.build_system_prompt()

    assert "Prefers slow oscillation" in prompt


@pytest.mark.asyncio
async def test_agent_chat_tool_call_loop(tmp_path: Path) -> None:
    """Test that the agent executes a tool call then gets the final text response."""
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient

    mock_ctx = _make_mock_ctx(tmp_path)

    llm = LLMClient("http://localhost:11434", "llama3")
    agent = SynapseAgent(llm_client=llm, profile_name=None)

    # First response: one tool call
    tool_call_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "get_status",
                        "arguments": "{}",
                    },
                }],
            }
        }]
    }
    # Second response: final text
    text_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Everything looks good!",
                "tool_calls": [],
            }
        }]
    }

    call_count = 0

    async def mock_chat(messages, tools=None, stream=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tool_call_response
        return text_response

    llm.chat = mock_chat

    import synapse.agent.agent as agent_mod
    import synapse.tools.registry as reg

    async def mock_get_status() -> dict:
        return {"status": "ok", "uptime_s": 1.0, "instances": []}

    with patch.object(agent_mod, "ctx", mock_ctx):
        with patch.object(reg, "ctx", mock_ctx):
            with patch("synapse.agent.agent._load_guide", return_value=""):
                # Patch dispatch to use mock_get_status
                with patch("synapse.agent.agent.dispatch_tool_call", new=AsyncMock(
                    return_value={"status": "ok", "uptime_s": 1.0, "instances": []}
                )):
                    result = await agent.chat("What is the status?")

    assert result == "Everything looks good!"
    assert call_count == 2


# ── AgentLoop observe mode tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observe_mode_filters_non_read_tools(tmp_path: Path) -> None:
    """AgentLoop in observe mode should only include read tools in the schema."""
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient
    from synapse.agent.loop import AgentLoop, _OBSERVE_WHITELIST

    mock_ctx = _make_mock_ctx(tmp_path)

    llm = LLMClient("http://localhost:11434", "llama3")
    agent = SynapseAgent(llm_client=llm, profile_name=None)
    loop = AgentLoop(agent=agent, interval_s=999, mode="observe")

    # Simulate a tick where the LLM tries to call set_axis (not allowed in observe)
    calls_dispatched: list[str] = []

    async def mock_dispatch(name: str, args: dict):
        calls_dispatched.append(name)
        return {"status": "ok"}

    tick_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Checking...",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "set_axis", "arguments": '{"tcode_id":"V0","value":0.5}'},
                    },
                    {
                        "id": "c2",
                        "function": {"name": "get_status", "arguments": "{}"},
                    },
                ],
            }
        }]
    }

    async def mock_llm_chat(messages, tools=None, stream=False):
        return tick_response

    llm.chat = mock_llm_chat

    import synapse.agent.loop as loop_mod
    import synapse.agent.agent as agent_mod

    with patch.object(loop_mod, "ctx", mock_ctx):
        with patch.object(agent_mod, "ctx", mock_ctx):
            with patch("synapse.agent.loop.dispatch_tool_call", new=mock_dispatch):
                with patch("synapse.agent.agent._load_guide", return_value=""):
                    await loop._tick()

    # set_axis should NOT be dispatched in observe mode
    assert "set_axis" not in calls_dispatched
    # get_status should be dispatched
    assert "get_status" in calls_dispatched
