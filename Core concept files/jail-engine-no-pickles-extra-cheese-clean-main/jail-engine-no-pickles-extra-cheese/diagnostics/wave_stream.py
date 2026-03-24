"""
Streaming MPF diagnostics as terminal waves.

Shows emotional/safety/memory aperture as horizontal block bars at a fixed interval.
Only standard library dependencies.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict

try:
    from engine_core import JLEngineCore
except Exception:
    JLEngineCore = None


BLOCKS = "▁▂▃▄▅▆▇█"
_ENGINE_INSTANCE = None


def value_to_bar(value: float, max_width: int = 12) -> str:
    """Convert 0.0–1.0 into a block bar with length scaled to the value."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0

    v = max(0.0, min(1.0, v))

    idx = int(v * (len(BLOCKS) - 1))
    idx = max(0, min(idx, len(BLOCKS) - 1))

    length = int(1 + v * (max_width - 1))
    return BLOCKS[idx] * max(length, 1)


def get_engine() -> Any:
    """
    Get or create a reference to the engine for diagnostics.
    Adjust if your app uses a different bootstrap.
    """
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is not None:
        return _ENGINE_INSTANCE

    if JLEngineCore is None:
        raise RuntimeError("JLEngineCore import failed; check diagnostics.wave_stream imports.")

    _ENGINE_INSTANCE = JLEngineCore()
    return _ENGINE_INSTANCE


def get_mpf_state() -> Dict[str, Any]:
    """Fetch the current MPF snapshot from the engine."""
    engine = get_engine()
    if not hasattr(engine, "get_mpf_state_snapshot"):
        raise RuntimeError("Engine is missing get_mpf_state_snapshot(); add it to JLEngineCore.")
    return engine.get_mpf_state_snapshot()


def format_wave_line(state: Dict[str, Any]) -> str:
    """Render one line of wave output from an MPF snapshot dict."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    gait = state.get("gait") or "?"
    rhythm = state.get("rhythm") or "?"
    aperture = state.get("aperture") or {}

    emo = float(aperture.get("emotional", 0.0) or 0.0)
    saf = float(aperture.get("safety", 1.0) or 0.0)
    mem = float(aperture.get("memory_focus", 0.0) or 0.0)

    emo_bar = value_to_bar(emo, max_width=14)
    saf_bar = value_to_bar(saf, max_width=10)
    mem_bar = value_to_bar(mem, max_width=10)

    return (
        f"[{ts}] "
        f"gait={gait:<6} rhythm={rhythm:<6} "
        f"emo {emo_bar:<14} "
        f"saf {saf_bar:<10} "
        f"mem {mem_bar:<10}"
    )


def run_wave_stream(interval: float = 0.2) -> None:
    """Continuously stream MPF state as wave lines to stdout."""
    print("JL ENGINE MPF WAVE STREAM – Ctrl+C to stop.")
    while True:
        try:
            state = get_mpf_state()
            line = format_wave_line(state)
            print(line, flush=True)
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nWave stream stopped by user.")
            break
        except Exception as exc:
            print(f"[wave_stream] ERROR: {exc}", flush=True)
            time.sleep(interval)


if __name__ == "__main__":
    run_wave_stream()
