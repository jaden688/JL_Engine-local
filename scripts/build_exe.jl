"""
Build a standalone SparkByte .exe using PackageCompiler.

Run from anywhere:
    julia scripts/build_exe.jl

Output:
    build/sparkbyte-YYYYMMDD-HHMM/
      bin/sparkbyte.exe   ← the executable (self-contained Julia)
      lib/julia/          ← bundled Julia sysimage
      artifacts/          ← binary deps (SQLite, etc.)
      data/               ← runtime agent files (copied)
      dynamic_tools.jl    ← forged tools state (copied)
      ENV_KEYS_GO_HERE.txt

Python + Playwright still need to be on the target machine for
browser/Mission Control features. Everything else is baked in.
"""

import Pkg
import Dates

const PROJECT_DIR = abspath(joinpath(@__DIR__, ".."))

# ── Preflight ─────────────────────────────────────────────────────────────────
println("\n  ╔══════════════════════════════════════════════╗")
println("  ║     SparkByte EXE Builder — Preflight        ║")
println("  ╚══════════════════════════════════════════════╝\n")

failed = false

function check(label, ok, fix="")
    sym = ok ? "✓" : "✗"
    col = ok ? "\e[32m" : "\e[31m"
    println("  $col$sym\e[0m  $label")
    !ok && !isempty(fix) && println("       → $fix")
    return ok
end

# Julia version
jv = VERSION
check("Julia $jv", jv >= v"1.10",
    "Need Julia 1.10+. Download from https://julialang.org/downloads/") || (failed = true)

# Project.toml exists with julia_main
toml_ok = isfile(joinpath(PROJECT_DIR, "Project.toml"))
check("Project.toml found at $PROJECT_DIR", toml_ok,
    "Run this script from the repo root or adjust PROJECT_DIR") || (failed = true)

# JLEngine source has julia_main
src_ok = isfile(joinpath(PROJECT_DIR, "src", "App.jl")) &&
         occursin("julia_main", read(joinpath(PROJECT_DIR, "src", "App.jl"), String))
check("julia_main() entry point found in src/App.jl", src_ok,
    "julia_main()::Cint must be defined and exported from JLEngine") || (failed = true)

# data/agents exists (runtime data)
data_ok = isfile(joinpath(PROJECT_DIR, "data", "agents", "Agents.mpf.json"))
check("Runtime data/ folder present", data_ok,
    "data/agents/Agents.mpf.json missing — agent configs won't be bundled") || (failed = true)

# PackageCompiler — check global env
pc_ok = try
    Pkg.activate(; temp=true)
    Pkg.add("PackageCompiler"; io=devnull)
    true
catch
    false
end
check("PackageCompiler installed/available", pc_ok,
    "Run: julia -e 'import Pkg; Pkg.add(\"PackageCompiler\")'") || (failed = true)

# Python on PATH
py_ver = try
    out = read(`python --version`, String)
    strip(out)
catch
    ""
end
py_ok = !isempty(py_ver)
check("Python on PATH ($py_ver)", py_ok,
    "Install Python 3.10+ and add to PATH — needed for Playwright/browser features (optional for core engine)")

# Playwright installed
pw_ok = try
    read(`python -c "import playwright; print('ok')"`, String)
    true
catch
    false
end
check("Playwright Python package installed", pw_ok,
    "pip install playwright && playwright install chromium")

# Chromium installed
cr_ok = try
    out = read(`python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('ok')"`, String)
    strip(out) == "ok"
catch
    false
end
check("Playwright Chromium browser available", cr_ok,
    "playwright install chromium")

println()

if failed
    println("  \e[31m✗ Preflight failed — fix errors above before building.\e[0m\n")
    exit(1)
end

println("  \e[32m✓ Preflight passed.\e[0m  Starting build (10–30 min)...\n")

# ── Activate PackageCompiler ──────────────────────────────────────────────────
Pkg.activate(; temp=true)
Pkg.add("PackageCompiler"; io=devnull)
using PackageCompiler

# Re-activate project so create_app sees the right env
Pkg.activate(PROJECT_DIR)

# ── Paths ─────────────────────────────────────────────────────────────────────
const BUILD_TAG  = string("sparkbyte-", Dates.format(Dates.now(), "yyyymmdd-HHMM"))
const OUTPUT_DIR = joinpath(PROJECT_DIR, "build", BUILD_TAG)

@info "Source : $PROJECT_DIR"
@info "Output : $OUTPUT_DIR"

# ── Build ─────────────────────────────────────────────────────────────────────
create_app(
    PROJECT_DIR,
    OUTPUT_DIR;
    executables    = ["sparkbyte" => "julia_main"],
    force          = true,
    incremental    = false,
    filter_stdlibs = true,
)

# ── Copy runtime data ─────────────────────────────────────────────────────────
@info "Copying runtime files…"

function copy_item(rel)
    src = joinpath(PROJECT_DIR, rel)
    dst = joinpath(OUTPUT_DIR, rel)
    if isfile(src)
        mkpath(dirname(dst))
        cp(src, dst; force=true)
        @info "  ✓  $rel"
    elseif isdir(src)
        cp(src, dst; force=true)
        @info "  ✓  $rel/"
    else
        @warn "  –  $rel (not found, skipped)"
    end
end

copy_item("data")
copy_item("dynamic_tools.jl")
copy_item("dynamic_tools_registry.json")

for db in ("sparkbyte_memory.db", "a2a_accounts.db", "a2a_usage.db")
    isfile(joinpath(PROJECT_DIR, db)) && copy_item(db)
end

open(joinpath(OUTPUT_DIR, "ENV_KEYS_GO_HERE.txt"), "w") do io
    write(io, """
SparkByte Snapshot — ENV Setup
================================
Copy your .env file into this directory before running sparkbyte.exe.

Required:
  GEMINI_API_KEY=...

Optional:
  OPENAI_API_KEY=...  XAI_API_KEY=...
  A2A_API_KEY=...     A2A_ADMIN_KEY=...
  REDDIT_CLIENT_ID=...
  REDDIT_CLIENT_SECRET=...
  REDDIT_REFRESH_TOKEN=...

Python (for browser/Mission Control):
  Python 3.10+ on PATH + pip install playwright + playwright install chromium

Run:
  bin\\sparkbyte.exe
""")
end

println("\n  ╔══════════════════════════════════════════════╗")
println("  ║          BUILD COMPLETE                      ║")
println("  ╠══════════════════════════════════════════════╣")
println("  ║  EXE: build\\$(BUILD_TAG)\\bin\\sparkbyte.exe")
println("  ║  Drop your .env into: build\\$(BUILD_TAG)\\")
println("  ╚══════════════════════════════════════════════╝\n")
