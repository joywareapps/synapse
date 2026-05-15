from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from synapse.api.routes_state import router as state_router
from synapse.api.routes_control import router as control_router
from synapse.api.routes_patterns import router as patterns_router
from synapse.api.websocket import router as ws_router


def create_app(
    auth_key: str = "",
    web_dir: Optional[str] = None,
) -> FastAPI:
    app = FastAPI(title="Synapse", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if auth_key:
        @app.middleware("http")
        async def check_auth(request: Request, call_next) -> Response:
            # Skip auth for WebSocket and health
            if request.url.path in ("/health", "/") or request.url.path.startswith("/ws"):
                return await call_next(request)
            key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if key != auth_key:
                return Response(status_code=401, content="Unauthorized")
            return await call_next(request)

    app.include_router(state_router)
    app.include_router(control_router)
    app.include_router(patterns_router)
    app.include_router(ws_router)

    if web_dir:
        web_path = Path(web_dir)
        if web_path.exists() and web_path.is_dir():
            app.mount("/", StaticFiles(directory=str(web_path), html=True), name="static")

    return app
