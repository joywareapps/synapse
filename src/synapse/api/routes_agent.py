from __future__ import annotations

"""REST API routes for the embedded LLM agent (§18)."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from synapse.api.deps import ctx

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_agent(
    model: str = "",
    provider_url: Optional[str] = None,
    profile_name: Optional[str] = None,
) -> Any:
    """Return the existing agent or create a new one."""
    from synapse.agent.agent import SynapseAgent
    from synapse.agent.llm_client import LLMClient

    if ctx.agent is not None and not model and not provider_url:
        # Reuse existing
        if profile_name is not None:
            ctx.agent.profile_name = profile_name
            ctx.active_profile_name = profile_name
        return ctx.agent

    # Determine URL and model
    base_url = provider_url or ""
    chosen_model = model

    if not base_url or not chosen_model:
        # Auto-detect
        import asyncio
        from synapse.agent.llm_client import detect_providers
        try:
            ollama_url = ctx.config.agent.ollama_url
            lm_studio_url = ctx.config.agent.lm_studio_url
        except AttributeError:
            ollama_url = "http://localhost:11434"
            lm_studio_url = "http://localhost:1234"

        try:
            loop = asyncio.get_event_loop()
            providers = loop.run_until_complete(detect_providers(ollama_url, lm_studio_url))
        except RuntimeError:
            providers = []

        for p in providers:
            if not base_url:
                base_url = p.base_url
            if not chosen_model and p.tool_capable_models:
                chosen_model = p.tool_capable_models[0]
            elif not chosen_model and p.models:
                chosen_model = p.models[0]
            if base_url and chosen_model:
                break

    if not base_url:
        try:
            base_url = ctx.config.agent.ollama_url
        except AttributeError:
            base_url = "http://localhost:11434"

    llm_client = LLMClient(base_url=base_url, model=chosen_model)
    agent = SynapseAgent(llm_client=llm_client, profile_name=profile_name)
    ctx.agent = agent
    if profile_name:
        ctx.active_profile_name = profile_name
    return agent


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    profile_name: Optional[str] = None


class LoopStartRequest(BaseModel):
    model: str = ""
    provider_url: Optional[str] = None
    interval_s: float = 30.0
    mode: str = "observe"
    profile_name: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/providers")
async def get_providers() -> list[dict]:
    """List detected LLM providers and their available models."""
    from synapse.agent.llm_client import detect_providers
    try:
        ollama_url = ctx.config.agent.ollama_url
        lm_studio_url = ctx.config.agent.lm_studio_url
    except AttributeError:
        ollama_url = "http://localhost:11434"
        lm_studio_url = "http://localhost:1234"

    providers = await detect_providers(ollama_url, lm_studio_url)
    return [
        {
            "name": p.name,
            "base_url": p.base_url,
            "models": p.models,
            "tool_capable_models": p.tool_capable_models,
        }
        for p in providers
    ]


@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    """Send a message to the agent and get a response."""
    agent = _get_or_create_agent(profile_name=req.profile_name)
    response = await agent.chat(req.message)
    return {
        "response": response,
        "profile_name": agent.profile_name,
    }


@router.get("/history")
async def get_history() -> list[dict]:
    """Get the full conversation history."""
    if ctx.agent is None:
        return []
    return ctx.agent.get_history()


@router.delete("/history")
async def clear_history() -> dict:
    """Clear the conversation history."""
    if ctx.agent is not None:
        ctx.agent.clear_history()
    return {"status": "cleared"}


@router.post("/loop/start")
async def loop_start(req: LoopStartRequest) -> dict:
    """Start the autonomous agent loop."""
    from synapse.agent.loop import AgentLoop

    if ctx.agent_loop and ctx.agent_loop.status()["running"]:
        return {"status": "already_running", **ctx.agent_loop.status()}

    agent = _get_or_create_agent(
        model=req.model,
        provider_url=req.provider_url,
        profile_name=req.profile_name,
    )

    try:
        max_tool_calls = ctx.config.agent.max_tool_calls_per_tick
    except AttributeError:
        max_tool_calls = 2

    loop = AgentLoop(
        agent=agent,
        interval_s=req.interval_s,
        mode=req.mode,
        max_tool_calls=max_tool_calls,
    )
    await loop.start()
    ctx.agent_loop = loop
    return {"status": "started", **loop.status()}


@router.post("/loop/stop")
async def loop_stop() -> dict:
    """Stop the autonomous agent loop."""
    if ctx.agent_loop is None:
        return {"status": "not_running"}
    await ctx.agent_loop.stop()
    return {"status": "stopped"}


@router.get("/loop/status")
async def loop_status() -> dict:
    """Get the autonomous loop status."""
    if ctx.agent_loop is None:
        return {"running": False, "mode": None, "interval_s": None, "tick_count": 0, "last_tick_at": None}
    return ctx.agent_loop.status()
