from __future__ import annotations

import argparse
import difflib
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class MutationResult:
    file_path: Path
    description: str
    old_text: str
    new_text: str


def _python_bin(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _call_ollama(prompt: str, model: str = "dolphin3:latest") -> str | None:
    """Call Ollama to get LLM response."""
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False
    }).encode("utf-8")
    
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "").strip()
    except Exception:
        return None


def _clean_code(response: str) -> str:
    """Clean markdown formatting from LLM response."""
    code = response.strip()
    if code.startswith("```python"):
        code = code.split("```python", 1)[1]
    elif code.startswith("```"):
        code = code.split("```", 1)[1]
    if code.endswith("```"):
        code = code.rsplit("```", 1)[0]
    return code.strip()


def _extract_function(text: str, func_name: str) -> str | None:
    """Extract a function definition from source code."""
    pattern = rf"(    def {func_name}\([^)]*\).*?:(?:\n        .*)+)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


TARGET_FUNCTIONS_ENGINE = [
    "_build_messages",
    "_detect_threat",
    "_derive_trigger_from_signals",
    "_infer_action_type",
    "_maybe_refuse",
]

TARGET_FUNCTIONS_TQA = [
    "update_present_state",
    "update_future_projection", 
    "apply_biases",
    "collapse",
    "_generate_projection",
]


FORBIDDEN_MUTATION_TOKENS = [
    "weight",
    "weights",
    "drive_weights",
    "parameter",
    "parameters",
    "threshold",
    "invariant",
    "strain",
    "temperature",
    "top_p",
    "temp",
    "sampling_bias",
    "learning_rate",
    "fine_tune",
    "finetune",
    "internal_loop_interval_seconds",
    "interval_seconds",
    "loop_interval",
    "history_length",
    "max_iterations",
    "timeout",
    "sleep",
]


def _find_logic_only_violation(old_text: str, new_text: str) -> str | None:
    """Reject mutations that touch tuning/weight/parameter-style lines."""
    if old_text == new_text:
        return None
    diff_lines = difflib.ndiff(old_text.splitlines(), new_text.splitlines())
    for line in diff_lines:
        if not line.startswith("+ "):
            continue
        added = line[2:].strip()
        if not added or added.startswith("#"):
            continue
        lowered = added.lower()
        for token in FORBIDDEN_MUTATION_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                return f"forbidden_token={token} line={added[:140]}"
    return None


def _thinking_pause_seconds(interval_seconds: float) -> float:
    base = max(1.0, float(interval_seconds or 1.0))
    return max(2.0, min(12.0, base * random.uniform(1.2, 2.0)))


def mutate_function_logic(copy_root: Path) -> MutationResult | None:
    """Use LLM to rewrite actual Python function logic in engine_core.py."""
    engine_path = copy_root / "jl_engine_core" / "engine_core.py"
    if not engine_path.exists():
        return None
    
    old_text = _read_text(engine_path)
    
    func_name = random.choice(TARGET_FUNCTIONS_ENGINE)
    old_func = _extract_function(old_text, func_name)
    if not old_func:
        return None
    
    prompt = f"""You are a Python code editor. CRITICAL: Maintain EXACT indentation using spaces (4 spaces per indent level).

Rewrite this Python function to change its LOGIC:
- Keep EXACT function signature: def {func_name}(...)
- Use EXACTLY 4 spaces for each indentation level
- Change the function's behavior/logic, not just variable names
- Keep same number of lines approximately
- Do NOT change weights, parameters, thresholds, or sampling knobs (temperature/top_p/strain/invariants)
- Return ONLY raw Python code, NO markdown, NO backticks

Original (note the 4-space indentation):
{old_func}

Rewritten with different logic:"""

    new_func = _call_ollama(prompt)
    if not new_func:
        return None
    
    new_func = _clean_code(new_func)
    
    if f"def {func_name}" not in new_func:
        return None
    
    new_text = old_text[:old_text.find(old_func)] + new_func + "\n" + old_text[old_text.find(old_func) + len(old_func):]
    
    if new_text == old_text:
        return None
    
    _write_text(engine_path, new_text)
    return MutationResult(
        file_path=engine_path,
        description=f"LLM rewrote {func_name} logic",
        old_text=old_text,
        new_text=new_text,
    )


def mutate_add_new_method(copy_root: Path) -> MutationResult | None:
    """Use LLM to add a new method to the engine."""
    engine_path = copy_root / "jl_engine_core" / "engine_core.py"
    if not engine_path.exists():
        return None
    
    old_text = _read_text(engine_path)
    
    prompt = """You are a Python code editor. Add a NEW method to the JLEngineCore class.

Requirements:
- Add a method that takes (self, ...) arguments
- Use 4-space indentation
- The method should do something useful for an AI engine (e.g., analyze sentiment, adjust behavior, etc.)
- Include a docstring
- Do NOT introduce or tune weights/parameters/thresholds/sampling knobs
- Return ONLY the new method code, NO markdown, NO explanations

Example format:
    def new_method_name(self, param: str) -> str:
        \"\"\"Docstring here.\"\"\"
        # logic here
        return result

Add a new useful method:"""

    new_method = _call_ollama(prompt)
    if not new_method:
        return None
    
    new_method = _clean_code(new_method)
    
    if "def " not in new_method or "(" not in new_method:
        return None
    
    insert_pos = old_text.rfind("\n    def ")
    if insert_pos == -1:
        return None
    
    new_text = old_text[:insert_pos + 1] + "\n" + new_method + "\n" + old_text[insert_pos + 1:]
    
    _write_text(engine_path, new_text)
    return MutationResult(
        file_path=engine_path,
        description="LLM added new method",
        old_text=old_text,
        new_text=new_text,
    )


def mutate_conditionals(copy_root: Path) -> MutationResult | None:
    """Use LLM to change if/else conditions in functions."""
    engine_path = copy_root / "jl_engine_core" / "engine_core.py"
    if not engine_path.exists():
        return None
    
    old_text = _read_text(engine_path)
    
    prompt = """You are a Python code editor. Find an if/elif/else block in the JLEngineCore class and INVERT or CHANGE the condition logic.

Requirements:
- Keep same indentation (4 spaces)
- Change the LOGIC of the condition (e.g., change > to <, add OR, change and to or, etc.)
- Keep the same overall structure
- Do NOT change weights, parameters, thresholds, or sampling knobs
- Return ONLY the modified code section, NO markdown

Find and modify a condition:"""

    section = _call_ollama(prompt)
    if not section:
        return None
    
    section = _clean_code(section)
    
    if "if " not in section and "elif " not in section:
        return None
    
    new_text = old_text
    for match in re.finditer(r"(    def .+?(?=\n    def |\Z))", old_text, re.DOTALL):
        func_block = match.group(1)
        if "if " in func_block or "elif " in func_block:
            new_text = new_text.replace(func_block[:200], section[:200], 1)
            break
    
    if new_text == old_text:
        return None
    
    _write_text(engine_path, new_text)
    return MutationResult(
        file_path=engine_path,
        description="LLM modified conditionals",
        old_text=old_text,
        new_text=new_text,
    )


def mutate_tqa_logic(copy_root: Path) -> MutationResult | None:
    """Use LLM to rewrite actual Python function logic in temporal_quantum_agent.py."""
    tqa_path = copy_root / "jl_engine_core" / "temporal_quantum_agent.py"
    if not tqa_path.exists():
        return None
    
    old_text = _read_text(tqa_path)
    
    func_name = random.choice(TARGET_FUNCTIONS_TQA)
    old_func = _extract_function(old_text, func_name)
    if not old_func:
        return None
    
    prompt = f"""You are a Python code editor. Rewrite this Python function to change its LOGIC and BEHAVIOR (not just variable names).

Requirements:
- Keep the SAME function signature (def {func_name}(...) )
- Keep SAME indentation (4 spaces)
- Change HOW the function works, not just what it returns
- Add new behavior, different conditions, alternative logic paths
- Do NOT change weights, parameters, thresholds, or sampling knobs
- Return ONLY raw Python code, NO markdown, NO explanations

Original function:
{old_func}

Rewrite with different logic:"""

    new_func = _call_ollama(prompt)
    if not new_func:
        return None
    
    new_func = _clean_code(new_func)
    
    if f"def {func_name}" not in new_func:
        return None
    
    new_text = old_text[:old_text.find(old_func)] + new_func + "\n" + old_text[old_text.find(old_func) + len(old_func):]
    
    if new_text == old_text:
        return None
    
    _write_text(tqa_path, new_text)
    return MutationResult(
        file_path=tqa_path,
        description=f"LLM rewrote TQA {func_name} logic",
        old_text=old_text,
        new_text=new_text,
    )


def _compile_candidate(python_exe: Path, copy_root: Path) -> tuple[bool, str]:
    cmd = [str(python_exe), "-m", "compileall", "jl_engine_core"]
    proc = subprocess.run(
        cmd,
        cwd=str(copy_root),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


def _create_venv(venv_dir: Path) -> Path:
    python_exe = _python_bin(venv_dir)
    if python_exe.exists():
        return python_exe
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
    )
    python_exe = _python_bin(venv_dir)
    if not python_exe.exists():
        raise RuntimeError(f"venv created but python not found at {python_exe}")
    return python_exe


def _ignore_names(_: str, names: list[str]) -> list[str]:
    skip = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    return [name for name in names if name in skip]


def _sync_engine_copy(repo_root: Path, copy_root: Path) -> None:
    targets = ["jl_engine_core", "framework", "src/jl_platform/core"]
    if copy_root.exists():
        shutil.rmtree(copy_root)
    copy_root.mkdir(parents=True, exist_ok=True)
    for rel in targets:
        src = repo_root / rel
        if not src.exists():
            continue
        dst = copy_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, ignore=_ignore_names, dirs_exist_ok=True)


def _stopped(control_file: Path, stop_file: Path) -> bool:
    if stop_file.exists():
        return True
    if not control_file.exists():
        return False
    text = control_file.read_text(encoding="utf-8", errors="ignore")
    for raw in text.splitlines():
        token = raw.strip().lower()
        if token in {"shuttle", "stop=shuttle", "command:shuttle"}:
            return True
    return False


def _log(path: Path, message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {message}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(line, end="")


def run_loop(
    *,
    repo_root: Path,
    lab_dir: Path,
    interval_seconds: float,
    max_iterations: int,
    reseed_copy: bool,
) -> None:
    copy_root = lab_dir / "engine_copy"
    venv_dir = lab_dir / ".venv"
    control_file = lab_dir / "control.txt"
    stop_file = lab_dir / "SHUTTLE"
    log_file = lab_dir / "loop.log"

    lab_dir.mkdir(parents=True, exist_ok=True)
    if reseed_copy or not copy_root.exists():
        _sync_engine_copy(repo_root, copy_root)
    if not control_file.exists():
        control_file.write_text(
            "# write exactly: shuttle\n",
            encoding="utf-8",
        )

    python_exe = _create_venv(venv_dir)
    
    mutators: list[Callable[[Path], MutationResult | None]] = [
        mutate_function_logic,
        mutate_add_new_method,
        mutate_tqa_logic,
    ]

    _log(log_file, f"self-edit loop started | copy={copy_root} | venv={python_exe}")
    iteration = 0
    while True:
        if max_iterations > 0 and iteration >= max_iterations:
            _log(log_file, "max_iterations reached; stopping")
            break
        if _stopped(control_file, stop_file):
            _log(log_file, "SHUTTLE detected; stopping")
            break

        iteration += 1
        think_for = _thinking_pause_seconds(interval_seconds)
        _log(log_file, f"iter={iteration} thinking seconds={think_for:.2f}")
        time.sleep(think_for)

        mutator = random.choice(mutators)
        result = mutator(copy_root)
        if result is None:
            _log(log_file, f"iter={iteration} no-op mutator={mutator.__name__}")
            time.sleep(max(0.2, interval_seconds))
            continue

        violation = _find_logic_only_violation(result.old_text, result.new_text)
        if violation:
            _write_text(result.file_path, result.old_text)
            _log(
                log_file,
                f"iter={iteration} rejected file={result.file_path.relative_to(copy_root)} reason=logic_only_guard detail={violation}",
            )
            time.sleep(max(0.2, interval_seconds))
            continue

        ok, compile_output = _compile_candidate(python_exe, copy_root)
        if ok:
            _log(
                log_file,
                f"iter={iteration} accepted file={result.file_path.relative_to(copy_root)} change={result.description}",
            )
            generation_dir = lab_dir / "generations"
            generation_dir.mkdir(parents=True, exist_ok=True)
            snapshot = generation_dir / f"gen_{iteration:06d}_{result.file_path.name}"
            snapshot.write_text(result.new_text, encoding="utf-8")
        else:
            _write_text(result.file_path, result.old_text)
            trimmed = " ".join((compile_output or "").split())[:800]
            _log(
                log_file,
                f"iter={iteration} reverted file={result.file_path.relative_to(copy_root)} reason=compile_failed detail={trimmed}",
            )

        time.sleep(max(0.2, interval_seconds))

    _log(log_file, "self-edit loop exited")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously self-edit an isolated engine copy in a venv until SHUTTLE."
    )
    parser.add_argument("--repo-root", default=".", help="Root of the source repository.")
    parser.add_argument(
        "--lab-dir",
        default=".self_edit_lab",
        help="Working lab directory containing copy, venv, logs, and shuttle controls.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=3.0,
        help="Delay between iterations.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="0 means run forever (until SHUTTLE).",
    )
    parser.add_argument(
        "--reseed-copy",
        action="store_true",
        help="Rebuild isolated engine copy from current repo before starting.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    lab_dir = (repo_root / args.lab_dir).resolve()
    run_loop(
        repo_root=repo_root,
        lab_dir=lab_dir,
        interval_seconds=float(args.interval_seconds),
        max_iterations=int(args.max_iterations),
        reseed_copy=bool(args.reseed_copy),
    )


if __name__ == "__main__":
    main()
