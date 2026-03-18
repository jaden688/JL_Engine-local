from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import wrap
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PDF = REPO_ROOT / "docs" / "JL_Engine_Project_Overview.pdf"

BG = "#0b1020"
PANEL = "#111827"
PANEL_2 = "#162033"
ACCENT = "#2dd4bf"
ACCENT_2 = "#f59e0b"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
LINE = "#334155"

SLIDE_W = 13.333
SLIDE_H = 7.5


@dataclass
class Slide:
    title: str
    subtitle: str
    builder: Callable[[Any], None]


def make_figure():
    fig = plt.figure(figsize=(SLIDE_W, SLIDE_H), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=BG, edgecolor="none"))
    ax.add_patch(Rectangle((0, 0.965), 1, 0.035, facecolor=ACCENT, edgecolor="none", alpha=0.95))
    ax.add_patch(Rectangle((0, 0.952), 0.22, 0.01, facecolor=ACCENT_2, edgecolor="none"))
    ax.add_patch(Rectangle((0.22, 0.952), 0.22, 0.01, facecolor=ACCENT, edgecolor="none"))
    ax.add_patch(Rectangle((0.44, 0.952), 0.56, 0.01, facecolor="#22c55e", edgecolor="none"))
    return fig, ax


def add_header(ax, title: str, subtitle: str = "", page: int = 1, total: int = 1):
    ax.text(
        0.06,
        0.915,
        title,
        color=TEXT,
        fontsize=28,
        fontweight="bold",
        va="top",
        ha="left",
    )
    if subtitle:
        ax.text(
            0.06,
            0.865,
            subtitle,
            color=MUTED,
            fontsize=12,
            va="top",
            ha="left",
        )
    ax.text(
        0.94,
        0.915,
        f"{page:02d}/{total:02d}",
        color=MUTED,
        fontsize=11,
        va="top",
        ha="right",
        family="DejaVu Sans Mono",
    )


def footer(ax, text: str):
    ax.text(0.06, 0.035, text, color=MUTED, fontsize=9, va="bottom", ha="left")


def draw_card(ax, x: float, y: float, w: float, h: float, title: str, body: str, *, facecolor=PANEL, edgecolor=LINE, title_color=TEXT, body_color=TEXT, title_size=14, body_size=11, mono=False):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.015",
        linewidth=1.2,
        edgecolor=edgecolor,
        facecolor=facecolor,
        alpha=0.98,
    )
    ax.add_patch(patch)
    ax.text(
        x + 0.02,
        y + h - 0.04,
        title,
        color=title_color,
        fontsize=title_size,
        fontweight="bold",
        va="top",
        ha="left",
    )
    if body:
        ax.text(
            x + 0.02,
            y + h - 0.10,
            body,
            color=body_color,
            fontsize=body_size,
            va="top",
            ha="left",
            family="DejaVu Sans Mono" if mono else "DejaVu Sans",
            linespacing=1.25,
        )


def draw_bullets(ax, bullets: list[str], x: float, y: float, width: int = 64, size: int = 13, line_step: float = 0.040):
    current = y
    for bullet in bullets:
        wrapped = wrap(bullet, width=width, break_long_words=False, break_on_hyphens=False) or [bullet]
        ax.text(x, current, "-", color=ACCENT, fontsize=size + 1, va="top", ha="left")
        ax.text(
            x + 0.02,
            current,
            "\n".join(wrapped),
            color=TEXT,
            fontsize=size,
            va="top",
            ha="left",
            linespacing=1.25,
        )
        current -= line_step * max(1, len(wrapped))
    return current


def draw_chip(ax, x: float, y: float, w: float, label: str, color: str):
    chip = FancyBboxPatch(
        (x, y),
        w,
        0.055,
        boxstyle="round,pad=0.010,rounding_size=0.025",
        linewidth=0,
        facecolor=color,
        alpha=0.98,
    )
    ax.add_patch(chip)
    ax.text(
        x + w / 2,
        y + 0.028,
        label,
        color=BG,
        fontsize=10,
        fontweight="bold",
        ha="center",
        va="center",
        family="DejaVu Sans Mono",
    )


def cover_slide(ax):
    ax.add_patch(Rectangle((0.58, 0.10), 0.34, 0.72, facecolor=PANEL_2, edgecolor=LINE, linewidth=1.2, alpha=0.98))
    ax.add_patch(Rectangle((0.61, 0.68), 0.28, 0.03, facecolor=ACCENT, edgecolor="none"))
    ax.add_patch(Rectangle((0.61, 0.63), 0.18, 0.02, facecolor=ACCENT_2, edgecolor="none"))

    ax.text(0.08, 0.82, "JL Engine Local", color=TEXT, fontsize=34, fontweight="bold", ha="left", va="top")
    ax.text(
        0.08,
        0.75,
        "Project overview for the local-first engine, persona runtime, and operator stack",
        color=MUTED,
        fontsize=15,
        ha="left",
        va="top",
    )
    ax.text(
        0.08,
        0.63,
        "One repo, two layers:\nJL Engine core + JL Platform runtime",
        color=TEXT,
        fontsize=22,
        ha="left",
        va="top",
        linespacing=1.15,
    )
    draw_chip(ax, 0.08, 0.48, 0.12, "MIT", ACCENT)
    draw_chip(ax, 0.21, 0.48, 0.18, "Python 3.10+", ACCENT_2)
    draw_chip(ax, 0.40, 0.48, 0.26, "Windows / macOS / Linux", "#22c55e")

    ax.text(0.08, 0.36, "Default voice:", color=MUTED, fontsize=12, ha="left", va="top")
    ax.text(0.08, 0.30, "SparkByte", color=TEXT, fontsize=20, fontweight="bold", ha="left", va="top")
    ax.text(
        0.08,
        0.22,
        "Launch local. Keep the engine local. Give the operator the full deck.",
        color=TEXT,
        fontsize=13,
        ha="left",
        va="top",
    )

    draw_card(
        ax,
        0.62,
        0.53,
        0.28,
        0.21,
        "At a glance",
        "Local runtime\nAgent registry\nCommand deck UI\nCLI / API access",
        facecolor="#18243a",
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.62,
        0.27,
        0.28,
        0.18,
        "Primary surface",
        "/ui/ command deck\nBacked by the FastAPI app",
        facecolor="#18243a",
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )


def overview_slide(ax):
    draw_bullets(
        ax,
        [
            "JL Engine is the orchestration layer for personality, memory, cognitive state, rhythm, and backend routing.",
            "JL Platform is the local operator/runtime layer: API, quest sessions, interpreter, browser bridge, and workspace tools.",
            "The command deck, the CLI, and the API all ride on the same runtime instead of separate stacks.",
            "Agents are loaded as payload files through a short MPF registry, so behavior stays data-driven.",
            "Local tooling is powerful by design, but the trusted-machine boundary matters; the admin routes are not internet-safe by default.",
        ],
        0.08,
        0.78,
        width=66,
        size=13,
        line_step=0.043,
    )
    draw_card(
        ax,
        0.66,
        0.20,
        0.26,
        0.50,
        "Entry points",
        "j-engine\nj-agent\njl-engine\njl-agent\ncli",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=13,
        mono=True,
    )
    draw_card(
        ax,
        0.66,
        0.72,
        0.26,
        0.12,
        "Install modes",
        "api | browser | ui | full",
        facecolor=PANEL_2,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    footer(ax, "Source anchors: README.md, pyproject.toml, docs/AGENTS.md, docs/MPF_OPEN_STANDARD.md")


def repo_map_slide(ax):
    boxes = [
        (0.07, 0.56, 0.26, 0.22, "jl_engine_core/", "Engine orchestration, memory, rhythm, cognitive gears, MPF loading, backends."),
        (0.36, 0.56, 0.26, 0.22, "src/jl_platform/", "FastAPI service, quest runtime, interpreter, browser bridge, local tools."),
        (0.65, 0.56, 0.28, 0.22, "src/jl_engine_cli/", "Headless CLI, slash commands, agent selection, backend toggles."),
        (0.07, 0.25, 0.40, 0.20, "ui_web/ + ui_easy/", "The main command deck and the lighter flow deck served by the same API."),
        (0.50, 0.25, 0.43, 0.20, "docs/ + tools/ + tests/", "Docs, generators, local automation scripts, and the regression suite."),
    ]
    for x, y, w, h, title, body in boxes:
        draw_card(ax, x, y, w, h, title, body, facecolor=PANEL, edgecolor=LINE, body_size=11)
    draw_card(
        ax,
        0.07,
        0.08,
        0.86,
        0.11,
        "Canonical runtime data",
        "jl_engine_core/data/agents/JL_Agents.mpf.json + payload files under jl_engine_core/data/ are the main source of truth for agent behavior.",
        facecolor="#18243a",
        edgecolor=ACCENT,
        body_size=12,
    )
    footer(ax, "The runtime favors data files over hard-coded personas, which makes the system easy to extend.")


def launch_slide(ax):
    draw_card(
        ax,
        0.07,
        0.62,
        0.24,
        0.16,
        "Windows fast start",
        "start.bat\n-> j-engine --unsafe-tools --auto-approve",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.37,
        0.62,
        0.28,
        0.16,
        "Command deck launch",
        "run_command_deck.ps1\n-> jl_platform.services.api.main:app",
        facecolor=PANEL_2,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.71,
        0.62,
        0.22,
        0.16,
        "Health gate",
        "/health\nthen open /ui/",
        facecolor=PANEL_2,
        edgecolor="#22c55e",
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.18,
        0.33,
        0.26,
        0.16,
        "CLI path",
        "j-engine --agent SparkByte",
        facecolor=PANEL,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.56,
        0.33,
        0.24,
        0.16,
        "Local defaults",
        "127.0.0.1:8000\nNo public bind by default",
        facecolor=PANEL,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    ax.add_patch(FancyArrowPatch((0.31, 0.70), (0.37, 0.70), arrowstyle="->", mutation_scale=16, linewidth=2, color=ACCENT))
    ax.add_patch(FancyArrowPatch((0.65, 0.70), (0.71, 0.70), arrowstyle="->", mutation_scale=16, linewidth=2, color=ACCENT_2))
    ax.add_patch(FancyArrowPatch((0.30, 0.40), (0.56, 0.40), arrowstyle="->", mutation_scale=16, linewidth=2, color="#22c55e"))
    draw_bullets(
        ax,
        [
            "The Windows launcher keeps the runtime local and opens the deck automatically when the health check passes.",
            "The CLI is separate, but it still uses the same core registry and backend configuration.",
            "The important thing is the launch contract, not the skin: one engine, multiple entrypoints.",
        ],
        0.08,
        0.18,
        width=72,
        size=12,
        line_step=0.044,
    )


def core_slide(ax):
    cards = [
        (0.07, 0.56, 0.26, 0.22, "Orchestrator", "JLEngineCore coordinates response generation, telemetry, and the active agent."),
        (0.36, 0.56, 0.26, 0.22, "State engines", "Behavior, cognitive modes, cognitive gears, rhythm, drift pressure, emotional aperture."),
        (0.65, 0.56, 0.28, 0.22, "Memory + backends", "Hybrid memory and backend routing for Ollama, OpenAI, OpenRouter, or Gemini."),
        (0.07, 0.25, 0.40, 0.20, "MPF registry loader", "Loads the short registry and resolves the full payload for the active agent."),
        (0.50, 0.25, 0.43, 0.20, "Output contract", "Returns reply, telemetry, and feedback so callers can show state and trace details."),
    ]
    for x, y, w, h, title, body in cards:
        draw_card(ax, x, y, w, h, title, body, facecolor=PANEL, edgecolor=LINE, body_size=11)
    draw_card(
        ax,
        0.07,
        0.08,
        0.86,
        0.11,
        "Key modules",
        "behavior_engine.py | cognitive_gears.py | cognitive_modes.py | emotional_aperture.py | rhythm.py | drift_pressure.py | hybrid_memory.py | temporal_field.py",
        facecolor="#18243a",
        edgecolor=ACCENT,
        body_size=11,
        mono=True,
    )
    footer(ax, "The core is UI-agnostic, so the same engine can back the CLI, API, or future surfaces.")


def platform_slide(ax):
    draw_card(
        ax,
        0.07,
        0.60,
        0.40,
        0.19,
        "Quest runtime",
        "FatQuestRuntime manages agent sessions, side quests, clone-on-failure, and agent loops.",
        facecolor=PANEL,
        edgecolor=ACCENT,
        body_size=12,
    )
    draw_card(
        ax,
        0.53,
        0.60,
        0.39,
        0.19,
        "Interpreter",
        "InterpreterSession handles tool calls, direct action fallback, and confirmation gating.",
        facecolor=PANEL,
        edgecolor=ACCENT_2,
        body_size=12,
    )
    draw_card(
        ax,
        0.07,
        0.31,
        0.27,
        0.16,
        "Browser bridge",
        "Playwright-backed local browser control and inspection.",
        facecolor=PANEL_2,
        edgecolor="#22c55e",
        body_size=12,
    )
    draw_card(
        ax,
        0.37,
        0.31,
        0.27,
        0.16,
        "Workspace tools",
        "List, read, save, and review files inside the workspace root.",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=12,
    )
    draw_card(
        ax,
        0.67,
        0.31,
        0.25,
        0.16,
        "Self-edit loop",
        "Autostartable local loop for controlled self-modifying workflows.",
        facecolor=PANEL_2,
        edgecolor=ACCENT_2,
        body_size=12,
    )
    draw_card(
        ax,
        0.07,
        0.08,
        0.85,
        0.10,
        "API surface",
        "/quest/* | /interpreter/run | /browser/* | /workspace/* | /self-edit/* | /tools/*",
        facecolor="#18243a",
        edgecolor=ACCENT,
        body_size=11,
        mono=True,
    )
    footer(ax, "The security model assumes this runs on a trusted local machine unless you add your own boundary.")


def agents_slide(ax):
    draw_card(
        ax,
        0.07,
        0.55,
        0.38,
        0.25,
        "How it works",
        "1. Read the MPF registry entry.\n2. Resolve the payload file.\n3. Expand modular payloads if needed.\n4. Load the resolved persona into the active session.",
        facecolor=PANEL,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.50,
        0.55,
        0.42,
        0.25,
        "Built-in agent examples",
        "SparkByte | Slappy | The Gremlin | Supervisor\nSaaS Copywriter | Cold Outreach Assistant\nYouTube Scriptwriter | Brand Voice Generator\nStartup Pitch Writer | Forgebinder",
        facecolor=PANEL,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.07,
        0.23,
        0.38,
        0.16,
        "Registry path",
        "jl_engine_core/data/agents/JL_Agents.mpf.json",
        facecolor=PANEL_2,
        edgecolor="#22c55e",
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.50,
        0.23,
        0.42,
        0.16,
        "Payload families",
        "fat_agents/ | jl_agents/ | generated/",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    footer(ax, "The registry stays small; the payloads carry the full behavior, voice, and backend defaults.")


def ui_slide(ax):
    draw_card(
        ax,
        0.07,
        0.56,
        0.25,
        0.22,
        "/ui/",
        "Full command deck\nChat, agents, tools, files, browser, self-edit",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.37,
        0.56,
        0.25,
        0.22,
        "/ui-easy/",
        "Lighter flow deck\nReduced surface area",
        facecolor=PANEL_2,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.67,
        0.56,
        0.26,
        0.22,
        "CLI",
        "j-engine\nSlash commands\nAgent switching\nBackend selection",
        facecolor=PANEL_2,
        edgecolor="#22c55e",
        body_size=12,
        mono=True,
    )
    draw_bullets(
        ax,
        [
            "The web UI is not a separate app; it is a view over the same API and runtime state.",
            "Agent selection, workspace browsing, and tool execution all stay inside the command deck flow.",
            "The UI also reflects browser-session state, benchmark state, and self-edit status.",
        ],
        0.08,
        0.28,
        width=74,
        size=12,
        line_step=0.043,
    )
    footer(ax, "UI behavior is driven by ui_web/app.js and backed by the same local API routes.")


def safety_slide(ax):
    draw_card(
        ax,
        0.07,
        0.56,
        0.40,
        0.24,
        "Local operator surfaces",
        "shell, cc bridge, browser, workspace, forge, audit, self-edit, and privileged memory tools.",
        facecolor=PANEL,
        edgecolor=ACCENT,
        body_size=12,
    )
    draw_card(
        ax,
        0.53,
        0.56,
        0.39,
        0.24,
        "Safer defaults",
        "Keep the service on 127.0.0.1, gate dangerous actions, and treat admin routes as trusted-machine only.",
        facecolor=PANEL,
        edgecolor=ACCENT_2,
        body_size=12,
    )
    draw_card(
        ax,
        0.07,
        0.24,
        0.40,
        0.18,
        "Tests",
        "pytest coverage for runtime, browser bridge, tool forge, memory, CLI, schemas, and launch behavior.",
        facecolor=PANEL_2,
        edgecolor="#22c55e",
        body_size=12,
    )
    draw_card(
        ax,
        0.53,
        0.24,
        0.39,
        0.18,
        "Bench manager",
        "tools/bench_manager.py watches repo changes and helps keep the runtime honest.",
        facecolor=PANEL_2,
        edgecolor=ACCENT,
        body_size=12,
    )
    footer(ax, "The main safety move is simple: do not expose the local admin surfaces to the public internet without adding auth and proxy controls.")


def docs_slide(ax):
    draw_card(
        ax,
        0.07,
        0.53,
        0.26,
        0.24,
        "Read first",
        "README.md\nONBOARDING.md\nARCHITECTURE.md",
        facecolor=PANEL,
        edgecolor=ACCENT,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.37,
        0.53,
        0.26,
        0.24,
        "Runtime docs",
        "docs/AGENTS.md\ndocs/MPF_OPEN_STANDARD.md\ndocs/TOOL_FORGE.md",
        facecolor=PANEL,
        edgecolor=ACCENT_2,
        body_size=12,
        mono=True,
    )
    draw_card(
        ax,
        0.67,
        0.53,
        0.26,
        0.24,
        "Safety docs",
        "SECURITY.md\nTROUBLESHOOTING.md\ndocs/ERROR_HANDLING.md",
        facecolor=PANEL,
        edgecolor="#22c55e",
        body_size=12,
        mono=True,
    )
    draw_bullets(
        ax,
        [
            "Launch locally, pick SparkByte, and verify the health endpoint before touching the heavier surfaces.",
            "Treat the operator tools as local-only until you explicitly harden them for remote access.",
            "If the project changes, regenerate the deck with the script so the overview stays current.",
        ],
        0.08,
        0.25,
        width=74,
        size=12,
        line_step=0.044,
    )
    draw_card(
        ax,
        0.08,
        0.08,
        0.84,
        0.10,
        "Generated from current checkout",
        f"{REPO_ROOT.name} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        facecolor="#18243a",
        edgecolor=ACCENT,
        body_size=11,
        mono=True,
    )


def build_slides():
    return [
        Slide("JL Engine Local", "Project overview for the local-first engine, persona runtime, and operator stack.", cover_slide),
        Slide("What this repository is", "A local-first runtime for agent sessions, operator tools, browser control, and a rich persona system.", overview_slide),
        Slide("Repository map", "The codebase is split into a core engine, a platform runtime, UI surfaces, and supporting docs/tools/tests.", repo_map_slide),
        Slide("Launch paths", "This repo has a few front doors, but they all converge on the same local runtime.", launch_slide),
        Slide("JL Engine core", "This is the brain: state, agents, memory, rhythm, emotional aperture, and backend routing.", core_slide),
        Slide("Platform runtime", "JL Platform wraps the core engine in local workflows and admin surfaces.", platform_slide),
        Slide("Agents and MPF", "Agents are data, not hard-coded behavior. The registry points to payloads and the payloads carry the persona.", agents_slide),
        Slide("UI surfaces and user flows", "The deck is the main product surface, but the CLI and the lighter UI are part of the same system.", ui_slide),
        Slide("Tools, tests, and safety", "This repo is powerful by design, so the trust boundary and regression coverage matter.", safety_slide),
        Slide("Docs and next steps", "The docs are unusually complete. Start there, then use the deck or CLI to exercise the runtime.", docs_slide),
    ]


def main() -> int:
    slides = build_slides()
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUTPUT_PDF) as pdf:
        metadata = pdf.infodict()
        metadata["Title"] = "JL Engine Local Project Overview"
        metadata["Author"] = "Codex"
        metadata["Subject"] = "JL Engine Local architecture and launch overview"
        metadata["Keywords"] = "JL Engine, local runtime, agents, platform, overview"
        metadata["CreationDate"] = datetime.now()

        total = len(slides)
        for idx, slide in enumerate(slides, start=1):
            fig, ax = make_figure()
            if idx > 1:
                add_header(ax, slide.title, slide.subtitle, page=idx, total=total)
            slide.builder(ax)
            pdf.savefig(fig, facecolor=BG, dpi=200)
            plt.close(fig)

    print(f"Wrote {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
