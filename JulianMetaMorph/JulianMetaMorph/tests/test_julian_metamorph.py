from __future__ import annotations

import json
from pathlib import Path

from julian_metamorph import GitHubClient, JulianMetaMorph, LicenseGate, QuarryStore, SkillForge
from julian_metamorph.models import RepoFile, RepoSnapshot


class FakeGitHubClient(GitHubClient):
    def __init__(self) -> None:
        pass

    def fetch_repo(self, full_name: str) -> RepoSnapshot:
        return RepoSnapshot(
            full_name=full_name,
            description="OAuth tooling",
            language="Python",
            stars=99,
            forks=12,
            topics=("oauth", "token"),
            license_spdx="MIT",
            default_branch="main",
            html_url=f"https://github.com/{full_name}",
        )

    def iter_source_files(self, full_name: str, *, ref: str, max_files: int = 60, max_bytes: int = 180000, extensions=None):
        return [
            RepoFile(
                path="client.py",
                content="class TokenClient:\n    def refresh_token(self):\n        return 'fresh'\n",
                language="Python",
                sha="abc123",
                size=88,
            ),
            RepoFile(
                path="auth.py",
                content="def build_session_cookie_auth():\n    return {'cookie': True}\n",
                language="Python",
                sha="def456",
                size=90,
            ),
        ][:max_files]

    def search_repositories(self, query: str, *, limit: int = 10):
        return [
            RepoSnapshot(
                full_name="octo/oauth-kit",
                description="Token refresh helpers",
                language="Python",
                stars=500,
                license_spdx="Apache-2.0",
                html_url="https://github.com/octo/oauth-kit",
            )
        ][:limit]


def test_license_gate_blocks_gpl() -> None:
    verdict = LicenseGate().classify("GPL-3.0")
    assert verdict.allowed is False
    assert verdict.category == "copyleft"


def test_ingest_repo_and_scout_task(tmp_path: Path) -> None:
    app = JulianMetaMorph(github=FakeGitHubClient(), quarry=QuarryStore(tmp_path / "quarry.db"))

    result = app.ingest_repo("octo/oauth-kit", max_files=10)
    hits = app.scout_task("refresh token client", limit=5)

    assert result["allowed"] is True
    assert result["ingested_files"] == 2
    assert hits
    assert hits[0].repo_full_name == "octo/oauth-kit"
    assert "refresh token client" in hits[0].why


def test_search_repositories_uses_license_gate(tmp_path: Path) -> None:
    app = JulianMetaMorph(github=FakeGitHubClient(), quarry=QuarryStore(tmp_path / "quarry.db"))
    results = app.search_repositories("oauth token")
    assert results[0]["allowed"] is True
    assert results[0]["license"] == "APACHE-2.0"


def test_forge_writes_real_skill_and_manifest(tmp_path: Path) -> None:
    app = JulianMetaMorph(github=FakeGitHubClient(), quarry=QuarryStore(tmp_path / "quarry.db"))
    app.ingest_repo("octo/oauth-kit")
    hits = app.scout_task("session cookie auth", limit=5)

    forged = SkillForge().forge("auth_capsule", "session cookie auth", hits, out_dir=tmp_path / "skills")

    assert forged.module_path.exists()
    assert forged.manifest_path.exists()

    manifest = json.loads(forged.manifest_path.read_text(encoding="utf-8"))
    assert manifest["profile"] == "Julian"
    assert manifest["sources"]

    namespace: dict = {}
    exec(forged.module_path.read_text(encoding="utf-8"), namespace)  # noqa: S102
    output = namespace["run"]({"query": "cookie"})
    assert output["profile"] == "Julian"
    assert output["matches"]


def test_dataset_records_ingest_and_hunt_preserve_source(tmp_path: Path) -> None:
    genome_dir = tmp_path / "genome"
    genome_dir.mkdir()
    (genome_dir / "cyber-security-sample.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "sec-001",
                        "title": "Credential stuffing login bypass",
                        "content": "Attackers can brute force password resets and log in with stolen session cookies.",
                        "source": "Vyber07/cyber-security",
                        "source_url": "https://example.org/reports/sec-001",
                        "tags": ["credential", "session", "login", "bypass"],
                    },
                    {
                        "id": "sec-002",
                        "title": "Token replay in API gateway",
                        "content": "Refresh tokens may leak across hosts during replay attacks.",
                        "source": "Vyber07/cyber-security",
                        "source_url": "https://example.org/reports/sec-002",
                        "tags": ["token", "replay", "gateway"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    quarry = QuarryStore(tmp_path / "quarry.db", genome_dir=genome_dir)
    result = quarry.ingest_genome()
    assert result["records_ingested"] >= 2

    hits = quarry.search_hf("credential stuffing login bypass", limit=5)
    assert hits
    assert hits[0]["source"] == "Vyber07/cyber-security"
    assert hits[0]["source_url"] == "https://example.org/reports/sec-001"

    app = JulianMetaMorph(github=FakeGitHubClient(), quarry=quarry)
    hunt = app.hunt_task("credential stuffing login bypass", repo_limit=1, files_per_repo=1, hit_limit=5)
    assert hunt.hits
    assert any(hit.source == "Vyber07/cyber-security" for hit in hunt.hits)
    assert any(hit.source_url.startswith("https://example.org/") for hit in hunt.hits)
