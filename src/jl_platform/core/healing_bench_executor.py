import sys
import subprocess
import os
import traceback
import time
import re
import json
import ast
import hashlib
import difflib
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

try:
    import msvcrt
except Exception:  # pragma: no cover - non-Windows fallback
    msvcrt = None

# Path shim: force this repo's root + src to highest import precedence.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_DIR = _REPO_ROOT / "src"
for _p in (_REPO_ROOT, _SRC_DIR):
    if _p.exists():
        _ps = str(_p)
        while _ps in sys.path:
            sys.path.remove(_ps)
        sys.path.insert(0, _ps)

try:
    from jl_platform.core.engine import CoreEngine
    from jl_platform.core.models import CoreInput, HostContext
    from jl_engine_core import backends as engine_backends
    from jl_platform.core.tools.registry import ToolRegistry
    from jl_platform.core.tools.builtin import register_core_tools
    from jl_platform.core.tools.execution_stream import run_py_exec_stream
    from jl_platform.core.tools.audit import run_audit_tool
except ImportError:
    print("\033[91m[-] Fatal Error: Could not load JL Platform Core.\033[0m")
    sys.exit(1)


try:
    from src.tools import tool_registry
    from src.tools.adapter import register_foundation_tools

    TOOLS_AVAILABLE = True
except ImportError:
    TOOLS_AVAILABLE = False

try:
    from .healing_bench_prompts import WORKER_SYSTEM_PROMPT, SUPERVISOR_SYSTEM_PROMPT
except ImportError:
    from healing_bench_prompts import WORKER_SYSTEM_PROMPT, SUPERVISOR_SYSTEM_PROMPT

try:
    import requests
except Exception:
    requests = None


class HealingBenchExecutor:
    def __init__(self, human_verification=False):
        self.human_verification = human_verification
        self.auto_install = str(os.environ.get("BENCH_AUTO_INSTALL", "1")).strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
        )
        self.agent_name = "SparkByte"
        self.history = []
        self.last_worker_response = ""
        self.backend_id = "unknown"
        self._fallback_backend_queue: list[str] = []
        self.allow_backend_fallback = self._env_flag("BENCH_ALLOW_BACKEND_FALLBACK", True)
        self.show_plan = self._env_flag("BENCH_SHOW_PLAN", False)
        self.show_raw_output = self._env_flag("BENCH_SHOW_RAW_OUTPUT", False)
        self.session_workdir = self._resolve_session_workdir()
        self.trace_log_path = self._resolve_trace_log_path()
        self.default_worker_agent_name = "Bench Worker (Default)"
        self.active_worker_agent_name = self.default_worker_agent_name
        self.active_worker_jl_agent_file: Optional[str] = None
        self._recent_worker_output_signatures: list[str] = []
        self._worker_repeat_threshold = self._env_int(
            "BENCH_REPEAT_THRESHOLD", 3, minimum=2, maximum=6
        )
        self.clear_memory_each_turn = self._env_flag("BENCH_CLEAR_MEMORY_EACH_TURN", True)

        print("\033[90m[*] Connecting to JL Platform Core...\033[0m")
        self._load_gemini_credentials()
        self._configure_preferred_backend()
        self.engine = CoreEngine()
        engine_backends.configure_backends(brain_id=self.backend_id)
        self.request_timeout = self._initial_timeout_for_backend(self.backend_id)
        self.max_timeout = self._env_float("BENCH_MAX_TIMEOUT", max(self.request_timeout, 420.0))
        self.retry_limit = self._env_int("BENCH_RETRIES", 2, minimum=0, maximum=6)

        self.engine.register_agent(
            agent_id="bench_worker",
            agent_ref_or_blob=self._build_default_worker_agent_blob(),
        )
        self.engine.register_agent(
            agent_id="bench_supervisor",
            agent_ref_or_blob={
                "name": "Healing Bench Supervisor",
                "role": "Security & Logic Auditor",
                "system_prompt": SUPERVISOR_SYSTEM_PROMPT,
            },
        )

        self.tool_registry = ToolRegistry()
        register_core_tools(self.tool_registry)
        if TOOLS_AVAILABLE:
            register_foundation_tools(self.tool_registry)
        backend_label = self._backend_label(self.backend_id)
        key_note = ""
        if self.backend_id == "google-gemini" and not self._gemini_key_loaded:
            key_note = " (no key)"
            cfg_path = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), "../../../", "jl_engine_core", "gemini_config.json"
                )
            )
            print(
                f"\033[93m[!] Gemini key not found. Expected at: {cfg_path} or GEMINI_API_KEY env var.\033[0m"
            )
        print(
            f"\033[92m[+] JL Platform Connected. Backend: {backend_label}{key_note}. "
            f"Timeout={int(self.request_timeout)}s Retries={self.retry_limit}.\033[0m"
        )

    def _load_gemini_credentials(self) -> None:
        self._gemini_key_loaded = False
        try:
            cfg_path = str(self._service_config_path())
            data = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            file_key = data.get("gemini_api_key") or data.get("google_api_key")
            key = env_key or file_key
            model = data.get("gemini_model")
            ollama_base = os.environ.get("OLLAMA_URL") or data.get("ollama_base_url")
            ollama_model = os.environ.get("BENCH_OLLAMA_MODEL") or data.get("ollama_model")
            if key:
                os.environ.setdefault("GEMINI_API_KEY", key)
                if "google-gemini" in engine_backends.BACKEND_REGISTRY:
                    engine_backends.BACKEND_REGISTRY["google-gemini"]["google_api_key"] = key
                self._gemini_key_loaded = True
            if model and "google-gemini" in engine_backends.BACKEND_REGISTRY:
                engine_backends.BACKEND_REGISTRY["google-gemini"]["gemini_model"] = model
            if ollama_base and "ollama-local" in engine_backends.BACKEND_REGISTRY:
                normalized = self._normalize_url(ollama_base)
                engine_backends.BACKEND_REGISTRY["ollama-local"]["baseUrl"] = normalized
                engine_backends.BACKEND_REGISTRY["ollama-local"]["base_url"] = normalized
                os.environ["OLLAMA_URL"] = normalized
            if ollama_model:
                self._set_ollama_model(str(ollama_model), persist=False)
        except Exception:
            # Non-fatal: engine can still run with other backends.
            self._gemini_key_loaded = False

    def _service_config_path(self) -> Path:
        return self._repo_root() / "jl_engine_core" / "gemini_config.json"

    def _persist_service_config(self, updates: dict) -> None:
        cfg_path = self._service_config_path()
        data: dict = {}
        try:
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f) or {}
                    if isinstance(loaded, dict):
                        data = loaded
        except Exception:
            data = {}
        data.update({k: v for k, v in (updates or {}).items() if v is not None})
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _current_ollama_model(self) -> str:
        cfg = engine_backends.BACKEND_REGISTRY.get("ollama-local", {})
        return str(cfg.get("modelName") or cfg.get("model_name") or "").strip()

    def _set_ollama_model(self, model_name: str, persist: bool = True) -> bool:
        model = str(model_name or "").strip()
        if not model:
            return False
        if "ollama-local" in engine_backends.BACKEND_REGISTRY:
            engine_backends.BACKEND_REGISTRY["ollama-local"]["modelName"] = model
            engine_backends.BACKEND_REGISTRY["ollama-local"]["model_name"] = model
        os.environ["JL_OLLAMA_MODEL"] = model
        os.environ["BENCH_OLLAMA_MODEL"] = model
        if persist:
            self._persist_service_config({"ollama_model": model})
        return True

    def _list_ollama_models(self) -> list[str]:
        if requests is None:
            return []
        cfg = engine_backends.BACKEND_REGISTRY.get("ollama-local", {})
        base = cfg.get("baseUrl") or cfg.get("base_url") or "http://127.0.0.1:11434"
        url = self._normalize_url(str(base)).rstrip("/") + "/api/tags"
        try:
            resp = requests.get(
                url,
                timeout=(
                    engine_backends.OLLAMA_CONNECT_TIMEOUT,
                    min(10.0, engine_backends.OLLAMA_READ_TIMEOUT),
                ),
            )
            resp.raise_for_status()
            payload = resp.json() if getattr(resp, "content", None) else {}
            models = [
                m.get("name")
                for m in (payload.get("models") or [])
                if isinstance(m, dict) and m.get("name")
            ]
            return sorted(set(str(m).strip() for m in models if str(m).strip()))
        except Exception:
            return []

    def print_system(self, message):
        print(f"\033[96m[{self.agent_name}]\033[0m {message}")

    def _print_human_reply(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        print(f"\033[1;95m[reply]\033[0m {text}")

    def _text_signature(self, text: str) -> str:
        normalized = " ".join(str(text or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _record_worker_output(self, response_text: str) -> bool:
        sig = self._text_signature(response_text)
        self._recent_worker_output_signatures.append(sig)
        if len(self._recent_worker_output_signatures) > self._worker_repeat_threshold:
            self._recent_worker_output_signatures = self._recent_worker_output_signatures[
                -self._worker_repeat_threshold :
            ]
        if len(self._recent_worker_output_signatures) < self._worker_repeat_threshold:
            return False
        return len(set(self._recent_worker_output_signatures)) == 1

    def _reset_worker_agent(self) -> None:
        try:
            self._set_worker_agent(self.active_worker_agent_name)
        except Exception:
            self.engine.register_agent(
                agent_id="bench_worker",
                agent_ref_or_blob=self._build_default_worker_agent_blob(),
            )
            self.active_worker_agent_name = self.default_worker_agent_name
            self.active_worker_jl_agent_file = None

    def _clear_agent_agent_memory(self, agent_id: str) -> bool:
        try:
            runtime_engine = getattr(self.engine, "_engines", {}).get(agent_id)
            if runtime_engine is None:
                return False
            agent_id = str(getattr(runtime_engine, "current_agent_name", "") or "").strip()
            if not agent_id:
                return False
            memory = getattr(runtime_engine, "memory_system", None)
            if memory is None:
                return False

            # SQLite backend (preferred persistent runtime)
            if hasattr(memory, "_save_agent") and hasattr(memory, "_default_agent"):
                memory._save_agent(agent_id, memory._default_agent())  # type: ignore[attr-defined]
                return True

            # In-memory backend fallback
            if hasattr(memory, "agent_store") and isinstance(memory.agent_store, dict):  # type: ignore[attr-defined]
                memory.agent_store[agent_id] = {  # type: ignore[attr-defined]
                    "recent_interactions": [],
                    "mood": "neutral",
                    "notes": {},
                    "dynamic_state": {},
                }
                return True
        except Exception:
            return False
        return False

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _build_default_worker_agent_blob(self) -> dict:
        return {
            "name": "Bench Worker",
            "identity": {
                "name": "Bench Worker",
                "role": "Python Automation Specialist",
                "description": "Executes user tasks as runnable Python with minimal chatter.",
                "tags": ["healing-bench", "worker", "automation"],
            },
            "base_prompt": WORKER_SYSTEM_PROMPT,
            "llm_profiles": {"generic_llm": {"boot_prompt": WORKER_SYSTEM_PROMPT}},
            "system_prompt": WORKER_SYSTEM_PROMPT,
        }

    def _agent_registry_path(self) -> Path:
        return self._repo_root() / "jl_engine_core" / "data" / "agents" / "JL_Agents.mpf.json"

    def _agent_base_dir(self) -> Path:
        return self._repo_root() / "jl_engine_core" / "data" / "agents"

    def _read_json_file(self, path: Path) -> Optional[dict]:
        for encoding in ("utf-8-sig", "utf-8"):
            try:
                raw = path.read_text(encoding=encoding)
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                continue
        return None

    def _load_agent_catalog(self) -> list[dict]:
        path = self._agent_registry_path()
        if not path.exists():
            return []
        raw = self._read_json_file(path)
        if raw is None:
            return []
        if not isinstance(raw, dict):
            return []
        base = self._agent_base_dir()
        catalog: list[dict] = []
        for name in sorted(raw.keys(), key=lambda item: str(item).lower()):
            entry = raw.get(name) if isinstance(raw.get(name), dict) else {}
            jl_agent_file = str((entry or {}).get("jl_agent_file") or (entry or {}).get("agent_file") or "").strip()
            if not jl_agent_file:
                continue
            agent_path = base / jl_agent_file
            catalog.append(
                {
                    "name": str(name),
                    "jl_agent_file": jl_agent_file,
                    "path": agent_path,
                    "exists": agent_path.exists(),
                }
            )
        return catalog

    def _find_agent_entry(self, agent_name: str) -> Optional[dict]:
        target = str(agent_name or "").strip().lower()
        if not target:
            return None
        catalog = self._load_agent_catalog()
        for entry in catalog:
            if str(entry.get("name", "")).strip().lower() == target:
                return entry
        names = [str(entry.get("name", "")).strip() for entry in catalog if entry.get("name")]
        name_lut = {name.lower(): name for name in names}
        matches = difflib.get_close_matches(target, list(name_lut.keys()), n=1, cutoff=0.65)
        if matches:
            matched_name = name_lut[matches[0]]
            for entry in catalog:
                if str(entry.get("name", "")).strip() == matched_name:
                    return entry
        return None

    def _build_worker_agent_blob_from_schema(self, agent_name: str) -> Optional[tuple[dict, str]]:
        entry = self._find_agent_entry(agent_name)
        if not entry:
            return None
        path = entry.get("path")
        if not isinstance(path, Path) or not path.exists():
            return None
        raw = self._read_json_file(path)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            return None

        blob = json.loads(json.dumps(raw))
        existing_base = str(blob.get("base_prompt") or "").strip()
        blended_prompt = WORKER_SYSTEM_PROMPT
        if existing_base:
            blended_prompt += (
                "\n\nSelected agent schema context (style/domain):\n" + existing_base
            )

        llm_profiles = blob.get("llm_profiles")
        if not isinstance(llm_profiles, dict):
            llm_profiles = {}
            blob["llm_profiles"] = llm_profiles
        generic = llm_profiles.get("generic_llm")
        if not isinstance(generic, dict):
            generic = {}
            llm_profiles["generic_llm"] = generic
        generic["boot_prompt"] = blended_prompt
        blob["base_prompt"] = blended_prompt
        blob["system_prompt"] = blended_prompt
        blob["name"] = str(entry.get("name") or agent_name)
        return blob, str(entry.get("jl_agent_file") or entry.get("agent_file") or "")

    def _set_worker_agent(self, agent_name: str) -> bool:
        requested = str(agent_name or "").strip()
        if not requested:
            return False
        low = requested.lower()
        if low in {"default", "bench worker", "bench worker (default)"}:
            self.engine.register_agent(
                agent_id="bench_worker",
                agent_ref_or_blob=self._build_default_worker_agent_blob(),
            )
            self.active_worker_agent_name = self.default_worker_agent_name
            self.active_worker_jl_agent_file = None
            return True

        packed = self._build_worker_agent_blob_from_schema(requested)
        if not packed:
            return False
        blob, jl_agent_file = packed
        self.engine.register_agent(agent_id="bench_worker", agent_ref_or_blob=blob)
        self.active_worker_agent_name = str(blob.get("name") or requested)
        self.active_worker_jl_agent_file = jl_agent_file or None
        return True

    def _slash_menu_items(self) -> list[tuple[str, str]]:
        return [
            ("/status", "Show current bench settings and workspace"),
            ("/agent", "Select active worker agent schema"),
            ("/backend", "Switch backend (ollama-local / openrouter / google-gemini)"),
            ("/model", "Set active Ollama model for bench/runtime"),
            ("/models", "List available Ollama models"),
            ("/workspace", "Change active workspace folder for this session"),
            ("/confirm", "Toggle execute confirmation prompt"),
            ("/plan", "Toggle code plan preview visibility"),
            ("/raw", "Toggle raw stdout/stderr visibility"),
            ("/memory", "Toggle or clear worker memory context"),
            ("/unstick", "Reset worker context to break repetition"),
            ("/trace", "Change trace log output path"),
            ("/help", "List slash commands"),
            ("/exit", "Exit Healing Bench"),
        ]

    def _print_runtime_status(self) -> None:
        print("\033[96m[status]\033[0m")
        print(f"  backend: {self.backend_id}")
        print(f"  ollama_model: {self._current_ollama_model() or 'n/a'}")
        print(f"  retries: {self.retry_limit}")
        print(f"  timeout: {int(self.request_timeout)}s (max {int(self.max_timeout)}s)")
        print(f"  workspace: {self.session_workdir}")
        print(f"  worker_agent: {self.active_worker_agent_name}")
        if self.active_worker_jl_agent_file:
            print(f"  worker_jl_agent_file: {self.active_worker_jl_agent_file}")
        print(f"  confirm: {'on' if self.human_verification else 'off'}")
        print(f"  show_plan: {'on' if self.show_plan else 'off'}")
        print(f"  show_raw_output: {'on' if self.show_raw_output else 'off'}")
        print(
            f"  clear_memory_each_turn: {'on' if self.clear_memory_each_turn else 'off'}"
        )
        print(f"  repeat_threshold: {self._worker_repeat_threshold}")
        print(f"  trace_log: {self.trace_log_path}")

    def _read_menu_key(self) -> str:
        if msvcrt is None:
            return "enter"
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                return "enter"
            if ch == "\x1b":
                return "esc"
            if ch in ("\x00", "\xe0"):
                code = msvcrt.getwch()
                if code == "H":
                    return "up"
                if code == "P":
                    return "down"
                continue
            if ch.lower() == "q":
                return "esc"
            if ch == "\x03":
                raise KeyboardInterrupt

    def _pick_slash_command(self) -> Optional[str]:
        items = self._slash_menu_items()
        if not items:
            return None
        # Fallback for non-Windows or terminals without msvcrt.
        if msvcrt is None:
            print("\nSlash commands:")
            for idx, (name, desc) in enumerate(items, start=1):
                print(f"  {idx}. {name:<11} {desc}")
            raw = input("Select command number (blank to cancel): ").strip()
            if not raw:
                return None
            try:
                selected = int(raw)
            except ValueError:
                return None
            if selected < 1 or selected > len(items):
                return None
            return items[selected - 1][0]

        selected = 0
        print("\n\033[96m[/ menu]\033[0m Use up/down then Enter. Esc to cancel.")
        print("")
        for _ in items:
            print("")
        while True:
            sys.stdout.write(f"\033[{len(items)}A")
            for idx, (name, desc) in enumerate(items):
                marker = ">" if idx == selected else " "
                if idx == selected:
                    line = f"\033[1;95m {marker} {name:<11}\033[0m {desc}"
                else:
                    line = f" {marker} {name:<11} {desc}"
                sys.stdout.write("\033[2K\r" + line + "\n")
            sys.stdout.flush()

            key = self._read_menu_key()
            if key == "up":
                selected = (selected - 1) % len(items)
                continue
            if key == "down":
                selected = (selected + 1) % len(items)
                continue
            if key == "esc":
                return None
            if key == "enter":
                return items[selected][0]

    def _pick_worker_agent(self) -> Optional[str]:
        catalog = [entry for entry in self._load_agent_catalog() if entry.get("exists")]
        items: list[tuple[str, str]] = [
            (self.default_worker_agent_name, "Built-in Healing Bench worker profile")
        ]
        for entry in catalog:
            items.append(
                (
                    str(entry.get("name") or ""),
                    str(entry.get("jl_agent_file") or entry.get("agent_file") or ""),
                )
            )

        if msvcrt is None:
            print("\nWorker agents:")
            for idx, (name, desc) in enumerate(items, start=1):
                print(f"  {idx}. {name:<28} {desc}")
            raw = input("Select agent number (blank to cancel): ").strip()
            if not raw:
                return None
            try:
                selected = int(raw)
            except ValueError:
                return None
            if selected < 1 or selected > len(items):
                return None
            return items[selected - 1][0]

        selected = 0
        print("\n\033[96m[agent menu]\033[0m Use up/down then Enter. Esc to cancel.")
        print("")
        for _ in items:
            print("")
        while True:
            sys.stdout.write(f"\033[{len(items)}A")
            for idx, (name, desc) in enumerate(items):
                marker = ">" if idx == selected else " "
                if idx == selected:
                    line = f"\033[1;95m {marker} {name:<28}\033[0m {desc}"
                else:
                    line = f" {marker} {name:<28} {desc}"
                sys.stdout.write("\033[2K\r" + line + "\n")
            sys.stdout.flush()

            key = self._read_menu_key()
            if key == "up":
                selected = (selected - 1) % len(items)
                continue
            if key == "down":
                selected = (selected + 1) % len(items)
                continue
            if key == "esc":
                return None
            if key == "enter":
                return items[selected][0]

    def _handle_slash_command(self, raw_input: str) -> str:
        text = str(raw_input or "").strip()
        if text == "/":
            picked = self._pick_slash_command()
            if not picked:
                self.print_system("Slash menu canceled.")
                return "handled"
            text = picked

        cmd, _, arg = text.partition(" ")
        cmd = cmd.strip().lower()
        arg = arg.strip()

        if cmd == "/help":
            print("\033[96m[slash commands]\033[0m")
            for name, desc in self._slash_menu_items():
                print(f"  {name:<11} {desc}")
            return "handled"

        if cmd == "/status":
            self._print_runtime_status()
            return "handled"

        if cmd == "/agent":
            selection = str(arg or "").strip().strip('"').strip("'")
            if not selection:
                selection = self._pick_worker_agent() or ""
            if not selection:
                self.print_system("Agent selection canceled.")
                return "handled"
            if not self._set_worker_agent(selection):
                self.print_system(f"Agent not found or invalid: {selection}")
                return "handled"
            self.print_system(f"Worker agent set to: {self.active_worker_agent_name}")
            if self.active_worker_jl_agent_file:
                self.print_system(f"Schema file: {self.active_worker_jl_agent_file}")
            return "handled"

        if cmd == "/backend":
            if not arg:
                arg = input("backend id: ").strip()
            candidate = str(arg or "").strip()
            if not candidate:
                self.print_system("No backend entered.")
                return "handled"
            if not self._backend_selectable(candidate, allow_unreachable_ollama=True):
                self.print_system(f"Backend not available: {candidate}")
                return "handled"
            self.backend_id = candidate
            engine_backends.configure_backends(brain_id=candidate)
            self.request_timeout = self._initial_timeout_for_backend(candidate)
            self.print_system(f"Backend set to {self._backend_label(candidate)}.")
            return "handled"

        if cmd == "/models":
            models = self._list_ollama_models()
            if not models:
                self.print_system("No Ollama models found (or Ollama is offline).")
                return "handled"
            self.print_system("Available Ollama models:")
            for name in models:
                print(f"  - {name}")
            return "handled"

        if cmd == "/model":
            model_arg = str(arg or "").strip()
            if model_arg.lower() in {"list", "ls"}:
                models = self._list_ollama_models()
                if not models:
                    self.print_system("No Ollama models found (or Ollama is offline).")
                else:
                    self.print_system("Available Ollama models:")
                    for name in models:
                        print(f"  - {name}")
                return "handled"
            if not model_arg:
                current = self._current_ollama_model() or "unknown"
                model_arg = input(f"ollama model (current: {current}): ").strip()
            if not model_arg:
                self.print_system("No model entered.")
                return "handled"
            if not self._set_ollama_model(model_arg, persist=True):
                self.print_system("Failed to set Ollama model.")
                return "handled"
            self.print_system(f"Ollama model set to: {model_arg}")
            return "handled"

        if cmd == "/workspace":
            if not arg:
                arg = input("workspace path: ").strip()
            if not arg:
                self.print_system("No workspace path entered.")
                return "handled"
            target = Path(arg).expanduser()
            try:
                target = target.resolve()
            except Exception:
                pass
            if not target.exists() or not target.is_dir():
                self.print_system(f"Workspace not found: {target}")
                return "handled"
            try:
                os.chdir(target)
                self.session_workdir = target
                self.print_system(f"Workspace switched to: {target}")
            except Exception as exc:
                self.print_system(f"Failed to switch workspace: {exc}")
            return "handled"

        if cmd == "/confirm":
            if arg.lower() in ("on", "1", "true", "yes", "y"):
                self.human_verification = True
            elif arg.lower() in ("off", "0", "false", "no", "n"):
                self.human_verification = False
            else:
                self.human_verification = not self.human_verification
            self.print_system(
                f"Execute confirmation {'ON' if self.human_verification else 'OFF'}."
            )
            return "handled"

        if cmd == "/plan":
            if arg.lower() in ("on", "1", "true", "yes", "y"):
                self.show_plan = True
            elif arg.lower() in ("off", "0", "false", "no", "n"):
                self.show_plan = False
            else:
                self.show_plan = not self.show_plan
            self.print_system(f"Plan preview {'ON' if self.show_plan else 'OFF'}.")
            return "handled"

        if cmd == "/raw":
            if arg.lower() in ("on", "1", "true", "yes", "y"):
                self.show_raw_output = True
            elif arg.lower() in ("off", "0", "false", "no", "n"):
                self.show_raw_output = False
            else:
                self.show_raw_output = not self.show_raw_output
            self.print_system(f"Raw output {'ON' if self.show_raw_output else 'OFF'}.")
            return "handled"

        if cmd == "/memory":
            mode = arg.lower()
            if mode == "clear":
                cleared = self._clear_agent_agent_memory("bench_worker")
                self._recent_worker_output_signatures.clear()
                if cleared:
                    self.print_system("Worker memory cleared.")
                else:
                    self.print_system("Worker memory clear skipped (engine not ready).")
                return "handled"
            if mode in ("on", "1", "true", "yes", "y"):
                self.clear_memory_each_turn = True
            elif mode in ("off", "0", "false", "no", "n"):
                self.clear_memory_each_turn = False
            else:
                self.clear_memory_each_turn = not self.clear_memory_each_turn
            self.print_system(
                f"Auto-clear memory each turn {'ON' if self.clear_memory_each_turn else 'OFF'}."
            )
            return "handled"

        if cmd == "/unstick":
            self._recent_worker_output_signatures.clear()
            self._clear_agent_agent_memory("bench_worker")
            switched = False
            if self.allow_backend_fallback:
                switched = self._switch_backend("manual_unstick")
            self._reset_worker_agent()
            if switched:
                self.print_system(
                    f"Worker reset complete. Backend switched to {self._backend_label(self.backend_id)}."
                )
            else:
                self.print_system("Worker reset complete.")
            return "handled"

        if cmd == "/trace":
            if not arg:
                arg = input("trace log path: ").strip()
            if not arg:
                self.print_system("No trace log path entered.")
                return "handled"
            target = Path(arg).expanduser()
            try:
                target = target.resolve()
            except Exception:
                pass
            self.trace_log_path = target
            self.print_system(f"Trace log set to: {self.trace_log_path}")
            return "handled"

        if cmd == "/exit":
            return "exit"

        self.print_system(f"Unknown slash command: {cmd}. Use /help.")
        return "handled"

    def _configure_preferred_backend(self) -> None:
        requested = (os.environ.get("BENCH_BACKEND") or "").strip()
        prefer_local = self._env_flag("BENCH_PREFER_LOCAL", True)
        priority = []
        if requested:
            priority.append(requested)
        if prefer_local:
            priority.extend(["ollama-local", "openrouter", "google-gemini"])
        else:
            priority.extend(["openrouter", "google-gemini", "ollama-local"])
        if requested and requested not in priority:
            priority.append(requested)
        deduped = []
        seen = set()
        for backend_id in priority:
            if backend_id in seen:
                continue
            seen.add(backend_id)
            deduped.append(backend_id)

        selected = None
        for backend_id in deduped:
            allow_unreachable = bool(requested and backend_id == "ollama-local")
            if not self._backend_selectable(
                backend_id, allow_unreachable_ollama=allow_unreachable
            ):
                continue
            if not selected:
                selected = backend_id

        if not selected:
            selected = (
                "ollama-local"
                if "ollama-local" in engine_backends.BACKEND_REGISTRY
                else (
                    "google-gemini"
                    if "google-gemini" in engine_backends.BACKEND_REGISTRY
                    else next(iter(engine_backends.BACKEND_REGISTRY.keys()), "ollama-local")
                )
            )

        self.backend_id = selected
        self._fallback_backend_queue = [
            b
            for b in deduped
            if b != selected and self._backend_selectable(b, allow_unreachable_ollama=False)
        ]
        engine_backends.configure_backends(brain_id=selected)
        if selected == "ollama-local" and not self._ping_ollama():
            self.print_system(
                "Ollama did not answer ping yet; bench will retry calls and auto-switch backend if enabled."
            )

    def _backend_selectable(self, backend_id: str, allow_unreachable_ollama: bool = False) -> bool:
        if backend_id not in engine_backends.BACKEND_REGISTRY:
            return False
        if backend_id == "google-gemini" and not self._gemini_key_loaded:
            return False
        if backend_id == "openrouter":
            cfg = engine_backends.BACKEND_REGISTRY.get("openrouter", {})
            key = cfg.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY")
            if not key:
                return False
        if backend_id == "ollama-local" and not allow_unreachable_ollama and not self._ping_ollama():
            return False
        return True

    def call_agent(self, agent_id, user_input, allow_backend_switch: bool = True):
        timeout = self.request_timeout
        host = HostContext(host_type="cli_bench", privacy_mode="local")
        last_response = ""
        for attempt in range(1, self.retry_limit + 2):
            engine_backends.configure_backends(brain_id=self.backend_id)
            inp = CoreInput(
                agent_id=agent_id,
                text=user_input,
                context={
                    "timeout": timeout,
                    "backend_id": self.backend_id,
                    "bench_attempt": attempt,
                },
            )
            result = self.engine.process(inp, host, self.tool_registry)
            response = result.payload.get("text", "")
            if not self._is_backend_error(response):
                self.request_timeout = timeout
                return response
            last_response = response
            if attempt <= self.retry_limit:
                timeout = min(self.max_timeout, max(timeout + 10.0, timeout * 1.35))
                self.print_system(
                    f"Backend hiccup on attempt {attempt}/{self.retry_limit + 1}; retrying at {int(timeout)}s timeout."
                )
                time.sleep(min(2.0, 0.4 * attempt))
                continue
            break
        if allow_backend_switch and self.allow_backend_fallback and self._switch_backend(last_response):
            return self.call_agent(agent_id, user_input, allow_backend_switch=False)
        return last_response

    def _switch_backend(self, reason: str) -> bool:
        while self._fallback_backend_queue:
            candidate = self._fallback_backend_queue.pop(0)
            if not self._backend_selectable(candidate, allow_unreachable_ollama=False):
                continue
            engine_backends.configure_backends(brain_id=candidate)
            self.backend_id = candidate
            self.request_timeout = self._initial_timeout_for_backend(candidate)
            self.print_system(
                f"Switched backend to {self._backend_label(candidate)} after failure: {reason[:120]}"
            )
            return True
        return False

    def _is_backend_error(self, text: str) -> bool:
        if not isinstance(text, str):
            return True
        stripped = text.strip()
        if not stripped:
            return True
        return stripped.startswith("[ERROR:")

    def _ping_ollama(self) -> bool:
        if requests is None:
            return False
        cfg = engine_backends.BACKEND_REGISTRY.get("ollama-local", {})
        base = cfg.get("baseUrl") or cfg.get("base_url") or "http://127.0.0.1:11434"
        url = self._normalize_url(base).rstrip("/") + "/api/tags"
        try:
            resp = requests.get(
                url,
                timeout=(
                    engine_backends.OLLAMA_CONNECT_TIMEOUT,
                    min(5.0, engine_backends.OLLAMA_READ_TIMEOUT),
                ),
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def _normalize_url(self, raw: str) -> str:
        value = str(raw or "").strip()
        if not value:
            value = "http://127.0.0.1:11434"
        if not value.startswith(("http://", "https://")):
            value = f"http://{value}"
        return value.rstrip("/")

    def _initial_timeout_for_backend(self, backend_id: str) -> float:
        if backend_id == "ollama-local":
            return self._env_float("BENCH_TIMEOUT", 120.0)
        return self._env_float("BENCH_TIMEOUT", 90.0)

    def _backend_label(self, backend_id: str) -> str:
        return {
            "google-gemini": "Google Gemini",
            "openrouter": "OpenRouter",
            "ollama-local": "Ollama (Local)",
        }.get(backend_id, backend_id)

    def _env_flag(self, name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")

    def _env_float(self, name: str, default: float, minimum: float = 1.0) -> float:
        raw = os.environ.get(name)
        if raw is None:
            value = default
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = default
        return max(minimum, value)

    def _env_int(self, name: str, default: int, minimum: int = 0, maximum: int = 10) -> int:
        raw = os.environ.get(name)
        if raw is None:
            value = default
        else:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
        value = max(minimum, value)
        value = min(maximum, value)
        return value

    def _resolve_trace_log_path(self) -> Path:
        raw = str(os.environ.get("BENCH_TRACE_LOG", "") or "").strip()
        if raw:
            try:
                return Path(raw).expanduser().resolve()
            except Exception:
                return Path(raw).expanduser()
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "logs" / "healing_bench_trace.jsonl"

    def _resolve_session_workdir(self) -> Path:
        raw = str(os.environ.get("BENCH_WORKDIR", "") or "").strip()
        target = Path(raw).expanduser() if raw else Path.cwd()
        try:
            target = target.resolve()
        except Exception:
            pass
        if not target.exists() or not target.is_dir():
            target = Path.cwd()
        try:
            os.chdir(target)
        except Exception:
            pass
        return target

    def _append_trace_log(self, payload: dict) -> None:
        try:
            self.trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            event = {"ts": datetime.now(UTC).isoformat(), **payload}
            with self.trace_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _extract_json_block(self, text: str) -> dict | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _summarize_stdout(self, stdout: str) -> str:
        text = str(stdout or "").strip()
        if not text:
            return ""
        parsed = self._extract_json_block(text)
        if isinstance(parsed, dict):
            final = str(parsed.get("final") or "").strip()
            if final:
                return final
            message = str(parsed.get("message") or "").strip()
            if message:
                return message
            error = str(parsed.get("error") or "").strip()
            if error:
                return f"Execution error: {error}"
            status = str(parsed.get("status") or "").strip()
            if status:
                return f"Execution status: {status}"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return ""
        first = lines[0]
        if len(lines) == 1 and len(first) <= 280:
            return first
        if len(first) > 280:
            return first[:280] + "..."
        return first

    def _is_valid_python(self, code: str) -> bool:
        if not code or not code.strip():
            return False
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _build_interpreter_fallback_code(self, task: str, worker_response: str = "") -> str:
        task_literal = json.dumps(str(task or ""))
        response_literal = json.dumps(str(worker_response or ""))
        return (
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "cwd = Path(os.getcwd())\n"
            "src = cwd / 'src'\n"
            "for p in (cwd, src):\n"
            "    if p.exists() and str(p) not in sys.path:\n"
            "        sys.path.insert(0, str(p))\n"
            "\n"
            "from jl_platform.core.interpreter import InterpreterSession\n"
            "session = InterpreterSession()\n"
            f"task = {task_literal}\n"
            f"worker_response = {response_literal}\n"
            "result = session.run(\n"
            "    task,\n"
            "    context={\n"
            "        'task_intent': 'healing_bench_execute',\n"
            "        'action_type': 'execute',\n"
            "        'source': 'healing_bench_fallback',\n"
            "        'worker_response': worker_response,\n"
            "    },\n"
            ")\n"
            "print(json.dumps(result, indent=2))\n"
        )

    def generate_code(self, task):
        print(f"\033[90m[*] Worker is coding...\033[0m")
        if self.clear_memory_each_turn:
            self._clear_agent_agent_memory("bench_worker")
        response = self.call_agent("bench_worker", f"TASK: {task}")
        self.last_worker_response = response

        if self._record_worker_output(response):
            self.print_system("Detected repeated worker output. Attempting loop recovery.")
            self._append_trace_log(
                {
                    "event": "worker_loop_detected",
                    "backend_id": self.backend_id,
                    "worker_agent": self.active_worker_agent_name,
                    "task": task,
                    "response_preview": str(response)[:600],
                }
            )
            if self.allow_backend_fallback:
                self._switch_backend("repetitive_worker_output")
            self._reset_worker_agent()
            nonce = int(time.time() * 1000)
            recovery_prompt = (
                f"TASK: {task}\n"
                "LOOP_BREAKER: your previous output repeated. Produce fresh, materially different "
                "executable Python that solves the task. Do not repeat prior text.\n"
                f"NONCE: {nonce}"
            )
            retried = self.call_agent("bench_worker", recovery_prompt, allow_backend_switch=False)
            if str(retried or "").strip():
                response = retried
                self.last_worker_response = retried
                self._record_worker_output(retried)

        code_match = re.search(r"```python(.*?)```", response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        looks_like_code = any(
            token in response for token in ("import ", "def ", "class ", "print(", "=", "from ")
        )
        if looks_like_code and "```" not in response:
            candidate = response.strip()
            if self._is_valid_python(candidate):
                return candidate
            return self._build_interpreter_fallback_code(task, response)

        # Hard fallback: never abort a turn just because the worker answered conversationally.
        return self._build_interpreter_fallback_code(task, response)

    def review_code(self, code, task):
        # Silent auditing...
        review_prompt = f"TASK: {task}\n\nPROPOSED CODE:\n```python\n{code}\n```"
        response = self.call_agent("bench_supervisor", review_prompt)
        if self._is_backend_error(response):
            return {
                "mode": "NORMAL",
                "reason": "Supervisor unavailable due backend timeout/error; proceeding.",
            }

        response_text = str(response or "")
        upper = response_text.upper()
        if "REJECTED" in upper:
            return {"mode": "CORRECTIVE", "reason": response}
        if "APPROVED" in upper:
            return {"mode": "NORMAL", "reason": "APPROVED"}
        # Assume PASS if not explicitly rejected, keeping silent.
        return {"mode": "NORMAL", "reason": "PASS"}

    def execute(self, code):
        print(f"\033[90m[*] Executing...\033[0m")
        result = run_py_exec_stream({"code": code})
        metrics = result.get("metrics") or {}
        audit = run_audit_tool({"code": code, "output": result.get("output", "")})
        summary = self._summarize_stdout(result.get("stdout") or "")
        duration_ms = metrics.get("duration_ms")
        memory_peak = metrics.get("memory_peak_kb")

        self._append_trace_log(
            {
                "event": "execute",
                "backend_id": self.backend_id,
                "worker_agent": self.active_worker_agent_name,
                "code": code,
                "result": result,
                "audit": audit,
                "summary": summary,
            }
        )

        if result.get("error"):
            print(f"\033[91m[!]\033[0m Execution failed: {result.get('error')}")
            if summary:
                self._print_human_reply(summary)
            print(f"\033[90m[trace]\033[0m {self.trace_log_path}")
            if self.show_raw_output and result.get("traceback"):
                print(result["traceback"])
        else:
            if summary:
                self._print_human_reply(summary)
            else:
                self._print_human_reply("Execution complete.")
            if result.get("stderr"):
                stderr_line = str(result.get("stderr")).strip().splitlines()[0]
                print(f"\033[93m[warn]\033[0m {stderr_line}")
            if self.show_raw_output and result.get("stdout"):
                print(f"\033[92m[OUTPUT]\033[0m\n{result['stdout']}")
            if self.show_raw_output and result.get("stderr"):
                print(f"\033[91m[STDERR]\033[0m\n{result['stderr']}")
            if not self.show_raw_output:
                print(f"\033[90m[trace]\033[0m {self.trace_log_path}")

        if duration_ms is not None:
            print(
                f"\033[90m[perf]\033[0m duration_ms={duration_ms} memory_peak_kb={memory_peak}"
            )
        self._auto_requirements_from_result(result)

    def _auto_requirements_from_result(self, result: dict) -> None:
        trace = result.get("traceback") or ""
        stderr = result.get("stderr") or ""
        error = result.get("error") or ""
        text = "\n".join([trace, stderr, error])
        if "ModuleNotFoundError" not in text and "No module named" not in text:
            return
        missing = set()
        for line in text.splitlines():
            if "No module named" in line:
                parts = line.split("No module named", 1)
                if len(parts) > 1:
                    mod = parts[1].strip().strip(":").strip().strip("'").strip('"')
                    if mod:
                        missing.add(mod)
        if not missing:
            return
        mapping = {
            "PIL": "pillow",
            "serial": "pyserial",
            "cv2": "opencv-python",
            "sklearn": "scikit-learn",
        }
        to_add = []
        for mod in sorted(missing):
            to_add.append(mapping.get(mod, mod))
        repo_root = Path(__file__).resolve().parents[3]
        req_path = repo_root / "requirements.txt"
        existing = set()
        if req_path.exists():
            existing = {
                ln.strip().lower()
                for ln in req_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip()
            }
        added = []
        lines = []
        if req_path.exists():
            lines = req_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for pkg in to_add:
            if pkg.lower() in existing:
                continue
            lines.append(pkg)
            added.append(pkg)
        if added:
            req_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            print(f"\033[93m[+] Added to requirements.txt: {', '.join(added)}\033[0m")
            if self.auto_install:
                self._install_packages(added)

    def _install_packages(self, packages: list[str]) -> None:
        if not packages:
            return
        print(f"\033[90m[*] Installing: {', '.join(packages)}\033[0m")
        try:
            cmd = [sys.executable, "-m", "pip", "install", *packages]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr)
            if proc.returncode != 0:
                print(f"\033[91m[!] pip install failed (code {proc.returncode})\033[0m")
        except Exception as exc:
            print(f"\033[91m[!] pip install error: {exc}\033[0m")

    def run_turn(self, user_input):
        self.history.append({"role": "user", "content": user_input})

        code = self.generate_code(user_input)
        if not code.strip():
            snippet = (self.last_worker_response or "").strip().replace("\n", " ")
            if len(snippet) > 180:
                snippet = snippet[:180] + "..."
            print("\033[91m[!] No executable code produced by worker. Aborting.\033[0m")
            if snippet:
                print(f"\033[90m[worker]\033[0m {snippet}")
            return
        review_state = self.review_code(code, user_input)

        if review_state["mode"] == "CORRECTIVE":
            print(f"\033[91m[!] BLOCKED by Supervisor.\033[0m")
            print(f"Reason: {review_state['reason']}")
            return

        self._append_trace_log(
            {
                "event": "plan",
                "backend_id": self.backend_id,
                "worker_agent": self.active_worker_agent_name,
                "task": user_input,
                "review": review_state,
                "worker_response": self.last_worker_response,
                "code": code,
            }
        )
        if self.show_plan:
            print(f"\n\033[93m--- PLAN ---\033[0m\n{code}\n\033[93m------------\033[0m\n")
        else:
            self.print_system("Plan prepared. Executing.")

        if self.human_verification:
            confirmation = input(f"\033[96m[{self.agent_name}]\033[0m Execute this? (y/n): ")
            if confirmation.lower() not in ["y", "yes", ""]:
                self.print_system("Aborted.")
                return

        self.execute(code)
        self.history.append({"role": "assistant", "content": "Code executed."})

    def start_chat(self):
        backend_label = self._backend_label(self.backend_id)
        print("\n\033[1;36m=== THE HEALING BENCH ===\033[0m")
        print(f"Backend:      {backend_label}")
        print(f"Retries:      {self.retry_limit}")
        print(f"Timeout:      {int(self.request_timeout)}s (max {int(self.max_timeout)}s)")
        print("Supervisor:   Silent Watchdog Mode")
        print(f"Workspace:    {self.session_workdir}")
        print(f"Worker:       {self.active_worker_agent_name}")
        print(f"Trace Log:    {self.trace_log_path}")
        print("Slash Menu:   Type / for command picker")
        print("\n")

        self.print_system("Engine online. Give me a task.")

        while True:
            try:
                user_input = input("\n\033[1;32m>\033[0m ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    slash_result = self._handle_slash_command(user_input)
                    if slash_result == "exit":
                        self.print_system("Severing connection.")
                        break
                    if slash_result == "handled":
                        continue

                if user_input.lower() in ["exit", "quit", "bye"]:
                    self.print_system("Severing connection.")
                    break

                self.run_turn(user_input)

            except KeyboardInterrupt:
                print("\n")
                self.print_system("Interrupted.")
                break


def main():
    require_confirm = os.environ.get("BENCH_REQUIRE_CONFIRM", "").strip() in (
        "1",
        "true",
        "yes",
        "y",
    )
    engine = HealingBenchExecutor(human_verification=require_confirm)
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        engine.run_turn(task)
    else:
        engine.start_chat()


if __name__ == "__main__":
    main()
