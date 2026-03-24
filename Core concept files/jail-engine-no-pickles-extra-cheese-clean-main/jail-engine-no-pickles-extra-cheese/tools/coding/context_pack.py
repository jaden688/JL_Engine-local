from __future__ import annotations

from typing import Any, Dict, List

from .search_tool import repo_map, search_rg, search_symbols
from .git_tool import git_diff, git_status


def build_context_pack(query: str, path: str = ".") -> Dict[str, Any]:
    """Assemble a multi-signal context blob for coding tasks."""
    pack: Dict[str, Any] = {"query": query}
    pack["repo_map"] = repo_map({"path": path})
    if query:
        pack["search"] = search_rg({"query": query, "path": path, "max_hits": 80})
        pack["symbols"] = search_symbols({"query": query, "path": path, "max_hits": 60})
    pack["git_status"] = git_status({})
    pack["git_diff"] = git_diff({})
    return pack
