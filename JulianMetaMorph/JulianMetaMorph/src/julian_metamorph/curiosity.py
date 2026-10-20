from __future__ import annotations

import json
import random
from pathlib import Path


def pick_curiosity_task(seeds: tuple[str, ...], state_dir: Path) -> str:
    """
    Pick a hunt task: mostly round-robin through seeds, sometimes a random jump
    so Julian feels less mechanical.
    """
    if not seeds:
        return "open source agent tool loop patterns"

    state_dir.mkdir(parents=True, exist_ok=True)
    idx_path = state_dir / ".julian_curiosity_idx"

    try:
        idx = int(idx_path.read_text(encoding="utf-8").strip()) if idx_path.exists() else 0
    except (ValueError, OSError):
        idx = 0

    n = len(seeds)
    if random.random() < 0.28:
        task = random.choice(seeds)
    else:
        task = seeds[idx % n]
        idx = (idx + 1) % n
        try:
            idx_path.write_text(str(idx), encoding="utf-8")
        except OSError:
            pass

    return task
