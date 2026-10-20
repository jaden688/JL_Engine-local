from __future__ import annotations

import json
from pathlib import Path

from julian_metamorph.cli import build_parser
from julian_metamorph.splash_garden import (
    SplashBenchConfig,
    SplashGardenConfig,
    render_splash_garden,
    run_splash_garden_bench,
)


def test_splash_garden_render_writes_rgb_delay_and_metadata(tmp_path: Path) -> None:
    rgb_path = tmp_path / "garden.png"
    delay_path = tmp_path / "garden_delay.png"
    meta_path = tmp_path / "garden.json"

    result = render_splash_garden(
        SplashGardenConfig(
            prompt="the splash garden",
            width=32,
            height=32,
            steps=10,
            out_path=str(rgb_path),
            delay_out_path=str(delay_path),
            meta_out_path=str(meta_path),
        )
    )

    assert rgb_path.exists()
    assert delay_path.exists()
    assert meta_path.exists()
    assert rgb_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert delay_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["layers"] == ["R", "G", "B", "D"]
    assert payload["layout"] == "hub-and-ring splash garden"
    assert payload["sources"]
    assert payload["tuning"]["delay_gain"] == 1.0
    assert "pixel_stats" in payload
    assert payload["output_files"]["red"].endswith("-red.png")
    assert payload["output_files"]["source_map"].endswith("-sources.png")
    assert Path(payload["output_files"]["red"]).exists()
    assert Path(payload["output_files"]["source_map"]).exists()
    assert result["output_files"]["rgb"] == str(rgb_path)


def test_splash_garden_bench_writes_manifest_and_case_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "bench"

    result = run_splash_garden_bench(
        SplashBenchConfig(
            prompt="unseen vision",
            width=28,
            height=28,
            steps=8,
            out_dir=str(out_dir),
        )
    )

    manifest_path = Path(result["manifest_path"])
    report_path = Path(result["report_path"])
    assert manifest_path.exists()
    assert report_path.exists()
    assert "Splash Garden Bench" in report_path.read_text(encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["prompt"] == "unseen vision"
    assert len(manifest["cases"]) == 4
    assert manifest["highlights"]["most_delay_driven"] == "delay-oracle"
    assert manifest["report_path"] == str(report_path)

    for case in manifest["cases"]:
        rgb_path = Path(case["files"]["rgb"])
        delay_path = Path(case["files"]["delay"])
        meta_path = Path(case["meta_path"])
        source_map_path = Path(case["files"]["source_map"])
        assert rgb_path.exists()
        assert delay_path.exists()
        assert meta_path.exists()
        assert source_map_path.exists()
        assert rgb_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_cli_parser_supports_splash_garden_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["splash-garden", "feel the ripple", "--steps", "12"])

    assert args.command == "splash-garden"
    assert args.prompt == "feel the ripple"
    assert args.steps == 12
    assert args.out.endswith(".png")


def test_cli_parser_supports_splash_garden_bench_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["splash-garden-bench", "unseen vision", "--steps", "12"])

    assert args.command == "splash-garden-bench"
    assert args.prompt == "unseen vision"
    assert args.steps == 12
