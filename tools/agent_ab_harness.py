"""
Agent A/B harness for JL Engine.

Runs the same prompt multiple times for multiple agents and emits a JSONL log
plus a small summary (similarity + code-fence heuristics).

This is intentionally lightweight: it uses the existing configured brain backend
(e.g., ollama-local) via JLEngineCore, so results reflect real runtime behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from typing import Callable


_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))", re.MULTILINE)


@dataclass(frozen=True)
class TrialMetrics:
    char_len: int
    line_len: int
    fence_count: int
    fence_langs: Tuple[str, ...]
    has_any_fence: bool
    python_fence_count: int
    python_fence_compile_ok: Optional[bool]
    unknown_imports: Tuple[str, ...]
    sha256_12: str


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _extract_fences(text: str) -> List[Tuple[str, str]]:
    fences: List[Tuple[str, str]] = []
    for match in _FENCE_RE.finditer(text or ""):
        lang = (match.group(1) or "").strip().lower()
        body = match.group(2) or ""
        fences.append((lang, body))
    return fences


def _python_fence_compile_status(fences: List[Tuple[str, str]]) -> Tuple[int, Optional[bool]]:
    py_blocks = [body for lang, body in fences if (lang or "").strip().lower() in {"py", "python"}]
    if not py_blocks:
        return 0, None
    combined = "\n\n".join(py_blocks).strip()
    if not combined:
        return len(py_blocks), True
    try:
        compile(combined, "<ab_python_fence>", "exec")
        return len(py_blocks), True
    except SyntaxError:
        return len(py_blocks), False


def _unknown_imports(text: str) -> Tuple[str, ...]:
    """
    Heuristic: find `import x` / `from x import y` and flag modules that aren't importable.
    This is intentionally conservative (it may miss dynamic imports and may flag optional deps).
    """
    mods: List[str] = []
    for match in _PY_IMPORT_RE.finditer(text or ""):
        mod = (match.group(1) or match.group(2) or "").strip()
        if not mod:
            continue
        root = mod.split(".", 1)[0]
        if root and root not in mods:
            mods.append(root)
    unknown: List[str] = []
    for mod in mods:
        try:
            if importlib.util.find_spec(mod) is None:
                unknown.append(mod)
        except Exception:
            unknown.append(mod)
    return tuple(unknown)


def _compute_metrics(text: str) -> TrialMetrics:
    fences = _extract_fences(text)
    langs = tuple(lang for lang, _ in fences if lang)
    py_count, py_ok = _python_fence_compile_status(fences)
    unknown = _unknown_imports(text)
    return TrialMetrics(
        char_len=len(text or ""),
        line_len=len((text or "").splitlines()),
        fence_count=len(fences),
        fence_langs=langs,
        has_any_fence=bool(fences),
        python_fence_count=py_count,
        python_fence_compile_ok=py_ok,
        unknown_imports=unknown,
        sha256_12=_sha12(text or ""),
    )


def _pairwise_similarity(outputs: List[str]) -> List[float]:
    sims: List[float] = []
    for i in range(len(outputs)):
        for j in range(i + 1, len(outputs)):
            sims.append(SequenceMatcher(None, outputs[i], outputs[j]).ratio())
    return sims


def _summarize_similarity(outputs: List[str]) -> Dict[str, Optional[float]]:
    if len(outputs) < 2:
        return {"mean": None, "min": None, "max": None}
    sims = _pairwise_similarity(outputs)
    return {
        "mean": float(statistics.mean(sims)) if sims else None,
        "min": float(min(sims)) if sims else None,
        "max": float(max(sims)) if sims else None,
    }


def _summarize_fences(metrics: List[TrialMetrics]) -> Dict[str, Any]:
    if not metrics:
        return {
            "any_fence_rate": 0.0,
            "mean_fence_count": 0.0,
            "langs_top": [],
            "python_fence_rate": 0.0,
            "python_compile_ok_rate": None,
            "unknown_import_rate": 0.0,
            "unknown_imports_top": [],
        }
    any_rate = sum(1 for m in metrics if m.has_any_fence) / len(metrics)
    mean_count = statistics.mean([m.fence_count for m in metrics]) if metrics else 0.0
    python_fence_rate = sum(1 for m in metrics if (m.python_fence_count or 0) > 0) / len(metrics)
    compile_checks = [m.python_fence_compile_ok for m in metrics if m.python_fence_compile_ok is not None]
    python_compile_ok_rate: Optional[float] = None
    if compile_checks:
        python_compile_ok_rate = sum(1 for ok in compile_checks if ok) / len(compile_checks)

    lang_counts: Dict[str, int] = {}
    for m in metrics:
        for lang in m.fence_langs:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    langs_top = sorted(lang_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]

    unknown_count = sum(1 for m in metrics if m.unknown_imports)
    unknown_import_rate = unknown_count / len(metrics)
    unknown_mod_counts: Dict[str, int] = {}
    for m in metrics:
        for mod in m.unknown_imports:
            unknown_mod_counts[mod] = unknown_mod_counts.get(mod, 0) + 1
    unknown_imports_top = sorted(unknown_mod_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "any_fence_rate": float(any_rate),
        "mean_fence_count": float(mean_count),
        "langs_top": langs_top,
        "python_fence_rate": float(python_fence_rate),
        "python_compile_ok_rate": float(python_compile_ok_rate) if python_compile_ok_rate is not None else None,
        "unknown_import_rate": float(unknown_import_rate),
        "unknown_imports_top": unknown_imports_top,
    }


def run_agent_trials(
    *,
    agent_name: str,
    prompt: str,
    n: int,
    context: Optional[Dict[str, Any]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[List[Dict[str, Any]], List[TrialMetrics], List[str]]:
    # Ensure we import *this* repo's `jl_engine_core`, not a different checkout
    # that might be available on the user's machine/PYTHONPATH.
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from jl_engine_core.engine_core import JLEngineCore  # noqa: E402

    engine = JLEngineCore()
    raw_rows: List[Dict[str, Any]] = []
    metrics: List[TrialMetrics] = []
    outputs: List[str] = []

    for idx in range(n):
        if progress_cb:
            try:
                progress_cb({"event": "trial_start", "agent": agent_name, "trial_index": idx, "n": n})
            except Exception:
                pass
        output, telemetry, feedback = engine.generate_response(
            prompt, agent_name=agent_name, context=context
        )
        outputs.append(output)
        m = _compute_metrics(output)
        metrics.append(m)
        raw_rows.append(
            {
                "agent": agent_name,
                "trial_index": idx,
                "prompt": prompt,
                "output": output,
                "metrics": asdict(m),
                "telemetry": telemetry,
                "feedback": feedback,
            }
        )
        if progress_cb:
            try:
                progress_cb(
                    {
                        "event": "trial_done",
                        "agent": agent_name,
                        "trial_index": idx,
                        "n": n,
                        "metrics": asdict(m),
                        "output_snip": (output or "").replace("\n", " ")[:160],
                    }
                )
            except Exception:
                pass

    return raw_rows, metrics, outputs


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="JL Engine agent A/B harness")
    parser.add_argument("--agents", nargs="+", required=True, help="Agent display names")
    parser.add_argument("--n", type=int, default=5, help="Trials per agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", type=str, help="Prompt string")
    group.add_argument("--prompt-file", type=str, help="Path to a UTF-8 prompt file")
    parser.add_argument("--out-dir", type=str, default="logs/ab_runs", help="Output directory")
    parser.add_argument(
        "--context-json",
        type=str,
        default="",
        help="Optional JSON object passed as `context` to engine.generate_response()",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.n <= 0:
        raise SystemExit("--n must be > 0")

    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SystemExit("Prompt must be non-empty.")

    context: Optional[Dict[str, Any]] = None
    if args.context_json:
        loaded = json.loads(args.context_json)
        if loaded is not None and not isinstance(loaded, dict):
            raise SystemExit("--context-json must be a JSON object.")
        context = loaded

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    jsonl_path = out_dir / f"ab_{stamp}.jsonl"
    summary_path = out_dir / f"ab_{stamp}.summary.json"

    all_rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {
        "stamp": stamp,
        "agents": list(args.agents),
        "n": int(args.n),
        "prompt_sha256_12": _sha12(prompt),
        "prompt_preview": prompt.strip().replace("\r\n", "\n")[:240],
        "per_agent": {},
    }

    for agent in args.agents:
        rows, metrics, outputs = run_agent_trials(
            agent_name=agent, prompt=prompt, n=int(args.n), context=context
        )
        all_rows.extend(rows)
        summary["per_agent"][agent] = {
            "similarity": _summarize_similarity(outputs),
            "fences": _summarize_fences(metrics),
            "char_len": {
                "mean": float(statistics.mean([m.char_len for m in metrics])) if metrics else 0.0,
                "min": min([m.char_len for m in metrics]) if metrics else 0,
                "max": max([m.char_len for m in metrics]) if metrics else 0,
            },
            "sha256_12s": [m.sha256_12 for m in metrics],
        }

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[AB] Wrote {len(all_rows)} trials -> {jsonl_path}")
    print(f"[AB] Wrote summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
