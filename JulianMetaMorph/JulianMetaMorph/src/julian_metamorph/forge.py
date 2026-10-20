from __future__ import annotations

import json
from pathlib import Path

from .models import ForgedSkill, ScoutHit
from .profile import JulianProfile


class SkillForge:
    def __init__(self, *, profile: JulianProfile | None = None) -> None:
        self.profile = profile or JulianProfile()

    def forge(self, name: str, task: str, hits: list[ScoutHit], *, out_dir: str | Path = "skills") -> ForgedSkill:
        if not hits:
            raise ValueError("Cannot forge a skill without scout hits.")
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        module_path = out_path / f"{name}.py"
        manifest_path = out_path / f"{name}.json"
        source = self._build_source(name=name, task=task, hits=hits)
        manifest = self._build_manifest(name=name, task=task, hits=hits)
        module_path.write_text(source, encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return ForgedSkill(
            name=name,
            task=task,
            description=f"Julian-forged skill for task: {task}",
            module_path=module_path,
            manifest_path=manifest_path,
            source=source,
        )

    def _build_source(self, *, name: str, task: str, hits: list[ScoutHit]) -> str:
        payload = [
            {
                "repo_full_name": hit.repo_full_name,
                "path": hit.path,
                "language": hit.language,
                "license_spdx": hit.license_spdx,
                "score": hit.score,
                "symbols": list(hit.symbols),
                "why": hit.why,
                "preview": hit.preview,
            }
            for hit in hits
        ]
        payload_json = json.dumps(payload, indent=2, ensure_ascii=True)
        prompt_json = json.dumps(self.profile.render_prompt(task), ensure_ascii=True)
        task_json = json.dumps(task, ensure_ascii=True)
        return f'''"""Julian-forged skill: {name}"""

from __future__ import annotations

JULIAN_PROMPT = {prompt_json}
TASK = {task_json}
FRAGMENTS = {payload_json}

def run(inp=None):
    payload = inp or {{}}
    query = str(payload.get("query") or TASK).lower()
    limit = int(payload.get("limit") or 5)
    matches = []
    for fragment in FRAGMENTS:
        haystack = " ".join([
            fragment["repo_full_name"],
            fragment["path"],
            fragment["why"],
            fragment["preview"],
            " ".join(fragment["symbols"]),
        ]).lower()
        if query in haystack or query == TASK.lower():
            matches.append(fragment)
    if not matches:
        matches = FRAGMENTS[:limit]
    return {{
        "profile": "Julian",
        "prompt": JULIAN_PROMPT,
        "task": TASK,
        "query": query,
        "matches": matches[:limit],
    }}
'''

    def _build_manifest(self, *, name: str, task: str, hits: list[ScoutHit]) -> dict[str, object]:
        return {
            "name": name,
            "task": task,
            "profile": self.profile.name,
            "profile_prompt": self.profile.render_prompt(task),
            "sources": [
                {
                    "repo_full_name": hit.repo_full_name,
                    "path": hit.path,
                    "language": hit.language,
                    "license_spdx": hit.license_spdx,
                    "allowed": hit.allowed,
                    "score": hit.score,
                    "symbols": list(hit.symbols),
                    "why": hit.why,
                }
                for hit in hits
            ],
        }
