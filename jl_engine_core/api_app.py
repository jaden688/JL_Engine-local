from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

from . import __version__
from .engine_core import EngineConfig, JLEngineCore


def _allowed_origins() -> list[str]:
    """Return CORS origins from env or default to localhost-only."""
    env_val = os.getenv("JL_CORS_ORIGINS", "").strip()
    if env_val:
        return [o.strip() for o in env_val.split(",") if o.strip()]
    return [
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]


class ChatRequest(BaseModel):
    # Accept legacy keys to avoid 422s from older clients.
    message: Optional[str] = None
    user_message: Optional[str] = None
    agent: Optional[str] = None
    agent_name: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


def _apply_overrides(config: EngineConfig, overrides: Optional[Dict[str, Any]]) -> EngineConfig:
    if not overrides:
        return config

    config.master_file = overrides.get("master_file", config.master_file)
    config.behavior_states_file = overrides.get("behavior_states_file", config.behavior_states_file)
    config.mpf_registry_file = overrides.get("mpf_registry_file", config.mpf_registry_file)
    config.default_agent_name = overrides.get("default_agent_name", config.default_agent_name)
    return config


def create_app(config_overrides: Optional[Dict[str, Any]] = None) -> FastAPI:
    engine_config = _apply_overrides(EngineConfig(), config_overrides)
    engine = JLEngineCore(config=engine_config)

    app = FastAPI(title="J_engine Core API", version=__version__)

    # Restrict CORS to known local origins; override via JL_CORS_ORIGINS env var.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response

    # Serve the web UI at /ui  (optional — works even without this)
    _ui_dir = Path(__file__).resolve().parent.parent.parent / "ui_web"
    if _ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_ui_dir), html=True), name="ui")

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/chat")
    async def chat(request: ChatRequest) -> Dict[str, Any]:
        try:
            message = request.message or request.user_message
            if not message:
                raise HTTPException(status_code=422, detail="Missing 'message' in request body.")
            agent = request.agent or request.agent_name
            reply, telemetry, feedback = engine.generate_response(
                user_message=message,
                agent_name=agent,
                context=request.context or {},
            )
            return {"reply": reply, "telemetry": telemetry, "feedback": feedback}
        except Exception as exc:  # pragma: no cover - runtime safeguard
            raise HTTPException(status_code=500, detail="internal_error") from exc

    @app.post("/agent-chat")
    async def agent_chat(request: ChatRequest) -> Dict[str, Any]:
        """Alias for /chat endpoint (Unity compatibility)"""
        return await chat(request)

    @app.get("/agent/{agent_name}/state")
    async def get_agent_state(agent_name: str) -> Dict[str, Any]:
        """Get current agent state for animation mapping"""
        try:
            # Get engine status which includes rhythm, gait, aperture
            status = engine.get_engine_status()

            return {
                "agent": agent_name,
                "rhythm": status.get("rhythm", "flop"),
                "gait": status.get("gait", "walk"),
                "aperture_mode": status.get("aperture_mode", "LIMITED"),
                "stability_score": status.get("stability_score", 0.5),
                "modulation_fault": status.get("modulation_fault", False),
            }
        except Exception as exc:  # pragma: no cover - runtime safeguard
            raise HTTPException(status_code=500, detail="internal_error") from exc

    return app


app = create_app()
