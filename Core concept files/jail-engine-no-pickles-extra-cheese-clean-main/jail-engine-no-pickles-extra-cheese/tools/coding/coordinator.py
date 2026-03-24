from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .context_pack import build_context_pack
from .registry import dispatch_tool
from .session import Session, new_session


ROLE_SYSTEM = """You are JL Coding Harness.

You MUST respond with strict JSON ONLY.

Schema:
{
  "role": "Planner|Implementer|Reviewer|Debugger|Integrator",
  "intent": "...",
  "plan": ["...", ...],
  "tool_calls": [
    {"tool": "fs.read|fs.write|fs.apply_patch|search.rg|exec.run|git.diff|repo.map|quality.test|...", "payload": {...}}
  ],
  "patches": [
    {"path": "relative/or/absolute", "patch": "unified diff"}
  ],
  "notes": "...",
  "stop": false
}

Rules:
- Prefer fs.apply_patch for edits.
- Run tests (quality.test or exec.run pytest) before stop=true.
- Keep tool_calls short and purposeful.
"""


def run_coding_task(
    user_goal: str,
    backend_runner,
    model: Optional[str] = None,
    max_iters: int = 6,
) -> Dict[str, Any]:
    """Run a multi-role coding task using the installed backend runner.

    backend_runner signature: (query, history, model=None) -> {assistant,tokens,raw}
    """
    session = new_session()
    context = build_context_pack(user_goal)
    session.write_json("context_pack.json", context)

    history: List[Dict[str, Any]] = [
        {"role": "system", "content": ROLE_SYSTEM},
        {"role": "user", "content": f"GOAL: {user_goal}\n\nCONTEXT_PACK: {json.dumps(context, ensure_ascii=False)[:12000]}"},
    ]

    last_tool_outputs: List[Dict[str, Any]] = []
    scorecard: Dict[str, Any] = {"iters": 0, "tests_passed": None, "lint_passed": None, "typecheck_passed": None}

    for it in range(max_iters):
        scorecard["iters"] = it + 1
        resp = backend_runner(query="Next step.", history=history, model=model)
        assistant = (resp or {}).get("assistant", "")
        session.append_text("transcript.txt", f"\n# ITER {it+1}\n{assistant}\n")

        try:
            obj = json.loads(assistant)
        except Exception:
            # If the model fails JSON, push it back on rails.
            history.append({"role": "assistant", "content": assistant})
            history.append({
                "role": "user",
                "content": "Your last message was not valid JSON. Re-emit STRICT JSON only using the schema.",
            })
            continue

        session.append_jsonl("model_steps.jsonl", obj)

        # Apply patches first
        for patch in (obj.get("patches") or []):
            if not isinstance(patch, dict):
                continue
            path = patch.get("path")
            ptxt = patch.get("patch")
            if path and ptxt:
                out = dispatch_tool("fs.apply_patch", {"path": path, "patch": ptxt})
                session.append_jsonl("tool_calls.jsonl", {"tool": "fs.apply_patch", "payload": {"path": path}, "result": out})
                last_tool_outputs.append(out)

        # Run tool calls
        for call in (obj.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            tool = call.get("tool")
            payload = call.get("payload") or {}
            out = dispatch_tool(str(tool), payload)
            session.append_jsonl("tool_calls.jsonl", {"tool": tool, "payload": payload, "result": out})
            last_tool_outputs.append(out)

            # Update scorecard heuristics
            if str(tool) in {"quality.test"}:
                rc = (out.get("data") or {}).get("returncode")
                if rc is not None:
                    scorecard["tests_passed"] = (rc == 0)
            if str(tool) == "quality.lint":
                rc = (out.get("data") or {}).get("returncode")
                if rc is not None:
                    scorecard["lint_passed"] = (rc == 0)
            if str(tool) == "quality.typecheck":
                rc = (out.get("data") or {}).get("returncode")
                if rc is not None:
                    scorecard["typecheck_passed"] = (rc == 0)

        session.write_json("scorecard.json", scorecard)

        history.append({"role": "assistant", "content": assistant})
        history.append(
            {
                "role": "user",
                "content": "TOOL_OUTPUTS (most recent):\n" + json.dumps(last_tool_outputs[-8:], ensure_ascii=False)[:12000],
            }
        )

        if bool(obj.get("stop")):
            break

    return {
        "ok": True,
        "response": "coding task complete",
        "data": {"session_id": session.id, "session_path": str(session.path), "scorecard": scorecard},
    }
