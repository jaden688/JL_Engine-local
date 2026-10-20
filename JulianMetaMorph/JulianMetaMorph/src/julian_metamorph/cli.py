from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path

import uvicorn

from .curiosity import pick_curiosity_task
from .forge import SkillForge
from .profile import JulianProfile
from .quarry import QuarryStore
from .scout import HuntResult, JulianMetaMorph
from .service import create_app
from .splash_garden import SplashBenchConfig, SplashGardenConfig, render_splash_garden, run_splash_garden_bench


def _default_dataset_dir() -> str:
    env_dir = os.environ.get("JULIAN_DATASET_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if candidate.exists():
            return str(candidate)
    for candidate in (
        Path.home() / "Downloads" / "JL_ExternalData",
        Path("data") / "genome",
    ):
        if candidate.exists():
            return str(candidate)
    return str(Path.home() / "Downloads" / "JL_ExternalData")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="julian-metamorph")
    parser.add_argument("--db", default="data/quarry.db", help="Path to the SQLite quarry database.")
    parser.add_argument(
        "--dataset-dir",
        default=_default_dataset_dir(),
        help="Directory containing JSON/JSONL dataset files to ingest automatically.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prompt_cmd = sub.add_parser("julian-prompt", help="Render Julian's operating prompt.")
    prompt_cmd.add_argument("--task", default="", help="Optional task seed.")

    search_repo_cmd = sub.add_parser("search-repos", help="Search GitHub repositories live.")
    search_repo_cmd.add_argument("query")
    search_repo_cmd.add_argument("--limit", type=int, default=10)

    ingest_cmd = sub.add_parser("ingest-repo", help="Ingest a GitHub repo into the local quarry.")
    ingest_cmd.add_argument("repo")
    ingest_cmd.add_argument("--max-files", type=int, default=60)

    ingest_dataset_cmd = sub.add_parser(
        "ingest-datasets",
        help="Import all JSON/JSONL files from the configured external data directory.",
    )
    ingest_dataset_cmd.add_argument("--dataset-dir", default=None, help="Override the dataset directory to scan.")

    scout_cmd = sub.add_parser("scout-task", help="Scout the local quarry for task-relevant fragments.")
    scout_cmd.add_argument("task")
    scout_cmd.add_argument("--limit", type=int, default=8)
    scout_cmd.add_argument("--include-blocked", action="store_true")

    hunt_cmd = sub.add_parser(
        "hunt-task",
        help="Full autonomous hunt: GitHub search → ingest → scout → store findings tree (SparkByte metamorph).",
    )
    hunt_cmd.add_argument("task")
    hunt_cmd.add_argument("--repo-limit", type=int, default=5)
    hunt_cmd.add_argument("--files-per-repo", type=int, default=40)
    hunt_cmd.add_argument("--hit-limit", type=int, default=10)

    curiosity_cmd = sub.add_parser(
        "curiosity-hunt",
        help="Pick a rotating/random interest seed and run hunt-task (Julian goes exploring).",
    )
    curiosity_cmd.add_argument("--repo-limit", type=int, default=5)
    curiosity_cmd.add_argument("--files-per-repo", type=int, default=40)
    curiosity_cmd.add_argument("--hit-limit", type=int, default=10)

    forge_cmd = sub.add_parser("forge-skill", help="Forge a reusable skill module from scout hits.")
    forge_cmd.add_argument("name")
    forge_cmd.add_argument("task")
    forge_cmd.add_argument("--limit", type=int, default=8)
    forge_cmd.add_argument("--out", default="skills")

    splash_cmd = sub.add_parser(
        "splash-garden",
        help="Render a prototype RGB+D ripple image using the Splash Garden field engine.",
    )
    splash_cmd.add_argument("prompt", help="Seed prompt for the ripple field.")
    splash_cmd.add_argument("--width", type=int, default=96)
    splash_cmd.add_argument("--height", type=int, default=96)
    splash_cmd.add_argument("--steps", type=int, default=72)
    splash_cmd.add_argument("--out", default="data/splash_garden.png")
    splash_cmd.add_argument("--delay-out", default="data/splash_garden_delay.png")
    splash_cmd.add_argument("--meta-out", default="data/splash_garden.json")
    splash_cmd.add_argument("--energy", type=float, default=1.0)
    splash_cmd.add_argument("--delay-gain", type=float, default=1.0)
    splash_cmd.add_argument("--structure-gain", type=float, default=1.0)
    splash_cmd.add_argument("--spectral-tilt", type=float, default=0.0)
    splash_cmd.add_argument("--ring-scale", type=float, default=1.0)

    bench_cmd = sub.add_parser(
        "splash-garden-bench",
        help="Run a multi-case Splash Garden bench to probe delay, structure, and spectral behavior.",
    )
    bench_cmd.add_argument("prompt", help="Seed prompt for the bench suite.")
    bench_cmd.add_argument("--width", type=int, default=96)
    bench_cmd.add_argument("--height", type=int, default=96)
    bench_cmd.add_argument("--steps", type=int, default=72)
    bench_cmd.add_argument("--out-dir", default="data/splash_garden_bench")

    serve_cmd = sub.add_parser("serve", help="Run the standalone Julian MetaMorph API service.")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    profile = JulianProfile()
    dataset_dir = Path(args.dataset_dir).expanduser() if getattr(args, "dataset_dir", None) else None
    if dataset_dir is not None and not dataset_dir.exists():
        dataset_dir = None
    quarry = QuarryStore(args.db, genome_dir=dataset_dir)
    app = JulianMetaMorph(profile=profile, quarry=quarry)

    if args.command == "julian-prompt":
        print(profile.render_prompt(args.task or None))
        return 0

    if args.command == "search-repos":
        print(json.dumps(app.search_repositories(args.query, limit=args.limit), indent=2))
        return 0

    if args.command == "ingest-repo":
        print(json.dumps(app.ingest_repo(args.repo, max_files=args.max_files), indent=2))
        return 0

    if args.command == "ingest-datasets":
        override_dir = Path(args.dataset_dir).expanduser() if getattr(args, "dataset_dir", None) else None
        if override_dir is not None and override_dir.exists():
            dataset_dir = override_dir
        elif override_dir is not None:
            dataset_dir = None
        elif getattr(args, "dataset_dir", None):
            dataset_dir = Path(args.dataset_dir).expanduser()
        else:
            dataset_dir = Path(_default_dataset_dir()).expanduser()
        quarry = QuarryStore(args.db, genome_dir=dataset_dir)
        print(json.dumps(quarry.ingest_genome(), indent=2))
        return 0

    if args.command == "scout-task":
        hits = app.scout_task(args.task, limit=args.limit, allowed_only=not args.include_blocked)
        print(json.dumps([dataclasses.asdict(hit) for hit in hits], indent=2))
        return 0

    def _hit_dict(h: object) -> dict[str, object]:
        return {
            "repo_full_name": h.repo_full_name,
            "path": h.path,
            "language": h.language,
            "license_spdx": h.license_spdx,
            "allowed": h.allowed,
            "score": h.score,
            "preview": (h.preview or "")[:400],
            "symbols": list(h.symbols),
            "why": h.why,
        }

    def _hunt_result_to_dict(result: HuntResult) -> dict[str, object]:
        return {
            "task": result.task,
            "hunt_id": result.hunt_id,
            "queries_used": result.queries_used,
            "repos_ingested": result.repos_ingested,
            "hit_count": len(result.hits),
            "hits": [_hit_dict(h) for h in result.hits],
        }

    if args.command == "hunt-task":
        result = app.hunt_task(
            args.task,
            repo_limit=args.repo_limit,
            files_per_repo=args.files_per_repo,
            hit_limit=args.hit_limit,
        )
        print(json.dumps(_hunt_result_to_dict(result), indent=2))
        return 0

    if args.command == "curiosity-hunt":
        db_path = Path(args.db)
        state_dir = db_path.parent
        picked = pick_curiosity_task(profile.curiosity_seeds, state_dir)
        result = app.hunt_task(
            picked,
            repo_limit=args.repo_limit,
            files_per_repo=args.files_per_repo,
            hit_limit=args.hit_limit,
        )
        out = _hunt_result_to_dict(result)
        out["picked_task"] = picked
        top = result.hits[0] if result.hits else None
        out["summary"] = (
            f"{picked[:120]} → {out['hit_count']} hits"
            + (f" | top: {top.repo_full_name}/{top.path}" if top else "")
        )
        print(json.dumps(out, indent=2))
        return 0

    if args.command == "forge-skill":
        hits = app.scout_task(args.task, limit=args.limit)
        forged = SkillForge(profile=profile).forge(args.name, args.task, hits, out_dir=Path(args.out))
        print(
            json.dumps(
                {
                    "name": forged.name,
                    "task": forged.task,
                    "module_path": str(forged.module_path),
                    "manifest_path": str(forged.manifest_path),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "splash-garden":
        result = render_splash_garden(
            SplashGardenConfig(
                prompt=args.prompt,
                width=args.width,
                height=args.height,
                steps=args.steps,
                out_path=args.out,
                delay_out_path=args.delay_out,
                meta_out_path=args.meta_out,
                energy=args.energy,
                delay_gain=args.delay_gain,
                structure_gain=args.structure_gain,
                spectral_tilt=args.spectral_tilt,
                ring_scale=args.ring_scale,
            )
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "splash-garden-bench":
        result = run_splash_garden_bench(
            SplashBenchConfig(
                prompt=args.prompt,
                width=args.width,
                height=args.height,
                steps=args.steps,
                out_dir=args.out_dir,
            )
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "serve":
        uvicorn.run(create_app(db_path=args.db), host=args.host, port=args.port)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
