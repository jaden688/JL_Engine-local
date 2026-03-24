"""
JL Engine Persona API - monetizable FastAPI microservice.

Runtime path: HTTP -> persona -> JL Engine core -> telemetry -> response.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api_keys import (
    ApiKeyRecord,
    UsageLimitExceeded,
    create_api_key,
    check_and_increment_usage,
    estimate_tokens,
    get_api_key,
    usage_snapshot,
)
from billing import create_checkout_session
from engine_core import EngineConfig, JLEngineCore

# Global defaults (override with env vars)
DEFAULT_PERSONA = os.environ.get("DEFAULT_PERSONA", "SparkByte")
DEFAULT_BACKEND = os.environ.get("DEFAULT_BACKEND", "ollama-local")
FALLBACK_BACKEND = os.environ.get("FALLBACK_BACKEND", "ollama-local")
REQUIRE_API_KEY = os.environ.get("REQUIRE_API_KEY", "false").lower() in {"1", "true", "yes"}
BILLING_ENABLED = os.environ.get("BILLING_ENABLED", "false").lower() in {"1", "true", "yes"}

app = FastAPI(title="JL Engine Persona API", version="1.0.0")
app.mount("/site", StaticFiles(directory=Path(__file__).resolve().parent / "site"), name="site")

# Single engine instance shared across requests with a lock.
engine_lock = threading.Lock()
engine = JLEngineCore(config=EngineConfig(default_persona_name=DEFAULT_PERSONA))


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the engine.")
    persona_name: Optional[str] = Field(
        default=None, description="Persona name to load (defaults to config)."
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional context payload forwarded to the engine."
    )
    user_trigger: Optional[str] = Field(
        default=None,
        description="Optional explicit trigger to bias rhythm/behavior selection.",
    )


class RewriteRequest(BaseModel):
    text: str
    persona_name: Optional[str] = None
    style: Optional[str] = None


class BrandVoiceRequest(BaseModel):
    text: str
    brand_voice: str
    persona_name: Optional[str] = None


class IssueKeyRequest(BaseModel):
    plan: str = "free"
    email: Optional[str] = None


def _require_api_key(x_api_key: str = Header(None)) -> Optional[ApiKeyRecord]:
    if not REQUIRE_API_KEY:
        return None
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing x-api-key header.")
    record = get_api_key(x_api_key)
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    return record


def _maybe_billable_call(
    record: Optional[ApiKeyRecord],
    tokens: int,
    persona: str | None,
    backend: str | None,
) -> Optional[Dict[str, Any]]:
    if not BILLING_ENABLED:
        return None
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing x-api-key header.")
    return _billable_call(record, tokens, persona=persona, backend=backend)


def _billable_call(record: ApiKeyRecord, tokens: int, persona: str | None, backend: str | None) -> Dict[str, Any]:
    try:
        return check_and_increment_usage(record.api_key, record.plan, tokens, persona=persona, backend=backend)
    except UsageLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"message": str(exc), "plan": exc.plan, "limit": exc.limit, "window": exc.window},
        ) from exc


def _respond(payload: Dict[str, Any]) -> Dict[str, Any]:
    return jsonable_encoder(payload)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root_redirect() -> Dict[str, str]:
    return {"message": "JL Engine Persona API", "site": "/site"}


@app.get("/pricing")
def pricing() -> Dict[str, Any]:
    return {
        "plans": {
            "free": {"price": 0, "limits": {"daily": 50}},
            "indie": {"price": "TBD", "limits": {"monthly": 3000}},
            "pro": {"price": "TBD", "limits": {"monthly": 50000}},
        },
        "checkout": "/billing/checkout?plan={plan}&email={email}",
    }


@app.post("/billing/checkout")
def billing_checkout(plan: str = "free", email: Optional[str] = None) -> Dict[str, Any]:
    if not BILLING_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing is disabled.")
    session = create_checkout_session(plan=plan, email=email)
    return _respond(session)


@app.post("/billing/issue-key")
def billing_issue_key(request: IssueKeyRequest) -> Dict[str, Any]:
    if not BILLING_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing is disabled.")
    key = create_api_key(plan=request.plan, email=request.email)
    return _respond({"api_key": key.api_key, "plan": key.plan, "email": key.email, "mode": "manual"})


@app.get("/me")
def me(record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API keys are disabled.")
    return _respond(
        {
            "api_key": record.api_key,
            "plan": record.plan,
            "created_at": record.created_at,
            "usage": usage_snapshot(record.api_key),
        }
    )


def _run_engine(message: str, persona_name: Optional[str], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    with engine_lock:
        reply, telemetry, feedback = engine.generate_response(
            message,
            persona_name=persona_name or DEFAULT_PERSONA,
            context=context or None,
        )
    return {"reply": reply, "telemetry": telemetry, "feedback": feedback}


@app.post("/chat")
def chat(request: ChatRequest, record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    tokens = estimate_tokens(request.message)
    usage = _maybe_billable_call(record, tokens, persona=request.persona_name or DEFAULT_PERSONA, backend=DEFAULT_BACKEND)
    result = _run_engine(request.message, request.persona_name, request.context)
    if record and BILLING_ENABLED:
        result["plan"] = record.plan
        result["usage"] = usage
    return _respond(result)


@app.post("/persona-chat")
def persona_chat(request: ChatRequest, record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    persona_name = request.persona_name or DEFAULT_PERSONA
    tokens = estimate_tokens(request.message)
    usage = _maybe_billable_call(record, tokens, persona=persona_name, backend=DEFAULT_BACKEND)
    result = _run_engine(request.message, persona_name, request.context)
    result["persona"] = persona_name
    if record and BILLING_ENABLED:
        result["plan"] = record.plan
        result["usage"] = usage
    return _respond(result)


@app.post("/analyze")
def analyze(request: ChatRequest, record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    persona_name = request.persona_name or DEFAULT_PERSONA
    prompt = f"Analyze the following content. Return concise findings + next actions.\n\nCONTENT:\n{request.message}"
    tokens = estimate_tokens(prompt)
    usage = _maybe_billable_call(record, tokens, persona=persona_name, backend=DEFAULT_BACKEND)
    result = _run_engine(prompt, persona_name, request.context)
    result["persona"] = persona_name
    if record and BILLING_ENABLED:
        result["plan"] = record.plan
        result["usage"] = usage
    return _respond(result)


@app.post("/rewrite")
def rewrite(request: RewriteRequest, record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    persona_name = request.persona_name or DEFAULT_PERSONA
    style = request.style or "high-converting, clear, confident"
    prompt = f"Rewrite the following text in a {style} style. Keep it concise and actionable.\n\nTEXT:\n{request.text}"
    tokens = estimate_tokens(prompt)
    usage = _maybe_billable_call(record, tokens, persona=persona_name, backend=DEFAULT_BACKEND)
    result = _run_engine(prompt, persona_name, None)
    result["persona"] = persona_name
    if record and BILLING_ENABLED:
        result["plan"] = record.plan
        result["usage"] = usage
    return _respond(result)


@app.post("/brand-voice")
def brand_voice(request: BrandVoiceRequest, record: Optional[ApiKeyRecord] = Depends(_require_api_key)) -> Dict[str, Any]:
    persona_name = request.persona_name or DEFAULT_PERSONA
    prompt = (
        f"Adopt the following brand voice: {request.brand_voice}. "
        f"Rewrite and polish the text for consistency and conversion.\n\nTEXT:\n{request.text}"
    )
    tokens = estimate_tokens(prompt)
    usage = _maybe_billable_call(record, tokens, persona=persona_name, backend=DEFAULT_BACKEND)
    result = _run_engine(prompt, persona_name, None)
    result["persona"] = persona_name
    if record and BILLING_ENABLED:
        result["plan"] = record.plan
        result["usage"] = usage
    return _respond(result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
    )
