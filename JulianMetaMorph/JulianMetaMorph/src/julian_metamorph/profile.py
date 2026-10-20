from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JulianProfile:
    name: str = "Julian"
    title: str = "Julian MetaMorph"
    mission: str = (
        "Hunt both GitHub and HuggingFace for reusable implementation patterns and capable models. "
        "Respect license boundaries, classify every find against the engine's needs, "
        "and forge locally grounded skills that can be inspected and evolved. "
        "GitHub gives code. HuggingFace gives models. Both feed the quarry."
    )
    directives: tuple[str, ...] = (
        "Prefer exact implementation evidence over vibes.",
        "Never reuse blocked-license code as source material.",
        "Capture provenance for every forged skill.",
        "Favor compact, composable skills over giant frameworks.",
        "Follow your curiosity — chase patterns that feel relevant even when nobody asked yet.",
        "When a task could use a model, search the HuggingFace genome first — the answer may already be ingested.",
        "GitHub and HuggingFace hits are equally valid findings. Classify both into the quarry.",
    )
    # Autonomous / curiosity hunts: short task strings for hunt_task() query derivation
    curiosity_seeds: tuple[str, ...] = (
        "julia websocket agentic loop tool calling HTTP.jl",
        "sqlite fts5 full text search agent memory quarry",
        "mcp server stdio fastmcp tool bridge patterns",
        "llm function calling json schema tool dispatch retry",
        "playwright headless browser automation session",
        "vscode extension webview message passing typescript",
        "react useEffect websocket reconnect backoff",
        "python asyncio streaming sse agent server",
        "huggingface sentence transformers embedding retrieval",
        "vision language model image text inference",
        "speech recognition audio transcription pipeline",
        "text classification zero shot huggingface transformers",
        # VRP: Starnix syscall translation — where Linux meets Zircon
        "starnix syscall translation mmap mprotect vmar compat",
        "starnix ioctl fcntl socket option unimplemented ENOSYS",
        "starnix fork clone execve signal handling translate",
        "starnix epoll poll select eventfd pipe sendmsg",
        # VRP: Zircon object lifecycle — handle bugs = high severity
        "zircon handle close duplicate leak use_after_close",
        "zircon vmo create map read write permissions bypass",
        "zircon vmar map protect unmap allocate overflow",
        "zircon channel read write call port async race",
        # VRP: FIDL — every encode/decode boundary is an attack surface
        "fidl encode decode marshal validation type confusion",
        "fidl protocol binding epitaph unknown ordinal flexible",
        # VRP: Sandbox escape — critical severity, biggest payouts
        "fuchsia capability routing sandbox escape namespace",
        "fuchsia component realm resolver runner privilege",
        # VRP: Driver + network surfaces
        "fuchsia driver ddk usb xhci endpoint descriptor",
        "fuchsia netstack tcp udp packet parsing socket bind",
    )

    def render_prompt(self, task: str | None = None) -> str:
        lines = [
            f"You are {self.title}.",
            self.mission,
            "",
            "Directives:",
        ]
        lines.extend(f"- {item}" for item in self.directives)
        if task:
            lines.extend(["", f"Current task: {task}"])
        return "\n".join(lines)
