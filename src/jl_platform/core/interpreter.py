"""Licensed under the Apache License, Version 2.0. See LICENSE.md and NOTICE."""

from __future__ import annotations

import inspect
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from time import time
from threading import Thread
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import uuid4

from jl_engine_core.engine_core import JLEngineCore
from jl_platform.core.tools.builtin import default_allow_unsafe_tools, register_core_tools
from jl_platform.core.tools.registry import ToolRegistry
from jl_platform.core.tools.PrivilegedMemoryForge import PrivilegedMemoryForge


SYSTEM_PREAMBLE = """\
You are a local interpreter. You can call tools to complete tasks.
Return ONLY JSON.

Schema:
1) Tool call:
{{"tool": "<tool_name>", "input": {{...}}}}

2) Final answer:
{{"final": "<response>"}}

Rules:
- Casual conversation, greetings, introductions, self-description, and "what system is this" questions should be answered directly with `{{"final": ...}}`.
- Do not inspect the local machine or run commands just to answer conversational questions. Only do local inspection when the user explicitly asks you to check, inspect, list, read, or execute something on this machine.
- If the user asks for a real-world action (files/folders/commands), call a tool before final.
- When the user asks for multiple local actions, keep going until the whole request is completed. Do not stop after the first successful tool call if more requested work remains.
- You have an incredibly powerful dynamic environment. Prefer writing custom Python solutions using `py_exec_stream` or forging temporary tools via `forge_create` to solve complex or custom tasks.
- You are not restricted to static tools. Write code to solve the user's problem.
- Never claim an action succeeded unless a tool result confirms it.
- Answer directly when no tool is needed.
- Read-only actions may run immediately; state-changing actions may require confirmation before execution.
- The host is Windows.
- Valid `bridge_local` modes are exactly `subprocess`, `fs_read`, `fs_write`, `fs_mkdir`, `fs_list`, `http`, `browser_inspect`, `browser_action`, and `ui`.
- For browser actions, use `bridge_local` with `mode: "browser_action"` and `data.action` set to one of `open`, `navigate`, `goto`, `click`, `focus`, `type`, `fill`, or `submit`.

Available tools:
{tools}

Tool call examples:
{tool_examples}
"""


@dataclass
class PendingAction:
    id: str
    tool: str
    input: Dict[str, Any]
    summary: str
    risk_level: str
    original_request: str
    run_context: Dict[str, Any]
    tool_trace: List[Dict[str, Any]]
    steps_remaining: int
    created_at: float = field(default_factory=time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "input": self.input,
            "summary": self.summary,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
        }


class InterpreterSession:
    def __init__(
        self,
        engine: Optional[JLEngineCore] = None,
        max_steps: int = 5,
        memory_forge: Optional[PrivilegedMemoryForge] = None,
        allow_unsafe_tools: Optional[bool] = None,
        allow_direct_action_fallback: bool = False,
    ):
        self.engine = engine or JLEngineCore()
        self.max_steps = max_steps
        self.registry = ToolRegistry()
        resolved_allow_unsafe_tools = (
            default_allow_unsafe_tools()
            if allow_unsafe_tools is None
            else bool(allow_unsafe_tools)
        )
        register_core_tools(self.registry, allow_unsafe=resolved_allow_unsafe_tools)
        self.memory_forge = memory_forge
        self.history: List[Dict[str, Any]] = []
        self.allow_unsafe_tools = resolved_allow_unsafe_tools
        self.allow_direct_action_fallback = allow_direct_action_fallback
        self._pending_action: PendingAction | None = None

    def _emit_stream_event(
        self,
        event_sink: Callable[[Dict[str, Any]], None] | None,
        event_type: str,
        **payload: Any,
    ) -> None:
        if event_sink is None:
            return
        event = {"type": event_type, **payload}
        try:
            event_sink(event)
        except Exception:
            pass

    def _build_conversational_fallback_prompt(self, user_message: str) -> str:
        return (
            "The user is having a normal conversation with you, not asking for a local action.\n"
            "Reply in normal prose as the currently selected agent.\n"
            "Do not call tools. Do not inspect the machine. Do not mention approvals, confirmations, "
            "policies, or JSON unless the user explicitly asked you to inspect or execute something locally.\n"
            "If they ask what system this is, answer from known JL Engine runtime context only, and only "
            "invite an explicit inspection if exact machine details would require checking the computer.\n\n"
            f"USER:\n{user_message}"
        )

    def _conversational_local_scope_hint(self) -> str:
        agent_name = str(getattr(self.engine, "current_agent_name", "") or "the current agent").strip()
        return (
            f"I'm {agent_name}, riding the JL Engine local console here. "
            "If you want exact machine details, ask me to inspect the system directly and I'll check it carefully."
        )

    def _fallback_to_direct_chat(
        self,
        *,
        request_text: str,
        run_context: Dict[str, Any],
        tool_trace: List[Dict[str, Any]],
        telemetry: Dict[str, Any] | None = None,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        fallback_context = dict(run_context)
        fallback_context["memory_user_message"] = request_text
        fallback_context["chat_fallback"] = True
        fallback_context.pop("synthetic_turn", None)

        reply_text = ""
        fallback_telemetry = telemetry or {}
        try:
            reply, fallback_telemetry, _feedback = self.engine.generate_response(
                user_message=self._build_conversational_fallback_prompt(request_text),
                context=fallback_context,
            )
            parsed = self._parse_json(reply)
            if isinstance(parsed, dict) and (parsed.get("tool") or parsed.get("input")):
                reply_text = self._conversational_local_scope_hint()
            elif isinstance(parsed, dict) and ("final" in parsed or "reply" in parsed):
                reply_text = self._unwrap_nested_final_text(
                    str(parsed.get("final") or parsed.get("reply") or "")
                )
            else:
                reply_text = self._unwrap_nested_final_text(str(reply or ""))
        except Exception:
            reply_text = ""

        if not reply_text or self._looks_like_tool_followup_drift(reply_text):
            reply_text = self._conversational_local_scope_hint()

        self.history.append({"role": "assistant", "final": reply_text})
        result = {
            "status": "ok",
            "final": reply_text,
            "reply": reply_text,
            "tool_trace": list(tool_trace),
            "telemetry": fallback_telemetry or telemetry or {},
        }
        self._emit_stream_event(
            event_sink,
            "turn_result",
            result=dict(result),
            status=str(result.get("status") or "ok"),
            final=reply_text,
            reply=reply_text,
        )
        return result

    def _looks_like_action_request(self, user_message: str) -> bool:
        text = self._action_detection_text(user_message)
        if not text.strip():
            return False
        low = text.lower()
        action_terms = (
            "create",
            "make",
            "write",
            "save",
            "put",
            "delete",
            "remove",
            "rename",
            "move",
            "run",
            "execute",
            "command",
        )
        scope_terms = (
            "file",
            "folder",
            "directory",
            "desktop",
            "documents",
            "downloads",
            "path",
            "c:\\",
            "/",
        )
        return any(t in low for t in action_terms) and any(t in low for t in scope_terms)

    def _action_detection_text(self, user_message: str) -> str:
        text = str(user_message or "").strip()
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n")
        last_user = None
        for match in re.finditer(r"(?i)\buser\s*:\s*", normalized):
            last_user = match
        if last_user is None:
            return normalized
        segment = normalized[last_user.end() :]
        cutoff = re.search(r"(?i)\b(?:engine|assistant|system)\s*:\s*", segment)
        if cutoff:
            segment = segment[: cutoff.start()]
        focused = segment.strip()
        return focused or normalized

    def _looks_like_explicit_local_action_request(self, user_message: str) -> bool:
        text = self._action_detection_text(user_message)
        if not text.strip():
            return False
        low = text.lower()
        action_terms = (
            "run",
            "execute",
            "check",
            "inspect",
            "show",
            "list",
            "read",
            "open",
            "find",
            "search",
            "print",
            "fetch",
            "get",
            "create",
            "make",
            "write",
            "save",
            "put",
            "delete",
            "remove",
            "rename",
            "move",
        )
        scope_terms = (
            "file",
            "files",
            "folder",
            "directory",
            "desktop",
            "documents",
            "downloads",
            "path",
            "system",
            "os",
            "computer",
            "windows",
            "architecture",
            "environment",
            "env",
            "process",
            "service",
            "browser",
            "page",
            "url",
            "command",
            "shell",
            "powershell",
            "cmd",
            "python",
            "machine",
            "pc",
            "local",
        )
        filename_like = bool(re.search(r"\b[\w\-. ]+\.[A-Za-z0-9]{1,8}\b", text))
        path_like = bool(re.search(r"[A-Za-z]:\\", text)) or ("\\" in text) or ("/" in text)
        return any(term in low for term in action_terms) and (
            any(term in low for term in scope_terms) or filename_like or path_like
        )

    def _extract_explicit_path(self, text: str) -> Path | None:
        if not text:
            return None
        match = re.search(r'([A-Za-z]:\\[^"\n\r]+)', text)
        if match:
            raw = match.group(1).strip().rstrip('".,;')
            if raw:
                return Path(raw).expanduser()
        return None

    def _clean_entity_name(self, value: str, *, strip_content: bool = False) -> str:
        name = str(value or "").strip().strip('".,;:')
        if not name:
            return ""

        lowered = name.lower()
        for marker in ("you can call it", "call it", "name it", "called", "named"):
            idx = lowered.rfind(marker)
            if idx > 0:
                candidate = name[idx + len(marker) :].strip().strip('".,;:')
                if candidate:
                    name = candidate
                    lowered = name.lower()
                    break

        if strip_content:
            name_clipped = name[:512]
            lowered_clipped = name_clipped.lower()
            content_markers = (
                " containing",
                "\tcontaining",
                " with content",
                "\twith content",
                " that says",
                "\tthat says",
                " saying",
                "\tsaying",
            )
            content_index = min(
                (idx for marker in content_markers if (idx := lowered_clipped.find(marker)) >= 0),
                default=-1,
            )
            if content_index >= 0:
                name = name[:content_index].strip().strip('".,;:')
                lowered = name.lower()

        lowered_clipped = name[:512].lower()
        location_markers = tuple(
            f" {prep} {article}{folder}"
            for prep in ("on", "in", "at", "to")
            for article in ("", "my ", "the ")
            for folder in ("desktop", "documents", "downloads")
        ) + tuple(
            f"\t{prep} {article}{folder}"
            for prep in ("on", "in", "at", "to")
            for article in ("", "my ", "the ")
            for folder in ("desktop", "documents", "downloads")
        )
        location_index = min(
            (idx for marker in location_markers if (idx := lowered_clipped.find(marker)) >= 0),
            default=-1,
        )
        if location_index >= 0:
            name = name[:location_index].strip().strip('".,;:')
            lowered = name.lower()

        filler_prefixes = (
            "just a ",
            "just an ",
            "just ",
            "a ",
            "an ",
            "new ",
            "empty ",
        )
        changed = True
        while changed and name:
            changed = False
            lowered = name.lower()
            for prefix in filler_prefixes:
                if lowered.startswith(prefix):
                    name = name[len(prefix) :].strip().strip('".,;:')
                    changed = True
                    break

        tokens = name.split()
        while tokens and tokens[-1].lower() in {"on", "to", "at", "in", "my", "the"}:
            tokens.pop()
        return " ".join(tokens).strip().strip('".,;:')

    def _extract_filename(self, text: str) -> str | None:
        patterns = (
            r'(?:you can\s+)?call(?: it)?\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
            r'(?:named|called|name it|file name|filename)\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
            r'file\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            name = self._clean_entity_name(match.group(1) or "", strip_content=True)
            if not name:
                continue
            if name:
                return name
        return None

    def _extract_file_content(self, text: str) -> str:
        patterns = (
            r'(?:containing|with content|that says|saying)\s+["\'](.+?)["\']',
            r'(?:containing|with content|that says|saying)\s+(.+)$',
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            content = (match.group(1) or "").strip()
            if content:
                return content
        return ""

    def _extract_folder_name(self, text: str) -> str | None:
        patterns = (
            r'(?:you can\s+)?call(?: it)?\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
            r'(?:name it)\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
            r'(?:folder|directory)\s+(?:named|called)\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
            r'(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:folder|directory)\s+["\']?([A-Za-z0-9 _\.\-]{1,180})',
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            name = self._clean_entity_name(match.group(1) or "")
            if name:
                return name
        return None

    def _default_base_path(self, low_text: str) -> Path:
        def _windows_user_folder(folder_name: str) -> Path:
            candidates: list[Path] = []
            env = os.environ
            user_profile = env.get("USERPROFILE")

            if user_profile:
                candidates.append(Path(user_profile) / folder_name)
            candidates.append(Path.home() / folder_name)

            for candidate in candidates:
                try:
                    if candidate.exists():
                        return candidate
                except Exception:
                    continue
            return candidates[0] if candidates else Path.cwd()

        if "desktop" in low_text:
            return _windows_user_folder("Desktop")
        if "documents" in low_text:
            return _windows_user_folder("Documents")
        if "downloads" in low_text:
            return _windows_user_folder("Downloads")
        # Keep unspecified fallback writes out of the repo root.
        return Path.cwd() / "artifacts" / "fs_write_fallbacks"

    def _align_desktop_like_path(self, raw_path: str, request_text: str = "") -> str:
        path_text = str(raw_path or "").strip()
        if not path_text:
            return path_text

        normalized = path_text.replace("/", "\\")
        lower = normalized.lower()
        request_lower = str(request_text or "").lower()

        folder_name = ""
        for candidate in ("desktop", "documents", "downloads"):
            if candidate in request_lower or f"\\{candidate}\\" in lower or lower.endswith(f"\\{candidate}"):
                folder_name = candidate
                break

        if not folder_name:
            return path_text

        base = self._default_base_path(folder_name)
        try:
            resolved_base = base.expanduser().resolve()
        except Exception:
            resolved_base = base.expanduser()

        leaf = Path(normalized).name.strip().strip('".,;:')
        if not leaf or leaf.lower() in {"desktop", "documents", "downloads", "admin", "users"}:
            return str(resolved_base)
        return str(resolved_base / leaf)

    def _fallback_execute_action(self, user_message: str) -> Dict[str, Any]:
        text = str(user_message or "").strip()
        if not text:
            return {"status": "error", "error": "empty_action_request"}

        low = text.lower()
        looks_like_folder_create = (
            any(term in low for term in ("folder", "directory"))
            and any(term in low for term in ("create", "make", "mkdir"))
        )
        looks_like_file_create = (
            "file" in low
            and any(term in low for term in ("create", "make", "write", "save", "put"))
        )
        if not looks_like_file_create and not looks_like_folder_create:
            return {"status": "error", "error": "unsupported_action_type"}

        if looks_like_folder_create and not looks_like_file_create:
            explicit_path = self._extract_explicit_path(text)
            if explicit_path is not None:
                target = explicit_path
            else:
                folder_name = self._extract_folder_name(text) or "New Folder"
                target = self._default_base_path(low) / folder_name
            try:
                target = target.expanduser().resolve()
            except Exception:
                target = target.expanduser()
            try:
                target.mkdir(parents=True, exist_ok=True)
                return {
                    "status": "ok",
                    "action": "fs_mkdir",
                    "path": str(target),
                    "exists": target.exists(),
                    "message": f"Created folder at {target}",
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "fs_mkdir",
                    "path": str(target),
                    "error": str(exc),
                    "message": f"Failed to create folder at {target}: {exc}",
                }

        explicit_path = self._extract_explicit_path(text)
        if explicit_path is not None:
            target = explicit_path
        else:
            filename = self._extract_filename(text) or "new_file"
            if "." not in Path(filename).name and any(t in low for t in ("text file", ".txt", "txt")):
                filename = f"{filename}.txt"
            base = self._default_base_path(low)
            target = base / filename

        try:
            target = target.expanduser().resolve()
        except Exception:
            target = target.expanduser()

        content = self._extract_file_content(text)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {
                "status": "ok",
                "action": "fs_write",
                "path": str(target),
                "bytes": len(content.encode("utf-8")),
                "exists": target.exists(),
                "message": f"Created file at {target}",
            }
        except Exception as exc:
            return {
                "status": "error",
                "action": "fs_write",
                "path": str(target),
                "error": str(exc),
                "message": f"Failed to create file at {target}: {exc}",
            }

    def _normalize_placeholder_fs_path(self, raw_path: str, request_text: str = "") -> str:
        path_text = str(raw_path or "").strip()
        if not path_text:
            return path_text

        normalized = path_text.replace("/", "\\")
        lower = normalized.lower()
        folder_name = None
        suffix = ""

        for candidate in ("desktop", "documents", "downloads"):
            marker = f"\\users\\yourusername\\{candidate}"
            idx = lower.find(marker)
            if idx >= 0:
                folder_name = candidate
                suffix = normalized[idx + len(marker) :]
                break

        if folder_name is None:
            for candidate in ("desktop", "documents", "downloads"):
                marker = f"\\{candidate}"
                if lower.endswith(marker):
                    continue
                placeholder = f"yourusername\\{candidate}"
                idx = lower.find(placeholder)
                if idx >= 0:
                    folder_name = candidate
                    suffix = normalized[idx + len(placeholder) :]
                    break

        if folder_name is None:
            low_request = str(request_text or "").lower()
            if "desktop" in low_request and "yourusername" in lower:
                folder_name = "desktop"
            elif "documents" in low_request and "yourusername" in lower:
                folder_name = "documents"
            elif "downloads" in low_request and "yourusername" in lower:
                folder_name = "downloads"
            if folder_name:
                marker = f"yourusername\\{folder_name}"
                idx = lower.find(marker)
                suffix = normalized[idx + len(marker) :] if idx >= 0 else ""

        if not folder_name:
            return self._align_desktop_like_path(path_text, request_text)

        target_base = self._default_base_path(folder_name).expanduser()
        try:
            resolved_base = target_base.resolve()
        except Exception:
            resolved_base = target_base

        suffix = suffix.lstrip("\\/")
        normalized_path = str(resolved_base / suffix) if suffix else str(resolved_base)
        return self._align_desktop_like_path(normalized_path, request_text)

    def _normalize_tool_input(self, tool_name: str, payload: Dict[str, Any], request_text: str = "") -> Dict[str, Any]:
        safe_payload = dict(payload if isinstance(payload, dict) else {})
        lowered = str(tool_name or "").strip().lower()

        if lowered == "bridge_local":
            mode, data = self._normalize_bridge_payload(safe_payload)
            normalized_input: Dict[str, Any] = {"mode": mode, "data": dict(data)}
            if mode in {"fs_write", "fs_read", "fs_list", "fs_mkdir"}:
                path_value = str(normalized_input["data"].get("path") or "").strip()
                if not path_value and mode == "fs_mkdir":
                    path_value = str(normalized_input["data"].get("name") or "").strip()
                if path_value:
                    normalized_input["data"]["path"] = self._normalize_placeholder_fs_path(path_value, request_text)
            return normalized_input

        if lowered == "run_shell":
            command = str(safe_payload.get("command") or "")
            normalized_command = command
            replacements = {
                "C:\\Users\\YourUsername\\Desktop": self._normalize_placeholder_fs_path(
                    "C:\\Users\\YourUsername\\Desktop", request_text
                ),
                "C:\\Users\\YourUsername\\Documents": self._normalize_placeholder_fs_path(
                    "C:\\Users\\YourUsername\\Documents", request_text
                ),
                "C:\\Users\\YourUsername\\Downloads": self._normalize_placeholder_fs_path(
                    "C:\\Users\\YourUsername\\Downloads", request_text
                ),
            }
            for placeholder, real_path in replacements.items():
                if placeholder in normalized_command:
                    normalized_command = normalized_command.replace(placeholder, real_path)
            safe_payload["command"] = normalized_command
            return safe_payload

        return safe_payload

    def _safe_file_bridge_override(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        request_text: str = "",
    ) -> tuple[str, Dict[str, Any]] | None:
        lowered = str(tool_name or "").strip().lower()
        if lowered != "run_shell":
            return None

        safe_payload = dict(payload if isinstance(payload, dict) else {})
        command = str(safe_payload.get("command") or "").strip()
        if not command:
            return None

        request_low = str(request_text or "").lower()
        command_low = command.lower()
        explicit_shell_terms = ("shell", "powershell", "command prompt", "cmd.exe", "terminal")
        if any(term in request_low for term in explicit_shell_terms):
            return None

        list_markers = ("get-childitem", "dir", "gci")
        read_markers = ("get-content", "type ", "gc ")

        if any(marker in command_low for marker in list_markers):
            browse_verbs = ("show", "list", "inspect", "browse", "what", "current")
            browse_terms = ("file", "files", "folder", "folders", "directory", "directories")
            if not any(verb in request_low for verb in browse_verbs) or not any(term in request_low for term in browse_terms):
                return None

            path_value = "."
            explicit_path = self._extract_explicit_path(request_text)
            if explicit_path is not None:
                path_value = str(explicit_path)
            elif any(folder in request_low for folder in ("desktop", "documents", "downloads")):
                path_value = str(self._default_base_path(request_low))

            return (
                "bridge_local",
                {
                    "mode": "fs_list",
                    "data": {"path": self._normalize_placeholder_fs_path(path_value, request_text)},
                },
            )

        if any(marker in command_low for marker in read_markers):
            path_value = ""
            explicit_path = self._extract_explicit_path(request_text)
            if explicit_path is not None:
                path_value = str(explicit_path)
            else:
                filename = self._extract_filename(request_text) or ""
                if filename:
                    base = self._default_base_path(request_low)
                    path_value = str(base / filename) if any(
                        folder in request_low for folder in ("desktop", "documents", "downloads")
                    ) else filename

            if not path_value:
                return None

            return (
                "bridge_local",
                {
                    "mode": "fs_read",
                    "data": {"path": self._normalize_placeholder_fs_path(path_value, request_text)},
                },
            )

        return None

    def _tool_catalog(self) -> str:
        specs = self.registry.list_specs()
        parts: list[str] = []
        for spec in specs:
            schema = spec.input_schema if isinstance(spec.input_schema, dict) else {}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = schema.get("required", []) if isinstance(schema, dict) else []
            fields: list[str] = []
            if isinstance(props, dict):
                for key in list(props.keys())[:8]:
                    marker = "*" if key in required else ""
                    fields.append(f"{key}{marker}")
            field_text = ", ".join(fields) if fields else "object"
            if isinstance(props, dict) and len(props) > 8:
                field_text += ", ..."
            parts.append(f"- {spec.name}: {spec.description} | input: {field_text}")

        if self.memory_forge:
            mem_tools = self.memory_forge.list_tools().get("tools", [])
            parts.extend(
                f"- {tool['name']} (dynamic): {tool['description']} | input: object"
                for tool in mem_tools
            )

        return "\n".join(parts)

    def _tool_examples(self) -> str:
        specs = {spec.name for spec in self.registry.list_specs()}
        examples: list[str] = []
        if "run_cc_command" in specs:
            examples.append(
                '{"tool":"run_cc_command","input":{"action":"search_files","root":".","query":"TODO","recursive":true}}'
            )
            examples.append('{"tool":"run_cc_command","input":{"action":"fs_list","path":"."}}')
        if "run_shell" in specs:
            examples.append('{"tool":"run_shell","input":{"command":"Get-ChildItem -Force","cwd":"."}}')
        if "bridge_local" in specs:
            examples.append(
                '{"tool":"bridge_local","input":{"mode":"fs_write","data":{"path":"./tmp_note.txt","content":"hello"}}}'
            )
            examples.append(
                '{"tool":"bridge_local","input":{"mode":"fs_mkdir","data":{"path":"./tmp_folder"}}}'
            )
            examples.append(
                '{"tool":"bridge_local","input":{"mode":"browser_inspect","data":{"url":"https://example.com"}}}'
            )
            examples.append(
                '{"tool":"bridge_local","input":{"mode":"browser_action","data":{"action":"click","role":"button","name":"Search"}}}'
            )
        if "forge_create" in specs and "forge_run" in specs:
            examples.append(
                '{"tool":"forge_create","input":{"name":"tmp_math","code":"def run(payload):\\n    return {\\"sum\\": payload.get(\\"a\\",0)+payload.get(\\"b\\",0)}","description":"temporary adder"}}'
            )
            examples.append('{"tool":"forge_run","input":{"name":"tmp_math","payload":{"a":2,"b":3}}}')
        if not examples:
            examples.append('{"tool":"<tool_name>","input":{}}')
        return "\n".join(f"- {item}" for item in examples)

    def _build_prompt(self, user_message: str) -> str:
        preamble = SYSTEM_PREAMBLE.format(
            tools=self._tool_catalog(),
            tool_examples=self._tool_examples(),
        )
        # Avoid feeding raw prior tool payloads back into the model prompt.
        # Long echoed histories can recursively amplify repetitive phrasing.
        return f"{preamble}\nUSER:\n{user_message}"

    def _build_step_input(
        self,
        *,
        current_input: str,
        initial_request: str,
        tool_trace: List[Dict[str, Any]],
    ) -> str:
        if not tool_trace:
            return current_input
        completed_tools = ", ".join(
            str(item.get("tool") or "?")
            for item in tool_trace
            if isinstance(item, dict) and str(item.get("tool") or "").strip()
        )
        return (
            "Continue the same local task until it is fully completed.\n\n"
            f"ORIGINAL_REQUEST:\n{initial_request}\n\n"
            f"LATEST_STEP_CONTEXT:\n{current_input}\n\n"
            f"TOOLS_ALREADY_USED:\n{completed_tools or 'none'}\n\n"
            "If more local actions are still needed, return the next tool call JSON.\n"
            "Return `{\"final\": ...}` only when the full original request is done."
        )

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"error": "empty_response"}
        try:
            return json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
        return {"error": "invalid_json", "raw": text}

    def _call_tool(
        self,
        name: str,
        payload: Dict[str, Any],
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        """Prioritizes in-memory tools, falling back to the registry."""
        if self.memory_forge and name in self.memory_forge._tools:
            run_tool = self.memory_forge.run_tool
            try:
                signature = inspect.signature(run_tool)
                supports_event_sink = "event_sink" in signature.parameters or any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
            except (TypeError, ValueError):
                supports_event_sink = False
            if supports_event_sink:
                return run_tool(name, payload, event_sink=event_sink)
            return run_tool(name, payload)

        call = self.registry.call
        try:
            signature = inspect.signature(call)
            supports_event_sink = "event_sink" in signature.parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            supports_event_sink = False
        if supports_event_sink:
            return call(name, payload, event_sink=event_sink)
        return call(name, payload)

    def _call_tool_with_optional_event_sink(
        self,
        name: str,
        payload: Dict[str, Any],
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        call_tool = self._call_tool
        try:
            signature = inspect.signature(call_tool)
            supports_event_sink = "event_sink" in signature.parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            supports_event_sink = False
        if supports_event_sink:
            return call_tool(name, payload, event_sink=event_sink)
        return call_tool(name, payload)

    def _unwrap_nested_final_text(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        parsed = self._parse_json(raw)
        if isinstance(parsed, dict):
            nested = parsed.get("final") or parsed.get("reply")
            if nested is not None:
                return str(nested).strip()
        return raw

    def _result_path(self, result: Dict[str, Any]) -> str:
        safe_result = result if isinstance(result, dict) else {}
        nested = safe_result.get("result") if isinstance(safe_result.get("result"), dict) else {}
        return str(nested.get("path") or safe_result.get("path") or "").strip()

    def _bridge_result_payload(self, result: Dict[str, Any]) -> Dict[str, Any]:
        safe_result = result if isinstance(result, dict) else {}
        nested = safe_result.get("result") if isinstance(safe_result.get("result"), dict) else {}
        return nested or safe_result

    def _browser_inspect_fallback_reply(self, tool_result: Dict[str, Any], request_text: str) -> str:
        payload = self._bridge_result_payload(tool_result)
        title = str(payload.get("title") or "").strip()
        url = str(payload.get("url") or payload.get("current_url") or "").strip()
        visible_text = re.sub(r"\s+", " ", str(payload.get("visible_text") or "").strip())
        request_low = str(request_text or "").lower()

        if title:
            if "title" in request_low:
                return f"The page title is {title}."
            if visible_text:
                excerpt = visible_text[:180].rstrip(" .,;:")
                if excerpt:
                    return f"I inspected {url or 'the page'}; the title is {title}, and the page says: {excerpt}."
            return f"I inspected {url or 'the page'}; the title is {title}."

        if visible_text:
            excerpt = visible_text[:180].rstrip(" .,;:")
            if excerpt:
                return f"I inspected {url or 'the page'}; visible text starts with: {excerpt}."
        return ""

    def _fs_list_fallback_reply(self, tool_result: Dict[str, Any]) -> str:
        payload = self._bridge_result_payload(tool_result)
        entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
        names = [
            str(entry.get("name") or "").strip()
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("name") or "").strip()
        ]
        if not names:
            return "I checked the folder; it looks empty."
        preview = ", ".join(names[:10])
        if len(names) > 10:
            preview += ", ..."
        return f"Here are the current files: {preview}."

    def _looks_like_tool_followup_drift(self, text: str) -> bool:
        visible = str(text or "").strip()
        if not visible:
            return True
        low = visible.lower()
        suspicious_markers = (
            "flatmap(",
            "commit_hash",
            "httpconnectionpool",
            "max retries exceeded",
            "diff --git",
            "\"tool_trace\"",
            "\"stdout\"",
            "\"stderr\"",
            "traceback",
            "winerror 10061",
        )
        if any(marker in low for marker in suspicious_markers):
            return True
        if low.startswith("<unused") and low.endswith(">"):
            return True
        if visible.startswith("{") or visible.startswith("["):
            return True
        return False

    def _postprocess_tool_driven_final(self, final_text: str, tool_trace: List[Dict[str, Any]], request_text: str) -> str:
        visible = self._unwrap_nested_final_text(final_text)
        if not tool_trace:
            return visible or str(final_text or "")

        last_trace = tool_trace[-1] if isinstance(tool_trace[-1], dict) else {}
        tool_name = str(last_trace.get("tool") or "").strip().lower()
        tool_input = last_trace.get("input") if isinstance(last_trace.get("input"), dict) else {}
        tool_result = last_trace.get("result") if isinstance(last_trace.get("result"), dict) else {}

        if tool_name == "bridge_local":
            mode = str(tool_input.get("mode") or "").strip().lower()
            if mode == "browser_inspect":
                payload = self._bridge_result_payload(tool_result)
                title = str(payload.get("title") or "").strip()
                request_low = str(request_text or "").lower()
                needs_title = "title" in request_low
                if title and title.lower() not in visible.lower() and (
                    needs_title or self._looks_like_tool_followup_drift(visible)
                ):
                    fallback = self._browser_inspect_fallback_reply(tool_result, request_text)
                    if fallback:
                        return fallback
            if mode == "fs_list" and self._looks_like_tool_followup_drift(visible):
                fallback = self._fs_list_fallback_reply(tool_result)
                if fallback:
                    return fallback

        return visible or str(final_text or "")

    def _postprocess_confirmation_response(
        self,
        pending: PendingAction,
        tool_result: Dict[str, Any],
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        status = str(response.get("status") or "")
        repeated_pending = response.get("pending_action") if isinstance(response.get("pending_action"), dict) else {}
        same_tool_requeued = (
            status == "confirmation_required"
            and str(repeated_pending.get("tool") or "") == pending.tool
            and (repeated_pending.get("input") or {}) == pending.input
        )

        if same_tool_requeued:
            self._pending_action = None
            response = {
                "status": "ok",
                "tool_trace": list(response.get("tool_trace") or []),
                "telemetry": dict(response.get("telemetry") or {}),
            }
            status = "ok"

        if status != "ok":
            return response

        visible = self._unwrap_nested_final_text(str(response.get("final") or response.get("reply") or ""))
        if pending.tool == "bridge_local":
            mode = str(pending.input.get("mode") or "").strip().lower()
            if mode == "browser_inspect":
                title = str(self._bridge_result_payload(tool_result).get("title") or "").strip()
                request_low = str(pending.original_request or "").lower()
                needs_title = "title" in request_low
                if title and title.lower() not in visible.lower() and (
                    needs_title or self._looks_like_tool_followup_drift(visible)
                ):
                    fallback = self._browser_inspect_fallback_reply(tool_result, pending.original_request)
                    if fallback:
                        response["final"] = fallback
                        response["reply"] = fallback
                        return response
        if visible:
            response["final"] = visible
            response["reply"] = visible

        if pending.tool == "bridge_local":
            mode = str(pending.input.get("mode") or "").strip().lower()
            path = self._result_path(tool_result)
            path_name = Path(path).name if path else ""
            if mode == "fs_mkdir":
                if not visible or (path and path not in visible and path_name and path_name not in visible):
                    fallback = f"Created folder at {path or pending.input.get('data', {}).get('path') or 'the requested path'}."
                    response["final"] = fallback
                    response["reply"] = fallback
            elif mode == "fs_write":
                if not visible or (path and path not in visible and path_name and path_name not in visible):
                    fallback = f"Wrote {path or pending.input.get('data', {}).get('path') or 'the requested file'}."
                    response["final"] = fallback
                    response["reply"] = fallback
            return response

        if pending.tool == "run_shell":
            if visible:
                return response
            stdout = str(tool_result.get("stdout") or "").strip()
            stderr = str(tool_result.get("stderr") or "").strip()
            if bool(tool_result.get("ok")) and stdout:
                fallback = stdout
            elif stderr:
                fallback = f"Command failed: {stderr}"
            else:
                fallback = "Command completed."
            response["final"] = fallback
            response["reply"] = fallback
        return response

    def get_pending_action(self) -> Dict[str, Any] | None:
        if self._pending_action is None:
            return None
        return self._pending_action.snapshot()

    def _make_confirmation_result(
        self,
        pending: PendingAction,
        *,
        telemetry: Dict[str, Any] | None = None,
        reminder: bool = False,
    ) -> Dict[str, Any]:
        lead = "Resolve the pending action first" if reminder else "Awaiting confirmation"
        reply = f"{lead}: {pending.summary}."
        return {
            "status": "confirmation_required",
            "final": reply,
            "reply": reply,
            "pending_action": pending.snapshot(),
            "tool_trace": list(pending.tool_trace),
            "telemetry": telemetry or {},
        }

    def _normalize_bridge_payload(self, payload: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        safe_payload = payload if isinstance(payload, dict) else {}
        mode = str(safe_payload.get("mode", "") or "").strip().lower()
        data = safe_payload.get("data") if isinstance(safe_payload.get("data"), dict) else {}
        normalized_data = dict(data)

        if mode == "ui_info":
            mode = "browser_inspect"
        elif mode == "ui_access":
            has_browser_target = any(
                str(normalized_data.get(key) or "").strip()
                for key in ("url", "selector", "id", "name", "label", "role")
            ) or isinstance(normalized_data.get("target"), dict)
            mode = "browser_action" if has_browser_target else "ui"
        elif mode in {"browser_info", "browser_snapshot"}:
            mode = "browser_inspect"
        elif mode in {"browser_open", "browser_nav", "browser_navigate", "browser_go"}:
            mode = "browser_action"
            normalized_data.setdefault("action", "open")
        elif mode in {"fs_mkdir", "mkdir", "folder_create", "directory_create"}:
            mode = "fs_mkdir"
        elif mode == "fs_create":
            path_text = str(normalized_data.get("path") or "").strip()
            content_present = normalized_data.get("content") is not None
            looks_like_file = bool(content_present or (path_text and Path(path_text).suffix))
            mode = "fs_write" if looks_like_file else "fs_mkdir"

        if mode == "browser_action" and not str(normalized_data.get("action") or "").strip():
            if str(normalized_data.get("url") or "").strip():
                normalized_data["action"] = "open"
            elif any(str(normalized_data.get(key) or "").strip() for key in ("value", "text")) and (
                any(str(normalized_data.get(key) or "").strip() for key in ("selector", "id", "name", "label", "role"))
                or isinstance(normalized_data.get("target"), dict)
            ):
                normalized_data["action"] = "fill"
            elif any(str(normalized_data.get(key) or "").strip() for key in ("selector", "id", "name", "label", "role")) or isinstance(
                normalized_data.get("target"), dict
            ):
                normalized_data["action"] = "click"

        return mode, normalized_data

    def _summarize_tool_action(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = str(name or "").strip()
        safe_payload = payload if isinstance(payload, dict) else {}
        lowered = tool_name.lower()
        summary = f"run tool `{tool_name or 'unknown'}`"
        requires_confirmation = False
        risk_level = "medium"

        if lowered == "audit_crosscheck":
            return {
                "summary": "audit generated output",
                "requires_confirmation": False,
                "risk_level": "low",
            }

        if lowered == "forge_list":
            return {
                "summary": "inspect available RAM tools",
                "requires_confirmation": False,
                "risk_level": "low",
            }

        if lowered == "bridge_local":
            mode, data = self._normalize_bridge_payload(safe_payload)
            if mode == "fs_list":
                path = str(data.get("path", ".") or ".")
                return {
                    "summary": f"inspect files in `{path}`",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if mode == "fs_read":
                path = str(data.get("path", "") or "").strip() or "."
                return {
                    "summary": f"read `{path}`",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if mode == "browser_inspect":
                target = str(data.get("url") or data.get("current_url") or "active browser page").strip()
                return {
                    "summary": f"inspect `{target}` through the browser accessibility bridge",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if mode == "browser_action":
                action = str(data.get("action", "browser_action") or "browser_action").strip()
                target = str(
                    data.get("url")
                    or data.get("selector")
                    or data.get("id")
                    or data.get("name")
                    or data.get("label")
                    or data.get("target")
                    or ""
                ).strip()
                summary = f"send browser action `{action}`"
                if target:
                    summary = f"{summary} for `{target}`"
                return {
                    "summary": summary,
                    "requires_confirmation": False,
                    "risk_level": "high",
                }
            if mode == "http":
                method = str(data.get("method", "GET") or "GET").upper()
                url = str(data.get("url", "") or "").strip() or "remote endpoint"
                if method == "GET":
                    return {
                        "summary": f"fetch `{url}`",
                        "requires_confirmation": False,
                        "risk_level": "low",
                    }
                return {
                    "summary": f"send {method} request to `{url}`",
                    "requires_confirmation": False,
                    "risk_level": "high",
                }
            if mode == "fs_write":
                path = str(data.get("path", "") or "").strip() or "target file"
                return {
                    "summary": f"write `{path}`",
                    "requires_confirmation": True,
                    "risk_level": "high",
                }
            if mode == "fs_mkdir":
                path = str(data.get("path", "") or data.get("name") or "").strip() or "target folder"
                return {
                    "summary": f"create folder `{path}`",
                    "requires_confirmation": True,
                    "risk_level": "high",
                }
            if mode == "subprocess":
                cmd = data.get("cmd")
                cmd_text = "subprocess"
                if isinstance(cmd, list) and cmd:
                    cmd_text = " ".join(str(part) for part in cmd[:6])
                return {
                    "summary": f"run `{cmd_text}` through the local bridge",
                    "requires_confirmation": False,
                    "risk_level": "high",
                }
            if mode == "ui":
                action = str(data.get("action", "ui_action") or "ui_action").strip()
                return {
                    "summary": f"control the local UI ({action})",
                    "requires_confirmation": False,
                    "risk_level": "high",
                }
            summary = f"use bridge_local in `{mode or 'unknown'}` mode"
            return {
                "summary": summary,
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if lowered == "run_shell":
            command = str(safe_payload.get("command", "") or "").strip() or "shell command"
            return {
                "summary": f"run shell command `{command}`",
                "requires_confirmation": True,
                "risk_level": "high",
            }

        if lowered == "run_cc_command":
            action = str(safe_payload.get("action") or "run").strip().lower()
            if action == "search_files":
                query = str(safe_payload.get("query") or "").strip() or "file search"
                return {
                    "summary": f"search workspace files for `{query}`",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if action == "fs_list":
                root = str(safe_payload.get("root") or safe_payload.get("path") or ".").strip() or "."
                return {
                    "summary": f"list files under `{root}`",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if action == "fs_read":
                path = str(safe_payload.get("path") or "").strip() or "target file"
                return {
                    "summary": f"read `{path}` through command commissioner",
                    "requires_confirmation": False,
                    "risk_level": "low",
                }
            if action == "fs_write":
                path = str(safe_payload.get("path") or "").strip() or "target file"
                return {
                    "summary": f"write `{path}` through command commissioner",
                    "requires_confirmation": True,
                    "risk_level": "high",
                }
            if action == "fs_mkdir":
                path = str(safe_payload.get("path") or "").strip() or "target folder"
                return {
                    "summary": f"create folder `{path}` through command commissioner",
                    "requires_confirmation": True,
                    "risk_level": "high",
                }
            command = safe_payload.get("command")
            if isinstance(command, list):
                command_text = " ".join(str(part) for part in command[:6])
            else:
                command_text = str(command or "").strip()
            if not command_text:
                command_text = str(safe_payload.get("query") or "").strip() or "command commissioner task"
            if str(safe_payload.get("action") or "").strip().lower() == "search_files":
                command_text = str(safe_payload.get("query") or command_text).strip() or "file search"
            return {
                "summary": f"run command commissioner task `{command_text}`",
                "requires_confirmation": True,
                "risk_level": "high",
            }

        if lowered == "py_exec_stream":
            return {
                "summary": "execute Python code in the local runtime",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if lowered == "forge_create":
            name_text = str(safe_payload.get("name", "") or "").strip() or "RAM tool"
            return {
                "summary": f"create RAM tool `{name_text}`",
                "requires_confirmation": False,
                "risk_level": "medium",
            }

        if lowered == "forge_delete":
            name_text = str(safe_payload.get("name", "") or "").strip() or "RAM tool"
            return {
                "summary": f"delete RAM tool `{name_text}`",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if lowered == "forge_promote":
            name_text = str(safe_payload.get("name", "") or "").strip() or "RAM tool"
            return {
                "summary": f"promote RAM tool `{name_text}` into core tools",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if lowered == "forge_promote_last":
            return {
                "summary": "promote the most recently created RAM tool into core tools",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if lowered == "forge_run":
            name_text = str(safe_payload.get("name", "") or "").strip() or "RAM tool"
            return {
                "summary": f"run RAM tool `{name_text}`",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        if self.memory_forge and tool_name in self.memory_forge._tools:
            return {
                "summary": f"run dynamic RAM tool `{tool_name}`",
                "requires_confirmation": False,
                "risk_level": "high",
            }

        return {
            "summary": summary,
            "requires_confirmation": requires_confirmation,
            "risk_level": risk_level,
        }

    def _continue_run(
        self,
        *,
        next_input: str,
        run_context: Dict[str, Any],
        tool_trace: List[Dict[str, Any]],
        steps_remaining: int,
        initial_request: str | None = None,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        request_text = str(initial_request or next_input or "")
        action_request_text = self._action_detection_text(request_text)
        action_request = self._looks_like_action_request(action_request_text)
        explicit_local_action = self._looks_like_explicit_local_action_request(action_request_text)
        remaining = max(0, int(steps_remaining))

        self._emit_stream_event(
            event_sink,
            "turn_started",
            request=request_text,
            steps_remaining=remaining,
            action_request=action_request,
            explicit_local_action=explicit_local_action,
        )

        for step_idx in range(remaining):
            prompt = self._build_prompt(
                self._build_step_input(
                    current_input=next_input,
                    initial_request=request_text,
                    tool_trace=tool_trace,
                )
            )
            turn_context = dict(run_context)
            turn_context.setdefault("memory_user_message", next_input)
            suppress_memory_write = bool(
                turn_context.get("suppress_memory_write")
                or turn_context.get("interpreter_mode")
                or turn_context.get("synthetic_turn")
                or next_input.startswith("TOOL_RESULT for ")
            )
            turn_context["suppress_memory_write"] = suppress_memory_write
            if turn_context.get("synthetic_turn"):
                turn_context.setdefault("suppress_feedback_log", True)
            self._emit_stream_event(
                event_sink,
                "model_request_started",
                step=step_idx + 1,
                steps_remaining=max(0, remaining - step_idx),
                request=request_text,
            )
            reply, telemetry, _feedback = self.engine.generate_response(
                user_message=prompt, context=turn_context
            )
            self._emit_stream_event(
                event_sink,
                "model_response",
                step=step_idx + 1,
                raw_reply=reply,
                telemetry=telemetry,
            )
            data = self._parse_json(reply)
            if "final" in data:
                final_text = self._postprocess_tool_driven_final(
                    str(data["final"]),
                    tool_trace,
                    request_text,
                )
                if action_request and not tool_trace and self.allow_direct_action_fallback:
                    fallback = self._fallback_execute_action(action_request_text)
                    if fallback.get("status") == "ok":
                        tool_trace.append(
                            {
                                "tool": "direct_action_fallback",
                                "input": {"request": action_request_text},
                                "result": fallback,
                            }
                        )
                        final_text = str(fallback.get("message") or final_text)
                    else:
                        result = {
                            "status": "error",
                            "error": "action_request_not_executed",
                            "final": (
                                "Action request detected, but no tool was executed and fallback failed: "
                                + str(fallback.get("error") or "unknown")
                            ),
                            "tool_trace": tool_trace,
                            "telemetry": telemetry,
                        }
                        self._emit_stream_event(
                            event_sink,
                            "turn_result",
                            result=dict(result),
                            status="error",
                            final=str(result.get("final") or ""),
                            reply=str(result.get("final") or ""),
                            tool_trace=list(tool_trace),
                        )
                        return result
                if action_request and not tool_trace and not self.allow_direct_action_fallback:
                    result = {
                        "status": "error",
                        "error": "action_request_not_executed_no_fallback",
                        "final": (
                            "Action request detected, but no tool was executed and direct-action fallback is disabled."
                        ),
                        "tool_trace": tool_trace,
                        "telemetry": telemetry,
                    }
                    self._emit_stream_event(
                        event_sink,
                        "turn_result",
                        result=dict(result),
                        status="error",
                        final=str(result.get("final") or ""),
                        reply=str(result.get("final") or ""),
                        tool_trace=list(tool_trace),
                    )
                    return result
                self.history.append({"role": "assistant", "final": final_text})
                result = {
                    "status": "ok",
                    "final": final_text,
                    "tool_trace": tool_trace,
                    "telemetry": telemetry,
                }
                self._emit_stream_event(
                    event_sink,
                    "turn_result",
                    result=dict(result),
                    status="ok",
                    final=final_text,
                    reply=final_text,
                    tool_trace=list(tool_trace),
                )
                return result
            tool_name = data.get("tool")
            tool_input = data.get("input", {})
            if tool_name:
                normalized_input = self._normalize_tool_input(
                    str(tool_name),
                    tool_input if isinstance(tool_input, dict) else {},
                    request_text,
                )
                tool_override = self._safe_file_bridge_override(
                    str(tool_name),
                    normalized_input,
                    request_text,
                )
                if tool_override is not None:
                    tool_name, normalized_input = tool_override
                policy = self._summarize_tool_action(str(tool_name), normalized_input)
                if bool(policy.get("requires_confirmation")):
                    pending = PendingAction(
                        id=uuid4().hex,
                        tool=str(tool_name),
                        input=normalized_input,
                        summary=str(policy.get("summary") or f"run tool `{tool_name}`"),
                        risk_level=str(policy.get("risk_level") or "medium"),
                        original_request=request_text,
                        run_context=dict(run_context),
                        tool_trace=list(tool_trace),
                        steps_remaining=max(1, remaining - step_idx - 1),
                    )
                    self._pending_action = pending
                    confirmation = self._make_confirmation_result(pending, telemetry=telemetry)
                    self._emit_stream_event(
                        event_sink,
                        "confirmation_required",
                        pending_action=pending.snapshot(),
                        result=dict(confirmation),
                    )
                    self._emit_stream_event(
                        event_sink,
                        "turn_result",
                        result=dict(confirmation),
                        status="confirmation_required",
                        final=str(confirmation.get("final") or confirmation.get("reply") or ""),
                        reply=str(confirmation.get("reply") or confirmation.get("final") or ""),
                        pending_action=pending.snapshot(),
                    )
                    return confirmation
                self._emit_stream_event(
                    event_sink,
                    "tool_call_started",
                    tool=str(tool_name),
                    input=normalized_input,
                    summary=str(policy.get("summary") or ""),
                    risk_level=str(policy.get("risk_level") or "medium"),
                )
                result = self._call_tool_with_optional_event_sink(
                    tool_name,
                    normalized_input,
                    event_sink=event_sink,
                )
                self._emit_stream_event(
                    event_sink,
                    "tool_call_finished",
                    tool=str(tool_name),
                    input=normalized_input,
                    result=result,
                )
                tool_trace.append({"tool": tool_name, "input": normalized_input, "result": result})
                self.history.append({"role": "tool", "tool": tool_name, "result": result})
                next_input = f"TOOL_RESULT for {tool_name}:\n{json.dumps(result, indent=2)}"
                continue
            # If no tool/final and this looks like an action request, force local fallback execution.
            if action_request and not tool_trace and not self.allow_direct_action_fallback:
                result = {
                    "status": "error",
                    "error": "action_request_not_executed_no_fallback",
                    "final": (
                        "Action request detected, but model output was not actionable and direct-action fallback is disabled."
                    ),
                    "raw_reply": reply,
                    "tool_trace": tool_trace,
                    "telemetry": telemetry,
                }
                self._emit_stream_event(
                    event_sink,
                    "turn_result",
                    result=dict(result),
                    status="error",
                    final=str(result.get("final") or ""),
                    reply=str(result.get("final") or ""),
                    tool_trace=list(tool_trace),
                )
                return result
            if action_request and not tool_trace and self.allow_direct_action_fallback:
                self._emit_stream_event(
                    event_sink,
                    "tool_call_started",
                    tool="direct_action_fallback",
                    input={"request": action_request_text},
                    summary="execute local fallback action",
                    risk_level="medium",
                )
                fallback = self._fallback_execute_action(action_request_text)
                if fallback.get("status") == "ok":
                    tool_trace.append(
                        {
                            "tool": "direct_action_fallback",
                            "input": {"request": action_request_text},
                            "result": fallback,
                        }
                    )
                    final_text = str(fallback.get("message") or "Action executed via fallback.")
                    self.history.append({"role": "assistant", "final": final_text})
                    result = {
                        "status": "ok",
                        "final": final_text,
                        "tool_trace": tool_trace,
                        "telemetry": telemetry,
                    }
                    self._emit_stream_event(
                        event_sink,
                        "tool_call_finished",
                        tool="direct_action_fallback",
                        input={"request": action_request_text},
                        result=fallback,
                    )
                    self._emit_stream_event(
                        event_sink,
                        "turn_result",
                        result=dict(result),
                        status="ok",
                        final=final_text,
                        reply=final_text,
                        tool_trace=list(tool_trace),
                    )
                    return result
                self._emit_stream_event(
                    event_sink,
                    "tool_call_finished",
                    tool="direct_action_fallback",
                    input={"request": request_text},
                    result=fallback,
                )
                result = {
                    "status": "error",
                    "error": "action_request_not_executed",
                    "final": (
                        "Action request detected, but model output was not actionable and fallback failed: "
                        + str(fallback.get("error") or "unknown")
                    ),
                    "raw_reply": reply,
                    "tool_trace": tool_trace,
                    "telemetry": telemetry,
                }
                self._emit_stream_event(
                    event_sink,
                    "turn_result",
                    result=dict(result),
                    status="error",
                    final=str(result.get("final") or ""),
                    reply=str(result.get("final") or ""),
                    tool_trace=list(tool_trace),
                )
                return result
            # If no tool/final, return raw for non-action chat.
            result = {
                "status": "ok",
                "final": reply,
                "tool_trace": tool_trace,
                "telemetry": telemetry,
            }
            self._emit_stream_event(
                event_sink,
                "turn_result",
                result=dict(result),
                status="ok",
                final=reply,
                reply=reply,
                tool_trace=list(tool_trace),
            )
            return result

        result = {
            "status": "error",
            "error": "max_steps_exceeded",
            "tool_trace": tool_trace,
        }
        self._emit_stream_event(event_sink, "error", result=dict(result), error="max_steps_exceeded")
        self._emit_stream_event(
            event_sink,
            "turn_result",
            result=dict(result),
            status="error",
            tool_trace=list(tool_trace),
        )
        return result

    def run(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        self._emit_stream_event(
            event_sink,
            "run_started",
            message=user_message,
            agent=str(getattr(self.engine, "current_agent_name", "") or ""),
        )
        if self._pending_action is not None:
            result = self._make_confirmation_result(self._pending_action, reminder=True)
            self._emit_stream_event(
                event_sink,
                "confirmation_required",
                pending_action=self._pending_action.snapshot(),
                result=dict(result),
            )
            self._emit_stream_event(
                event_sink,
                "turn_result",
                result=dict(result),
                status="confirmation_required",
                final=str(result.get("final") or result.get("reply") or ""),
                reply=str(result.get("reply") or result.get("final") or ""),
                pending_action=self._pending_action.snapshot(),
            )
            self._emit_stream_event(
                event_sink,
                "run_finished",
                status=str(result.get("status") or ""),
                final=str(result.get("final") or result.get("reply") or ""),
            )
            return result

        run_context = dict(context or {})
        run_context.setdefault("interpreter_mode", True)
        result = self._continue_run(
            next_input=user_message,
            run_context=run_context,
            tool_trace=[],
            steps_remaining=self.max_steps,
            initial_request=user_message,
            event_sink=event_sink,
        )
        self._emit_stream_event(
            event_sink,
            "run_finished",
            status=str(result.get("status") or ""),
            final=str(result.get("final") or result.get("reply") or ""),
        )
        return result

    def stream_run(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Iterable[Dict[str, Any]]:
        queue: Queue[Dict[str, Any] | object] = Queue()
        sentinel = object()

        def _sink(event: Dict[str, Any]) -> None:
            queue.put(dict(event) if isinstance(event, dict) else {"type": "event", "payload": event})

        def _worker() -> None:
            try:
                self.run(user_message, context=context, event_sink=_sink)
            except Exception as exc:
                queue.put({"type": "error", "error": str(exc)})
            finally:
                queue.put(sentinel)

        Thread(target=_worker, daemon=True).start()
        while True:
            item = queue.get()
            if item is sentinel:
                break
            yield item

    def confirm_pending_action(
        self,
        pending_action_id: str,
        *,
        approved: bool,
        note: str = "",
        event_sink: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        pending = self._pending_action
        if pending is None:
            result = {"status": "error", "error": "no_pending_action"}
            self._emit_stream_event(event_sink, "error", result=dict(result), error="no_pending_action")
            self._emit_stream_event(event_sink, "turn_result", result=dict(result), status="error")
            return result
        if str(pending_action_id or "").strip() != pending.id:
            result = {"status": "error", "error": "pending_action_mismatch", "pending_action": pending.snapshot()}
            self._emit_stream_event(
                event_sink,
                "error",
                result=dict(result),
                error="pending_action_mismatch",
                pending_action=pending.snapshot(),
            )
            self._emit_stream_event(event_sink, "turn_result", result=dict(result), status="error")
            return result

        self._pending_action = None
        note_text = str(note or "").strip()
        if not approved:
            reply = f"Cancelled pending action: {pending.summary}."
            if note_text:
                reply = f"{reply} Note: {note_text}"
            self.history.append({"role": "assistant", "final": reply})
            result = {
                "status": "ok",
                "final": reply,
                "reply": reply,
                "tool_trace": list(pending.tool_trace),
                "cancelled": True,
            }
            self._emit_stream_event(
                event_sink,
                "turn_result",
                result=dict(result),
                status="ok",
                final=reply,
                reply=reply,
                cancelled=True,
            )
            return result

        run_context = dict(pending.run_context)
        if note_text:
            run_context["approval_note"] = note_text
        self._emit_stream_event(
            event_sink,
            "tool_call_started",
            tool=pending.tool,
            input=pending.input,
            summary=pending.summary,
            risk_level=pending.risk_level,
        )
        result = self._call_tool_with_optional_event_sink(
            pending.tool,
            pending.input,
            event_sink=event_sink,
        )
        self._emit_stream_event(
            event_sink,
            "tool_call_finished",
            tool=pending.tool,
            input=pending.input,
            result=result,
        )
        tool_trace = list(pending.tool_trace)
        tool_trace.append({"tool": pending.tool, "input": pending.input, "result": result})
        self.history.append({"role": "tool", "tool": pending.tool, "result": result})
        resumed_input = (
            f"ORIGINAL USER REQUEST:\n{pending.original_request}\n\n"
            f"TOOL_RESULT for {pending.tool}:\n{json.dumps(result, indent=2)}"
        )
        resume_sink = event_sink
        if event_sink is not None:
            def _resume_sink(event: Dict[str, Any]) -> None:
                if isinstance(event, dict) and str(event.get("type") or "") == "turn_result":
                    return
                event_sink(event)

            resume_sink = _resume_sink
        response = self._continue_run(
            next_input=resumed_input,
            run_context=run_context,
            tool_trace=tool_trace,
            steps_remaining=pending.steps_remaining,
            initial_request=pending.original_request,
            event_sink=resume_sink,
        )
        final_response = self._postprocess_confirmation_response(pending, result, response)
        self._emit_stream_event(
            event_sink,
            "turn_result",
            result=dict(final_response),
            status=str(final_response.get("status") or "ok"),
            final=str(final_response.get("final") or final_response.get("reply") or ""),
            reply=str(final_response.get("reply") or final_response.get("final") or ""),
            pending_action=pending.snapshot(),
        )
        return final_response
