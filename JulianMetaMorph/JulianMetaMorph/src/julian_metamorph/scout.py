from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from time import time

from .github_client import GitHubClient
from .license_gate import LicenseGate
from .models import RepoFile, ScoutHit
from .profile import JulianProfile
from .quarry import QuarryStore

# ── Category classification map ───────────────────────────────────────────────
# (keyword_set, category, subcategory)
_CATEGORY_RULES: list[tuple[set[str], str, str]] = [
    # ── VRP: Starnix syscall translation boundary ────────────────────────────
    # Where Linux assumptions meet Zircon reality — every mismatch is a bounty
    ({"starnix", "syscall", "translate", "compat", "posix", "linux_uapi"}, "vrp_starnix", "syscall_translation"),
    ({"errno", "einval", "efault", "enosys", "eopnotsupp", "unimplemented"}, "vrp_starnix", "missing_syscall"),
    ({"ioctl", "fcntl", "prctl", "setsockopt", "getsockopt"}, "vrp_starnix", "ioctl_surface"),
    ({"mmap", "mprotect", "mremap", "munmap", "brk", "sbrk"}, "vrp_starnix", "memory_mapping"),
    ({"fork", "clone", "execve", "wait", "exit_group", "ptrace"}, "vrp_starnix", "process_lifecycle"),
    ({"signal", "sigaction", "sigaltstack", "sigprocmask", "kill"}, "vrp_starnix", "signal_handling"),
    ({"epoll", "poll", "select", "eventfd", "timerfd", "signalfd"}, "vrp_starnix", "fd_multiplexing"),
    ({"pipe", "fifo", "socketpair", "sendmsg", "recvmsg", "cmsg"}, "vrp_starnix", "ipc_translation"),
    # ── VRP: Zircon handle lifecycle ─────────────────────────────────────────
    # Handle leaks, double-close, use-after-close = high-severity VRP
    ({"handle", "zx_handle", "close", "duplicate", "replace", "transfer"}, "vrp_zircon", "handle_lifecycle"),
    ({"vmo", "vmo_create", "vmo_read", "vmo_write", "vmo_map", "vmo_op_range"}, "vrp_zircon", "vmo_ops"),
    ({"vmar", "vmar_map", "vmar_protect", "vmar_unmap", "vmar_allocate"}, "vrp_zircon", "vmar_mapping"),
    ({"channel", "channel_read", "channel_write", "channel_call"}, "vrp_zircon", "channel_ipc"),
    ({"port", "port_wait", "port_queue", "port_cancel"}, "vrp_zircon", "port_async"),
    ({"job", "process", "thread", "task_kill", "task_suspend"}, "vrp_zircon", "task_control"),
    # ── VRP: FIDL protocol boundaries ────────────────────────────────────────
    # Serialization/deserialization bugs, type confusion, missing validation
    ({"fidl", "encode", "decode", "marshal", "unmarshal", "wire_format"}, "vrp_fidl", "serialization"),
    ({"protocol", "binding", "proxy", "stub", "epitaph", "event"}, "vrp_fidl", "protocol_boundary"),
    ({"table", "union", "flexible", "strict", "ordinal", "unknown"}, "vrp_fidl", "type_evolution"),
    # ── VRP: Capability routing / sandbox escape ─────────────────────────────
    # Component framework capability misrouting = sandbox escape = critical VRP
    ({"capability", "routing", "offer", "expose", "use", "from_parent"}, "vrp_sandbox", "cap_routing"),
    ({"sandbox", "namespace", "directory", "rights", "readonly"}, "vrp_sandbox", "namespace_escape"),
    ({"component", "realm", "collection", "resolver", "runner"}, "vrp_sandbox", "component_framework"),
    # ── VRP: Memory safety (classic patterns, high payout) ───────────────────
    ({"buffer", "overflow", "overrun", "oob", "out_of_bounds", "bounds_check", "memcpy", "memmove", "strncpy"}, "vrp_memory", "buffer_overflow"),
    ({"use_after_free", "uaf", "dangling", "freed", "double_free", "free", "release", "destroy", "ref_count"}, "vrp_memory", "use_after_free"),
    ({"uninitialized", "uninit", "garbage", "memset", "zeroinit", "stack_variable"}, "vrp_memory", "uninitialized_read"),
    ({"integer_overflow", "truncation", "signedness", "wraparound", "narrowing", "cast", "size_t", "ssize_t"}, "vrp_memory", "integer_overflow"),
    ({"null", "nullptr", "null_check", "deref", "dereference", "optional", "fit::nullable"}, "vrp_memory", "null_deref"),
    # ── VRP: Race conditions / concurrency ───────────────────────────────────
    ({"race", "toctou", "data_race", "thread_safety", "atomic", "lock_order", "deadlock"}, "vrp_concurrency", "race_condition"),
    ({"mutex", "lock", "unlock", "guard", "acquire", "release", "spinlock"}, "vrp_concurrency", "lock_discipline"),
    ({"refcount", "ref_count", "add_ref", "release_ref", "weak_ptr", "shared_ptr"}, "vrp_concurrency", "refcount_race"),
    # ── VRP: Driver / device boundary ────────────────────────────────────────
    ({"driver", "ddk", "banjo", "bind", "device_add", "device_remove"}, "vrp_driver", "driver_interface"),
    ({"usb", "xhci", "endpoint", "descriptor", "transfer", "bulk", "interrupt"}, "vrp_driver", "usb_surface"),
    ({"pci", "mmio", "pio", "bar", "config_space", "interrupt"}, "vrp_driver", "pci_surface"),
    # ── VRP: Network stack ───────────────────────────────────────────────────
    ({"netstack", "tcp", "udp", "icmp", "packet", "socket", "bind", "listen", "accept"}, "vrp_network", "netstack"),
    ({"dhcp", "dns", "arp", "ndp", "ipv6", "routing", "forwarding"}, "vrp_network", "protocol_handling"),
    # ── Existing categories ──────────────────────────────────────────────────
    ({"websocket", "ws", "socket", "wss", "upgrade", "handshake"}, "websocket", "protocol"),
    ({"reconnect", "backoff", "retry", "keepalive", "heartbeat"}, "websocket", "resilience"),
    ({"stream", "chunk", "pipe", "generator", "yield", "async_gen"}, "streaming", "async_io"),
    ({"async", "await", "asyncio", "trio", "anyio", "coroutine", "event_loop"}, "streaming", "async_runtime"),
    ({"agent", "tool", "llm", "inference", "completion", "prompt", "openai", "anthropic"}, "ai_agent", "llm_tooling"),
    ({"plan", "action", "observation", "thought", "react", "chain", "workflow"}, "ai_agent", "orchestration"),
    ({"memory", "cache", "recall", "store", "retrieve", "embedding", "vector"}, "memory", "storage"),
    ({"sqlite", "database", "db", "sql", "fts", "index", "query"}, "memory", "database"),
    ({"queue", "scheduler", "pipeline", "dispatch", "broker", "task"}, "orchestration", "scheduling"),
    ({"http", "server", "router", "fastapi", "flask", "starlette", "endpoint"}, "ui_server", "http"),
    ({"html", "css", "dom", "render", "frontend", "canvas", "ui"}, "ui_server", "frontend"),
    ({"julia", "jl", "module", "mutable", "struct", "macro"}, "engine_core", "julia_patterns"),
    ({"test", "spec", "assert", "mock", "fixture", "pytest"}, "testing", "test_patterns"),
]


@dataclass
class HuntResult:
    task: str
    hunt_id: str
    queries_used: list[str]
    repos_ingested: list[dict[str, object]]
    hits: list[ScoutHit]


class JulianMetaMorph:
    def __init__(
        self,
        *,
        profile: JulianProfile | None = None,
        github: GitHubClient | None = None,
        quarry: QuarryStore | None = None,
        license_gate: LicenseGate | None = None,
    ) -> None:
        self.profile = profile or JulianProfile()
        self.github = github or GitHubClient()
        self.quarry = quarry or QuarryStore()
        self.license_gate = license_gate or LicenseGate()

    # ── BUG HUNT MODE ────────────────────────────────────────────────────────
    VRP_QUERIES: list[str] = [
        # Starnix translation boundaries
        "starnix syscall translate linux compat",
        "mmap mprotect vmar mapping translate",
        "ioctl fcntl socket option translate",
        "fork clone execve process lifecycle",
        "signal sigaction handler translate",
        "epoll poll select eventfd translate",
        "pipe sendmsg recvmsg cmsg ancillary",
        # Zircon object lifecycle
        "handle close duplicate transfer leak",
        "vmo create map read write op_range",
        "vmar map protect unmap allocate",
        "channel read write call port wait",
        # FIDL boundaries
        "fidl encode decode marshal validate",
        "fidl protocol binding proxy epitaph",
        # Sandbox / capability
        "capability routing offer expose namespace",
        "sandbox directory rights escape",
        "component realm resolver runner",
        # Memory safety
        "buffer overflow memcpy bounds size",
        "free release destroy ref_count dangling",
        "uninitialized memset stack variable",
        "integer overflow cast truncation size_t",
        # Concurrency
        "mutex lock unlock guard race",
        "refcount add_ref release weak_ptr",
        # Driver surface
        "driver ddk device_add bind remove",
        "usb endpoint descriptor transfer",
        # Network
        "netstack tcp udp packet socket",
    ]

    def hunt_bugs(
        self,
        target_repo: str,
        *,
        files_limit: int = 80,
        hit_limit: int = 20,
    ) -> HuntResult:
        hunt_id = str(uuid.uuid4())[:8]
        task = f"vrp hunt: {target_repo}"

        # Skip GitHub ingest if repo already exists in quarry (e.g. local SDK ingest)
        existing = self.quarry.summary()
        if files_limit > 0:
            try:
                result = self.ingest_repo(target_repo, max_files=files_limit)
            except Exception:
                result = None  # Already ingested locally, skip
        else:
            result = None

        # Run every VRP query against the ingested code
        all_hits: list[ScoutHit] = []
        seen_paths: set[str] = set()
        queries_used: list[str] = []

        for q in self.VRP_QUERIES:
            queries_used.append(q)
            hits = self.scout_task(q, limit=5, allowed_only=False)
            for h in hits:
                key = f"{h.repo_full_name}:{h.path}"
                if key not in seen_paths:
                    seen_paths.add(key)
                    all_hits.append(h)

        # Sort: VRP categories first, then by score
        vrp_prefixes = ("vrp_starnix", "vrp_zircon", "vrp_fidl", "vrp_sandbox",
                        "vrp_memory", "vrp_concurrency", "vrp_driver", "vrp_network")

        def _vrp_rank(hit: ScoutHit) -> tuple[int, float]:
            cat, _ = self.classify_hit(hit)
            priority = {
                "vrp_sandbox": 0,      # Critical — sandbox escape
                "vrp_starnix": 1,      # High — translation boundary
                "vrp_zircon": 2,       # High — handle lifecycle
                "vrp_fidl": 3,         # High — protocol boundary
                "vrp_memory": 4,       # Standard — memory safety
                "vrp_concurrency": 5,  # Standard — race conditions
                "vrp_driver": 6,       # Standard — driver surface
                "vrp_network": 7,      # Standard — network stack
            }
            return (priority.get(cat, 99), hit.score)

        all_hits.sort(key=_vrp_rank)

        self.quarry.store_hunt_findings(
            hunt_id=hunt_id,
            task=task,
            hits=all_hits[:hit_limit],
            queries=queries_used,
        )

        return HuntResult(
            task=task,
            hunt_id=hunt_id,
            queries_used=queries_used,
            repos_ingested=[result],
            hits=all_hits[:hit_limit],
        )

    # ── AUTONOMOUS HUNT ───────────────────────────────────────────────────────
    def hunt_task(
        self,
        task: str,
        *,
        repo_limit: int = 5,
        files_per_repo: int = 40,
        hit_limit: int = 10,
    ) -> HuntResult:
        hunt_id = str(uuid.uuid4())[:8]
        queries = self._derive_queries(task)
        seen: dict[str, object] = {}

        # ── GitHub: search + ingest ───────────────────────────────────────────
        for q in queries:
            for repo in self.github.search_repositories(q, limit=10):
                if repo.full_name not in seen:
                    verdict = self.license_gate.classify(repo.license_spdx)
                    if verdict.allowed:
                        seen[repo.full_name] = repo

        candidates = sorted(seen.values(), key=lambda r: r.stars, reverse=True)[:repo_limit]

        ingested_summaries: list[dict[str, object]] = []
        for repo in candidates:
            result = self.ingest_repo(repo.full_name, max_files=files_per_repo)
            ingested_summaries.append(result)

        # Scout the quarry for GitHub code hits
        gh_hits = self.scout_task(task, limit=hit_limit)

        # ── dataset / HuggingFace genome: search ─────────────────────────────
        hf_raw = self.quarry.search_hf(task, limit=max(4, hit_limit // 2))
        hf_hits: list[ScoutHit] = []
        for m in hf_raw:
            jm = m.get("jm_metadata") or {}
            source = m.get("source") or m.get("dataset") or m.get("id")
            source_url = m.get("source_url") or m.get("url") or ""
            preview = (
                f"dataset={m.get('dataset') or m.get('source')} "
                f"record={m.get('id')} source={source_url or source} "
                f"tags={m.get('jm_capability') or ''}"
            )
            hf_hits.append(ScoutHit(
                repo_full_name=str(m.get("dataset") or m.get("source") or m.get("id") or "hf-dataset"),
                path=str(m.get("url") or source_url or source),
                language="dataset",
                license_spdx=str(m.get("license", "UNKNOWN")),
                allowed=True,
                score=float(m.get("score", 0.0)),
                preview=preview,
                symbols=tuple(jm.get("tags", [])) if isinstance(jm.get("tags", []), list) else tuple(),
                why=f"Hugging Face dataset record — {m.get('title') or m.get('id')} — matched task: \"{task}\" | source={source}",
                source=str(source),
                source_url=str(source_url),
            ))

        hits = gh_hits + hf_hits

        # Store findings into tree DB
        self.quarry.store_hunt_findings(
            hunt_id=hunt_id,
            task=task,
            hits=hits,
            queries=queries,
        )

        return HuntResult(
            task=task,
            hunt_id=hunt_id,
            queries_used=queries,
            repos_ingested=ingested_summaries,
            hits=hits,
        )

    def _derive_queries(self, task: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", task.lower())
        stop = {
            "with", "from", "into", "that", "this", "have", "will", "your", "about",
            "using", "should", "want", "need", "please", "make", "find", "code",
            "help", "stuff", "things", "something", "anything", "our", "the", "for",
            "and", "can", "you", "get", "all", "some", "use", "its", "also",
        }
        kept = [t for t in tokens if t not in stop]
        if not kept:
            return [task.strip()[:60]]

        queries = [" ".join(kept[:5])]
        if len(kept) >= 2:
            queries.append(" ".join(kept[:2]) + " library")
        if kept:
            queries.append(kept[0] + " implementation")
        return queries

    # ── EXISTING METHODS ──────────────────────────────────────────────────────
    def ingest_repo(self, full_name: str, *, max_files: int = 60) -> dict[str, object]:
        repo = self.github.fetch_repo(full_name)
        verdict = self.license_gate.classify(repo.license_spdx)
        self.quarry.upsert_repo(repo, allowed=verdict.allowed)

        files = self.github.iter_source_files(
            full_name,
            ref=repo.default_branch,
            max_files=max_files,
        )
        ingested = 0
        for repo_file in files:
            enriched = RepoFile(
                path=repo_file.path,
                content=repo_file.content,
                language=repo_file.language,
                sha=repo_file.sha,
                size=repo_file.size,
                symbols=self.extract_symbols(repo_file.path, repo_file.content),
            )
            self.quarry.upsert_file(repo.full_name, enriched)
            ingested += 1
        return {
            "repo": repo.full_name,
            "license": verdict.normalized,
            "allowed": verdict.allowed,
            "ingested_files": ingested,
            "profile": self.profile.name,
        }

    def scout_task(self, task: str, *, limit: int = 8, allowed_only: bool = True) -> list[ScoutHit]:
        query = self.build_query(task)
        hits = self.quarry.search(query, limit=limit, allowed_only=allowed_only)
        return [
            ScoutHit(
                repo_full_name=hit.repo_full_name,
                path=hit.path,
                language=hit.language,
                license_spdx=hit.license_spdx,
                allowed=hit.allowed,
                score=hit.score,
                preview=hit.preview,
                symbols=hit.symbols,
                why=self.explain_hit(task, hit),
            )
            for hit in hits
        ]

    def search_repositories(self, query: str, *, limit: int = 10) -> list[dict[str, object]]:
        results = []
        for repo in self.github.search_repositories(query, limit=limit):
            verdict = self.license_gate.classify(repo.license_spdx)
            results.append(
                {
                    "full_name": repo.full_name,
                    "description": repo.description,
                    "language": repo.language,
                    "stars": repo.stars,
                    "license": verdict.normalized,
                    "allowed": verdict.allowed,
                    "html_url": repo.html_url,
                }
            )
        return results

    @staticmethod
    def build_query(task: str) -> str:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_./:-]{2,}", task.lower())
        stop = {
            "with", "from", "into", "that", "this", "have", "will", "your", "about",
            "using", "should", "want", "need", "please", "make", "find", "code"
        }
        kept: list[str] = []
        for token in tokens:
            if token in stop:
                continue
            if token not in kept:
                kept.append(token)
        if not kept:
            return "code"
        return " ".join(kept[:8])

    @staticmethod
    def classify_hit(hit: ScoutHit) -> tuple[str, str]:
        """Return (category, subcategory) for a hit based on its signals."""
        bag: set[str] = set()
        bag.update(hit.path.lower().replace("/", " ").replace(".", " ").split())
        bag.update(hit.language.lower().split())
        bag.update(s.lower() for s in hit.symbols)
        bag.update(hit.preview.lower().split()[:60])

        for keywords, cat, subcat in _CATEGORY_RULES:
            if keywords & bag:
                return cat, subcat
        return "misc", "general"

    @staticmethod
    def explain_hit(task: str, hit: ScoutHit) -> str:
        """Generate a readable explanation of why this hit is relevant."""
        cat, subcat = JulianMetaMorph.classify_hit(hit)
        sym_list = list(hit.symbols[:5])
        sym_str = ", ".join(f"`{s}`" for s in sym_list) if sym_list else None

        # Category-specific preamble
        preambles = {
            "vrp_starnix": "⚡ VRP: Starnix syscall translation boundary — Linux↔Zircon mismatch",
            "vrp_zircon": "⚡ VRP: Zircon handle/object lifecycle — leak, double-close, use-after-close",
            "vrp_fidl": "⚡ VRP: FIDL protocol boundary — serialization, type confusion, validation gap",
            "vrp_sandbox": "🔴 VRP CRITICAL: Capability routing / sandbox escape vector",
            "vrp_memory": "⚡ VRP: Memory safety — classic high-payout pattern",
            "vrp_concurrency": "⚡ VRP: Race condition / concurrency bug",
            "vrp_driver": "⚡ VRP: Driver boundary — untrusted device input surface",
            "vrp_network": "⚡ VRP: Network stack — packet parsing, protocol state machine",
            "websocket": "Shows WebSocket implementation patterns",
            "streaming": "Demonstrates async streaming / generator patterns",
            "ai_agent": "Contains LLM / agent tooling patterns",
            "memory": "Implements memory, caching, or storage logic",
            "orchestration": "Provides task scheduling or pipeline patterns",
            "ui_server": "HTTP server or frontend rendering patterns",
            "engine_core": "Julia-specific patterns applicable to the engine core",
            "testing": "Test infrastructure patterns",
            "misc": "General implementation patterns",
        }
        preamble = preambles.get(cat, "Relevant implementation")

        parts = [f"{preamble} ({subcat})"]
        if sym_str:
            parts.append(f"— exposes {sym_str}")
        parts.append(f"— from `{hit.path}` in `{hit.repo_full_name}`")
        parts.append(f"— license: {hit.license_spdx}")
        if task:
            parts.append(f"— matched task: \"{task}\"")
        return " ".join(parts)

    @staticmethod
    def extract_symbols(path: str, content: str) -> tuple[str, ...]:
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        patterns = {
            "py": [r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "js": [r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "ts": [r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "tsx": [r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "go": [r"^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)", r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct"],
            "rs": [r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)", r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "jl": [r"^\s*function\s+([A-Za-z_][A-Za-z0-9_!]*)", r"^\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "c": [r"^\s*(?:static\s+)?(?:\w+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\btypedef\s+struct\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "h": [r"^\s*(?:static\s+)?(?:\w+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\btypedef\s+struct\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "cc": [r"^\s*(?:\w+::)*([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "cpp": [r"^\s*(?:\w+::)*([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "cxx": [r"^\s*(?:\w+::)*([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "hpp": [r"^\s*(?:\w+::)*([A-Za-z_][A-Za-z0-9_]*)\s*\(", r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)"],
            "fidl": [r"\bprotocol\s+([A-Za-z_][A-Za-z0-9_]*)", r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)", r"\btable\s+([A-Za-z_][A-Za-z0-9_]*)"],
        }
        results: list[str] = []
        for pattern in patterns.get(suffix, []):
            for match in re.finditer(pattern, content, flags=re.MULTILINE):
                name = match.group(1)
                if name not in results:
                    results.append(name)
        return tuple(results[:32])
