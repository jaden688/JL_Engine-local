"""OSV-Scanner integration — queries Google's OSV.dev vulnerability database."""

from __future__ import annotations

import os
from typing import Any

import requests


class OSVScanner:
    API_ROOT = "https://api.osv.dev/v1"

    def __init__(self, *, timeout: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()

    def query_package(self, ecosystem: str, name: str, version: str | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"package": {"ecosystem": ecosystem, "name": name}}
        if version:
            payload["version"] = version
        resp = self.session.post(
            f"{self.API_ROOT}/query",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("vulns", [])

    def query_commit(self, commit_hash: str) -> list[dict[str, Any]]:
        resp = self.session.post(
            f"{self.API_ROOT}/query",
            json={"commit": commit_hash},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("vulns", [])

    def batch_query(self, queries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        resp = self.session.post(
            f"{self.API_ROOT}/querybatch",
            json={"queries": queries},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [r.get("vulns", []) for r in results]

    def scan_repo(self, full_name: str) -> dict[str, Any]:
        """Scan a GitHub repo for known vulnerabilities via OSV ecosystem queries."""
        parts = full_name.split("/")
        repo_name = parts[-1] if parts else full_name

        ecosystem_guesses = self._guess_ecosystems(full_name)

        all_vulns: list[dict[str, Any]] = []
        queries_made: list[str] = []

        for eco, pkg in ecosystem_guesses:
            queries_made.append(f"{eco}:{pkg}")
            try:
                vulns = self.query_package(eco, pkg)
                all_vulns.extend(vulns)
            except requests.HTTPError:
                continue

        summary = []
        for v in all_vulns:
            summary.append({
                "id": v.get("id", ""),
                "summary": v.get("summary", ""),
                "severity": self._extract_severity(v),
                "affected": [a.get("package", {}).get("name", "") for a in v.get("affected", [])],
                "references": [r.get("url", "") for r in v.get("references", [])[:3]],
            })

        return {
            "repo": full_name,
            "queries_made": queries_made,
            "vuln_count": len(all_vulns),
            "vulnerabilities": summary[:50],
        }

    def _guess_ecosystems(self, full_name: str) -> list[tuple[str, str]]:
        """Heuristic: guess ecosystem/package combos from a repo name."""
        parts = full_name.split("/")
        repo_name = parts[-1] if parts else full_name
        owner = parts[0] if len(parts) > 1 else ""

        guesses: list[tuple[str, str]] = []

        if "fuchsia" in full_name.lower():
            guesses.append(("GIT", f"https://fuchsia.googlesource.com/{repo_name}"))
            guesses.append(("GIT", f"https://github.com/{full_name}"))

        guesses.append(("GIT", f"https://github.com/{full_name}"))

        if any(kw in repo_name.lower() for kw in ("py", "python")):
            guesses.append(("PyPI", repo_name))
        if any(kw in repo_name.lower() for kw in ("js", "node", "npm")):
            guesses.append(("npm", repo_name))
        if "rust" in repo_name.lower() or "rs" in repo_name.lower():
            guesses.append(("crates.io", repo_name))
        if "go" in repo_name.lower():
            guesses.append(("Go", f"github.com/{full_name}"))

        return guesses

    @staticmethod
    def _extract_severity(vuln: dict[str, Any]) -> str:
        severity_list = vuln.get("severity", [])
        if severity_list:
            return severity_list[0].get("score", "UNKNOWN")
        db_specific = vuln.get("database_specific", {})
        return db_specific.get("severity", "UNKNOWN")
