"""Syzkaller integration — queries syzbot crash data for kernel/Zircon bug hunting."""

from __future__ import annotations

import os
from typing import Any

import requests


class SyzkallerBridge:
    SYZBOT_API = "https://syzkaller.appspot.com"

    def __init__(self, *, timeout: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.api_key = os.getenv("SYZBOT_API_KEY", "")

    def get_open_bugs(self, manager: str = "fuchsia") -> list[dict[str, Any]]:
        """Fetch open bugs from syzbot. Fuchsia bugs are auth-gated, so we fall back to upstream."""
        namespace = manager if manager != "fuchsia" else "upstream"
        resp = self.session.get(
            f"{self.SYZBOT_API}/{namespace}/open",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        bugs = self._parse_bug_table(resp.text)
        if manager == "fuchsia" and not bugs:
            resp = self.session.get(
                f"{self.SYZBOT_API}/upstream/open",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            bugs = self._parse_bug_table(resp.text)
        return bugs

    def get_crashes(self, target_repo: str) -> dict[str, Any]:
        """Get crash data relevant to a target repo/subsystem."""
        manager = self._repo_to_manager(target_repo)
        bugs = self.get_open_bugs(manager)

        subsystem_keywords = self._extract_subsystem_keywords(target_repo)
        relevant = []
        for bug in bugs:
            title = (bug.get("title") or "").lower()
            if any(kw in title for kw in subsystem_keywords) or not subsystem_keywords:
                relevant.append({
                    "title": bug.get("title", ""),
                    "id": bug.get("id", ""),
                    "status": bug.get("status", "open"),
                    "reported": bug.get("reported", ""),
                    "crash_type": self._classify_crash(bug.get("title", "")),
                    "url": bug.get("url", f"{self.SYZBOT_API}/bug?id={bug.get('id', '')}"),
                })

        return {
            "target_repo": target_repo,
            "manager": manager,
            "total_open_bugs": len(bugs),
            "relevant_bugs": relevant[:30],
            "subsystem_keywords": subsystem_keywords,
        }

    def get_reproducer(self, bug_id: str) -> dict[str, Any] | None:
        """Fetch the C reproducer for a specific syzbot bug if available."""
        params: dict[str, str] = {"id": bug_id}
        if self.api_key:
            params["key"] = self.api_key
        try:
            resp = self.session.get(
                f"{self.SYZBOT_API}/api/bug",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            crashes = data.get("crashes", [])
            for crash in crashes:
                if crash.get("c_repro"):
                    return {
                        "bug_id": bug_id,
                        "repro_type": "c",
                        "repro_url": crash["c_repro"],
                        "kernel_config": crash.get("kernel_config", ""),
                    }
                if crash.get("syz_repro"):
                    return {
                        "bug_id": bug_id,
                        "repro_type": "syz",
                        "repro_url": crash["syz_repro"],
                    }
        except requests.HTTPError:
            pass
        return None

    def _repo_to_manager(self, target_repo: str) -> str:
        lower = target_repo.lower()
        if "fuchsia" in lower or "zircon" in lower:
            return "fuchsia"
        if "linux" in lower or "kernel" in lower:
            return "linux"
        return "fuchsia"

    def _extract_subsystem_keywords(self, target_repo: str) -> list[str]:
        lower = target_repo.lower()
        keywords: list[str] = []
        subsystems = {
            "net": ["net", "socket", "tcp", "udp", "ethernet", "netstack"],
            "usb": ["usb", "xhci", "device"],
            "bluetooth": ["bt", "bluetooth", "hci"],
            "audio": ["audio", "codec", "dai"],
            "display": ["display", "framebuffer", "gpu"],
            "storage": ["block", "disk", "fs", "minfs", "blobfs", "fxfs"],
            "driver": ["driver", "ddk", "banjo", "fidl"],
            "kernel": ["zircon", "kernel", "scheduler", "vmo", "vmar", "handle"],
        }
        for subsys, kws in subsystems.items():
            if any(k in lower for k in kws):
                keywords.extend(kws)
        if not keywords:
            parts = target_repo.split("/")
            name = parts[-1] if parts else target_repo
            keywords = [tok for tok in name.lower().replace("-", " ").replace("_", " ").split() if len(tok) > 2]
        return keywords[:10]

    @staticmethod
    def _classify_crash(title: str) -> str:
        lower = title.lower()
        if "kasan" in lower or "use-after-free" in lower:
            return "use_after_free"
        if "overflow" in lower or "oob" in lower or "out-of-bounds" in lower:
            return "buffer_overflow"
        if "deadlock" in lower or "lock" in lower:
            return "deadlock"
        if "leak" in lower:
            return "memory_leak"
        if "null" in lower or "deref" in lower:
            return "null_deref"
        if "race" in lower or "data race" in lower:
            return "race_condition"
        if "panic" in lower or "assert" in lower:
            return "kernel_panic"
        return "unknown"

    @staticmethod
    def _parse_bug_table(html: str) -> list[dict[str, Any]]:
        """Parse syzbot's HTML bug table into structured data."""
        import re
        bugs: list[dict[str, Any]] = []
        for match in re.finditer(
            r'<td class="title">\s*<a href="(/bug\?[^"]*id=([^"&]*))"[^>]*>([^<]+)</a>',
            html,
        ):
            path, bug_id, title = match.group(1), match.group(2), match.group(3)
            bugs.append({
                "title": title.strip(),
                "id": bug_id,
                "status": "open",
                "url": f"https://syzkaller.appspot.com{path}",
            })
        return bugs
