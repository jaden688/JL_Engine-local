"""
FastAPI control-plane wrapper with basic tenant isolation.

This is a lightweight starting point for the SaaS posture described in
docs/saas_positioning.md. Tenants are resolved from a file-backed registry and
authenticated via bearer tokens. Each tenant gets its own engine instance and
lock to keep in-memory state (hybrid memory, rhythm, drift) isolated.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from engine_core import EngineConfig, JLEngineCore
from framework.mpf import load_mpf_registry
from saas.tenant_registry import Tenant, TenantRegistry

ENGINE_ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="JL Engine Control Plane", version="0.2.0")

tenant_registry = TenantRegistry()
_engine_pool: dict[str, JLEngineCore] = {}
_engine_locks: dict[str, threading.Lock] = {}
_pool_guard = threading.Lock()


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the engine.")
    persona_name: Optional[str] = Field(
        default=None, description="Persona name to load (defaults to tenant config)."
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional context payload forwarded to the engine."
    )
    user_trigger: Optional[str] = Field(
        default=None,
        description="Optional explicit trigger to bias rhythm/behavior selection.",
    )


def _parse_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    parts = header_value.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def require_tenant(authorization: str = Header(None)) -> Tenant:
    token = _parse_bearer_token(authorization)
    tenant = tenant_registry.authenticate_token(token)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )
    return tenant


def _build_engine_config(tenant: Tenant) -> EngineConfig:
    cfg_kwargs: Dict[str, Any] = {
        "master_file": str(ENGINE_ROOT / "JLframe_Engine_Framework.json"),
        "behavior_states_file": str(ENGINE_ROOT / "behavior_states.json"),
        "mpf_registry_file": str(tenant.mpf_registry_file),
        "default_persona_name": tenant.default_persona
        or EngineConfig().default_persona_name,
    }
    if tenant.history_length is not None:
        cfg_kwargs["history_length"] = int(tenant.history_length)
    return EngineConfig(**cfg_kwargs)


def _get_engine_for_tenant(tenant: Tenant) -> tuple[JLEngineCore, threading.Lock]:
    with _pool_guard:
        if tenant.tenant_id not in _engine_pool:
            _engine_pool[tenant.tenant_id] = JLEngineCore(
                config=_build_engine_config(tenant)
            )
            _engine_locks[tenant.tenant_id] = threading.Lock()

        return _engine_pool[tenant.tenant_id], _engine_locks[tenant.tenant_id]


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/tenants/{tenant_id}/health")
def tenant_health(tenant_id: str, tenant: Tenant = Depends(require_tenant)) -> Dict[str, str]:
    if tenant.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch.")
    return {"status": "ok", "tenant": tenant.tenant_id}


@app.get("/v1/tenants/me")
def tenant_me(tenant: Tenant = Depends(require_tenant)) -> Dict[str, str]:
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "mpf_registry_file": str(tenant.mpf_registry_file),
    }


@app.get("/v1/tenants/{tenant_id}/personas")
def list_personas(tenant_id: str, tenant: Tenant = Depends(require_tenant)) -> Dict[str, Any]:
    if tenant.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch.")

    profiles = load_mpf_registry(str(tenant.mpf_registry_file))
    personas = [
        {
            "display_name": display_name,
            "persona_file": profile.persona_file,
            "drive_type": profile.drive_type,
            "default_backend_id": profile.default_backend_id,
            "tags": profile.tags,
        }
        for display_name, profile in profiles.items()
    ]
    return {"tenant": tenant.tenant_id, "personas": personas}


@app.post("/v1/tenants/{tenant_id}/chat")
def chat(tenant_id: str, request: ChatRequest, tenant: Tenant = Depends(require_tenant)) -> Dict[str, Any]:
    if tenant.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch.")

    ctx = request.context.copy() if isinstance(request.context, dict) else {}
    if request.user_trigger:
        ctx["user_trigger"] = request.user_trigger

    engine, lock = _get_engine_for_tenant(tenant)
    try:
        with lock:
            reply, telemetry, feedback = engine.generate_response(
                request.message,
                persona_name=request.persona_name,
                context=ctx or None,
            )
    except Exception as exc:  # pragma: no cover - runtime safety for the API
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = {
        "tenant": tenant.tenant_id,
        "reply": reply,
        "telemetry": telemetry,
        "feedback": feedback,
    }
    return jsonable_encoder(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "saas.service:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
