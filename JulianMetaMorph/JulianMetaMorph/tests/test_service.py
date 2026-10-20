from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from julian_metamorph.service import create_app


def test_service_health_and_prompt(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "quarry.db", data_root=tmp_path / "data"))

    health = client.get("/health")
    prompt = client.post("/julian/prompt", json={"task": "refresh auth middleware"})

    assert health.status_code == 200
    assert health.json()["service"] == "julian-metamorph"
    assert prompt.status_code == 200
    assert "Julian MetaMorph" in prompt.json()["prompt"]


def test_service_ripple_scope_and_live_splash_outputs(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "quarry.db", data_root=tmp_path / "data"))

    scope = client.get("/ripple-scope")
    splash = client.post(
        "/splash/live",
        json={
            "prompt": "unseen vision",
            "width": 32,
            "height": 32,
            "steps": 10,
            "delay_gain": 1.2,
            "guide_label": "face.png",
            "guide_luma": [[0.0, 0.5] * 16 for _ in range(32)],
            "guide_edges": [[1.0, 0.25] * 16 for _ in range(32)],
        },
    )

    assert scope.status_code == 200
    assert "RIPPLE SCOPE LIVE" in scope.text
    assert splash.status_code == 200
    payload = splash.json()
    assert payload["status"] == "ok"
    assert payload["artifact_urls"]["rgb"].startswith("/artifacts/live/splash/")
    assert payload["result"]["output_files"]["source_map"].endswith("-sources.png")
    assert payload["result"]["guide"]["enabled"] is True
    assert payload["result"]["guide"]["label"] == "face.png"

    rgb = client.get(payload["artifact_urls"]["rgb"])
    meta = client.get(payload["artifact_urls"]["meta"])
    assert rgb.status_code == 200
    assert rgb.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert meta.status_code == 200
    assert "unseen vision" in meta.text


def test_service_live_bench_returns_report_and_artifacts(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "quarry.db", data_root=tmp_path / "data"))

    bench = client.post(
        "/splash/live/bench",
        json={
            "prompt": "unseen vision",
            "width": 28,
            "height": 28,
            "steps": 8,
            "guide_label": "storm.png",
            "guide_luma": [[0.5] * 28 for _ in range(28)],
            "guide_edges": [[0.75] * 28 for _ in range(28)],
        },
    )

    assert bench.status_code == 200
    payload = bench.json()
    manifest = payload["manifest"]
    assert payload["status"] == "ok"
    assert manifest["report_url"].startswith("/artifacts/live/bench/")
    assert manifest["cases"][0]["artifact_urls"]["rgb"].endswith(".png")
    assert manifest["cases"][0]["meta_url"].endswith(".json")

    report = client.get(manifest["report_url"])
    manifest_file = client.get(manifest["manifest_url"])
    assert report.status_code == 200
    assert "Splash Garden Bench" in report.text
    assert manifest_file.status_code == 200
    assert "most_delay_driven" in manifest_file.text
