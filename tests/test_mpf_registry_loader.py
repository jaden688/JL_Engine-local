from __future__ import annotations

import json

from framework import mpf as mpf_pkg


def test_registry_loader_injects_required_baseline_agents_from_canonical(tmp_path, monkeypatch):
    primary_registry = tmp_path / "primary.mpf.json"
    canonical_registry = tmp_path / "canonical.mpf.json"

    primary_registry.write_text(
        json.dumps(
            {
                "Custom Agent": {
                    "jl_agent_file": "generated/custom_agent.json",
                    "default_backend_id": "ollama-local",
                }
            }
        ),
        encoding="utf-8",
    )
    canonical_registry.write_text(
        json.dumps(
            {
                "SparkByte": {"jl_agent_file": "fat_agents/SparkByte_Full.json"},
                "The Gremlin": {"jl_agent_file": "fat_agents/The_Gremlin_Full.json"},
                "Slappy": {"jl_agent_file": "fat_agents/Slappy_Full.json"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mpf_pkg.fullstack, "CANONICAL_RUNTIME_REGISTRY", canonical_registry)

    profiles = mpf_pkg.load_mpf_registry(str(primary_registry))

    assert "Custom Agent" in profiles
    assert "SparkByte" in profiles
    assert "The Gremlin" in profiles
    assert "Slappy" in profiles


def test_registry_loader_keeps_custom_entries_when_canonical_missing(tmp_path, monkeypatch):
    primary_registry = tmp_path / "primary_only.mpf.json"
    primary_registry.write_text(
        json.dumps(
            {
                "Custom Agent": {
                    "jl_agent_file": "generated/custom_agent.json",
                    "default_backend_id": "ollama-local",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mpf_pkg.fullstack,
        "CANONICAL_RUNTIME_REGISTRY",
        tmp_path / "missing-canonical.mpf.json",
    )

    profiles = mpf_pkg.load_mpf_registry(str(primary_registry))

    assert list(profiles.keys()) == ["Custom Agent"]