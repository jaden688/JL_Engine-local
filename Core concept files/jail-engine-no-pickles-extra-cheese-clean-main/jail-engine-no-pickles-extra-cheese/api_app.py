"""FastAPI wrapper that exposes the JL Engine core as an HTTP API."""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from engine_core import JLEngineCore

app = FastAPI(title="JL Engine API", version="0.1.0")

# Single engine instance reused across requests.
engine = JLEngineCore()
engine_lock = threading.Lock()


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the engine.")
    persona_name: Optional[str] = Field(
        default=None, description="Persona name to load (defaults to engine config)."
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional context payload forwarded to the engine."
    )
    user_trigger: Optional[str] = Field(
        default=None,
        description="Optional explicit trigger to bias rhythm/behavior selection.",
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest) -> Dict[str, Any]:
    context = request.context.copy() if request.context else {}
    if request.user_trigger:
        context["user_trigger"] = request.user_trigger

    try:
        with engine_lock:
            reply, telemetry, feedback = engine.generate_response(
                request.message,
                persona_name=request.persona_name,
                context=context or None,
            )
    except Exception as exc:  # pragma: no cover - runtime safety for the API
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = {
        "reply": reply,
        "telemetry": telemetry,
        "feedback": feedback,
    }
    return jsonable_encoder(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
