from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import requests

from .models import RepoFile, RepoSnapshot


def _guess_language(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".json": "JSON",
        ".md": "Markdown",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".sh": "Shell",
        ".c": "C",
        ".h": "C",
        ".cc": "C++",
        ".cpp": "C++",
        ".cxx": "C++",
        ".hpp": "C++",
        ".hh": "C++",
        ".fidl": "FIDL",
        ".gn": "GN",
        ".gni": "GN",
    }.get(suffix, suffix.lstrip(".").upper())


class GitHubClient:
    API_ROOT = "https://api.github.com"
    DEFAULT_EXTENSIONS = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh",
        ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".fidl", ".gn", ".gni",
    }

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "julian-metamorph/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.API_ROOT}{path}",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_repo(self, full_name: str) -> RepoSnapshot:
        data = self._get_json(f"/repos/{full_name}")
        license_info = data.get("license") or {}
        return RepoSnapshot(
            full_name=data["full_name"],
            description=data.get("description") or "",
            homepage=data.get("homepage") or "",
            language=data.get("language") or "",
            stars=int(data.get("stargazers_count") or 0),
            forks=int(data.get("forks_count") or 0),
            topics=tuple(data.get("topics") or []),
            license_spdx=license_info.get("spdx_id") or license_info.get("name") or "UNKNOWN",
            default_branch=data.get("default_branch") or "main",
            pushed_at=data.get("pushed_at") or "",
            html_url=data.get("html_url") or "",
            metadata={
                "open_issues": int(data.get("open_issues_count") or 0),
                "watchers": int(data.get("subscribers_count") or 0),
            },
        )

    def fetch_tree(self, full_name: str, ref: str) -> list[dict[str, Any]]:
        data = self._get_json(f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"})
        return list(data.get("tree") or [])

    def fetch_file_content(self, full_name: str, path: str, ref: str) -> str:
        data = self._get_json(f"/repos/{full_name}/contents/{path}", params={"ref": ref})
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        download_url = data.get("download_url")
        if not download_url:
            return ""
        response = self.session.get(download_url, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def iter_source_files(
        self,
        full_name: str,
        *,
        ref: str,
        max_files: int = 60,
        max_bytes: int = 180_000,
        extensions: set[str] | None = None,
    ) -> list[RepoFile]:
        allow_exts = extensions or self.DEFAULT_EXTENSIONS
        files: list[RepoFile] = []
        for item in self.fetch_tree(full_name, ref):
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""
            suffix = Path(path).suffix.lower()
            size = int(item.get("size") or 0)
            if suffix not in allow_exts:
                continue
            if size > max_bytes:
                continue
            try:
                content = self.fetch_file_content(full_name, path, ref)
            except requests.HTTPError:
                continue
            files.append(
                RepoFile(
                    path=path,
                    content=content,
                    language=_guess_language(path),
                    sha=item.get("sha") or "",
                    size=size,
                )
            )
            if len(files) >= max_files:
                break
        return files

    def search_repositories(self, query: str, *, limit: int = 10) -> list[RepoSnapshot]:
        data = self._get_json(
            "/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": str(limit)},
        )
        snapshots: list[RepoSnapshot] = []
        for item in data.get("items") or []:
            license_info = item.get("license") or {}
            snapshots.append(
                RepoSnapshot(
                    full_name=item["full_name"],
                    description=item.get("description") or "",
                    homepage=item.get("homepage") or "",
                    language=item.get("language") or "",
                    stars=int(item.get("stargazers_count") or 0),
                    forks=int(item.get("forks_count") or 0),
                    topics=tuple(item.get("topics") or []),
                    license_spdx=license_info.get("spdx_id") or license_info.get("name") or "UNKNOWN",
                    default_branch=item.get("default_branch") or "main",
                    pushed_at=item.get("pushed_at") or "",
                    html_url=item.get("html_url") or "",
                )
            )
        return snapshots

    # ── PUSH FINDINGS TO GITHUB ───────────────────────────────────────────────
    def ensure_repo(self, repo_name: str, *, description: str = "", private: bool = False) -> dict[str, Any]:
        """Creates the repo if it doesn't exist; returns repo data either way."""
        try:
            return self._get_json(f"/repos/{self._authenticated_user()}/{repo_name}")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                resp = self.session.post(
                    f"{self.API_ROOT}/user/repos",
                    headers=self._headers(),
                    json={"name": repo_name, "description": description,
                          "private": private, "auto_init": True},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            raise

    def _authenticated_user(self) -> str:
        return self._get_json("/user")["login"]

    def push_file(
        self,
        owner: str,
        repo_name: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
    ) -> None:
        """Creates or updates a single file in a GitHub repo."""
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        url = f"{self.API_ROOT}/repos/{owner}/{repo_name}/contents/{path}"
        # Try to get existing SHA
        sha: str | None = None
        try:
            existing = self._get_json(f"/repos/{owner}/{repo_name}/contents/{path}",
                                      params={"ref": branch})
            sha = existing.get("sha")
        except requests.HTTPError:
            pass
        payload: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        resp = self.session.put(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()

    def push_findings_to_github(
        self,
        findings: list[dict],
        *,
        repo_name: str = "sparkbyte-engine-findings",
        branch: str = "main",
    ) -> str:
        """
        Organises findings into a tree of markdown files and pushes to GitHub.
        Returns the HTML URL of the repo.
        """
        owner = self._authenticated_user()
        repo_data = self.ensure_repo(
            repo_name,
            description="Auto-generated engine findings by Julian MetaMorph 🔍",
        )
        html_url: str = repo_data.get("html_url", f"https://github.com/{owner}/{repo_name}")

        # Group finding leaves by category/subcategory
        from collections import defaultdict
        groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        hunt_tasks: dict[str, str] = {}

        for node in findings:
            if node["node_type"] == "finding":
                groups[node["category"]][node["subcategory"]].append(node)
            if node["node_type"] == "hunt":
                hunt_tasks[node["hunt_id"]] = node["task"]

        # Build README
        readme_lines = [
            "# SparkByte Engine Findings",
            "",
            "> Auto-generated by **Julian MetaMorph** — GitHub scout for the SparkByte engine.",
            "",
            "## Categories",
            "",
        ]
        for cat, subcats in sorted(groups.items()):
            count = sum(len(v) for v in subcats.values())
            readme_lines.append(f"- **{cat}** — {count} findings")
            for subcat in sorted(subcats):
                readme_lines.append(f"  - [{subcat}]({cat}/{subcat}.md)")
        readme_lines += ["", "---", "*Pushed by Julian MetaMorph*"]
        self.push_file(owner, repo_name, "README.md",
                       "\n".join(readme_lines), "docs: update README", branch)

        # One markdown file per subcategory
        for cat, subcats in groups.items():
            for subcat, nodes in subcats.items():
                lines = [
                    f"# {cat} / {subcat}",
                    "",
                    f"*{len(nodes)} findings*",
                    "",
                ]
                for i, node in enumerate(nodes, 1):
                    lang = node.get("language", "").lower() or "text"
                    symbols = node.get("symbols", [])
                    sym_str = ", ".join(f"`{s}`" for s in symbols[:6]) if symbols else "—"
                    lines += [
                        f"## {i}. `{node['file_path']}`",
                        "",
                        f"**Repo:** [{node['repo_full_name']}](https://github.com/{node['repo_full_name']})",
                        f"  **License:** {node['license_spdx']}  **Score:** {node['score']:.3f}",
                        "",
                        f"**Symbols:** {sym_str}",
                        "",
                        f"> {node['explanation']}",
                        "",
                        f"```{lang}",
                        node.get("preview", ""),
                        "```",
                        "",
                        "---",
                        "",
                    ]
                self.push_file(
                    owner, repo_name, f"{cat}/{subcat}.md",
                    "\n".join(lines),
                    f"findings: {cat}/{subcat} ({len(nodes)} items)",
                    branch,
                )

        return html_url
