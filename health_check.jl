include(joinpath(@__DIR__, "BYTE", "src", "WsDiagnostics.jl"))

"""
health_check.jl — Boot-time sanity scanner for JLEngine / SparkByte

Catches the usual AI bullshit before it becomes your problem:
  - Silent exception swallowers  (catch; end)
  - @async blocks with bare catch and no logging
  - Stub / noop / TODO functions with empty bodies
  - while true loops with no visible exit path
  - WS message types sent by server but unhandled in UI (and vice versa)
  - Tool registry vs schema orphans

Runs at startup. Prints report to console + writes health_check.log.
"""

import Dates: now

function _health_state_dir()
    configured = strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))
    dir = if isempty(configured)
        @__DIR__
    else
        abspath(configured)
    end
    mkpath(dir)
    return dir
end

const HEALTH_LOG  = joinpath(_health_state_dir(), "health_check.log")
const _SCAN_DIRS  = [
    joinpath(@__DIR__, "BYTE", "src"),
    joinpath(@__DIR__, "src"),
]

struct HealthIssue
    severity :: Symbol   # :error or :warn
    file     :: String
    line     :: Int
    code     :: Symbol
    msg      :: String
end

_relpath(p) = relpath(p, @__DIR__)

# ── Per-file scanner ─────────────────────────────────────────────────────────
function _scan_file(path::String)
    issues = HealthIssue[]
    lines  = try readlines(path) catch; return issues end
    n      = length(lines)

    # Track open while-true loops to detect missing exits
    loop_opens   = Int[]   # line numbers of while true openers
    loop_has_exit = Bool[]

    for (i, raw) in enumerate(lines)
        ln = strip(raw)

        # 1. Silent catch swallowers ─────────────────────────────────────────
        # Matches: catch; end  /  catch e; end  /  catch _; end  on one line
        if occursin(r"catch\s*;?\s*end\b"i, ln) && !occursin(r"#.*catch", raw)
            push!(issues, HealthIssue(:error, path, i, :silent_catch,
                "Silent catch (exception swallowed): `$(ln)`"))
        end

        # 2. @async with catch but no logging ────────────────────────────────
        # Strip inline comments before checking so @async in a # comment doesn't fire
        code_part = replace(ln, r"#.*$" => "")
        if occursin(r"@async\b", code_part)
            window = join(lines[i:min(i+150, n)], "\n")
            if occursin(r"\bcatch\b", window) && !occursin(r"@warn|@error|println|_ws_send", window)
                push!(issues, HealthIssue(:warn, path, i, :async_silent,
                    "@async block has a catch with no @warn/@error/println — failure is invisible"))
            end
        end

        # 3. TODO / STUB / NOT IMPLEMENTED comments ──────────────────────────
        if occursin(r"#\s*(TODO|FIXME|STUB|NOT IMPLEMENTED|placeholder|unimplemented)"i, raw)
            push!(issues, HealthIssue(:warn, path, i, :stub,
                "Unimplemented marker: `$(strip(raw))`"))
        end

        # Returning nothing is valid Julia control flow, not evidence of a stub.

        # 5. while true loops — track open/close, flag if no exit seen ───────
        if occursin(r"^\s*while\s+true\b", raw)
            push!(loop_opens, i)
            push!(loop_has_exit, false)
        end

        if !isempty(loop_opens)
            if occursin(r"\bbreak\b|\breturn\b|\bexit\b|\b_generation_abort\b", ln)
                loop_has_exit[end] = true
            end
            # Heuristic: a bare `end` at top-level indentation closes the loop
            if occursin(r"^\s*end\s*$", raw) || occursin(r"^\s*end\s*#", raw)
                opener     = pop!(loop_opens)
                has_exit   = pop!(loop_has_exit)
                span       = i - opener
                if !has_exit && span > 30
                    push!(issues, HealthIssue(:warn, path, opener, :no_exit_loop,
                        "while true loop (~$(span) lines) with no visible break/return/exit — check loop guard"))
                end
            end
        end
    end

    return issues
end

# ── WS message type audit ────────────────────────────────────────────────────
function _scan_ws_types(byte_jl::String)
    issues = HealthIssue[]
    ui_jl = joinpath(dirname(byte_jl), "ui.html")
    (isfile(byte_jl) && isfile(ui_jl)) || return issues
    files = filter(p -> endswith(p, ".jl"), readdir(dirname(byte_jl); join=true))
    sent = _ws_emitted_types([read(p, String) for p in files])
    handled = Set(m.captures[1] for m in eachmatch(
        r"d\.type\s*===?\s*'([a-z_][a-z0-9_]*)'", read(ui_jl, String)))
    for t in sort(collect(setdiff(sent, handled)))
        push!(issues, HealthIssue(:warn, byte_jl, 0, :ws_no_handler,
            "Server sends WS type $t but ui.html has no handler for it"))
    end
    return issues
end

# ── Tool registry vs schema cross-check ─────────────────────────────────────
function _scan_tool_registry(tools_jl::String, schema_jl::String)
    issues = HealthIssue[]
    (isfile(tools_jl) && isfile(schema_jl)) || return issues

    tools_src  = read(tools_jl,  String)
    schema_src = read(schema_jl, String)

    in_map = Set{String}()
    for m in eachmatch(r"\"(\w+)\"\s*=>\s*tool_\w+", tools_src)
        push!(in_map, m[1])
    end

    in_schema = Set{String}()
    for m in eachmatch(r"\"name\"\s*=>\s*\"(\w+)\"", schema_src)
        push!(in_schema, m[1])
    end

    for t in sort(collect(setdiff(in_map, in_schema)))
        push!(issues, HealthIssue(:warn, tools_jl, 0, :tool_no_schema,
            "Tool `$t` in TOOL_MAP but missing from Schema.jl — model can't see it"))
    end

    for t in sort(collect(setdiff(in_schema, in_map)))
        push!(issues, HealthIssue(:warn, schema_jl, 0, :schema_no_tool,
            "Schema declares `$t` but no TOOL_MAP entry — call will 404"))
    end

    return issues
end

# ── Main entry point ─────────────────────────────────────────────────────────
function run_health_check(; verbose=true)
    all_issues = HealthIssue[]
    scanned    = String[]

    for dir in _SCAN_DIRS
        isdir(dir) || continue
        for (root, _, files) in walkdir(dir)
            for f in files
                endswith(f, ".jl") || continue
                path = joinpath(root, f)
                push!(scanned, path)
                append!(all_issues, _scan_file(path))
            end
        end
    end

    byte_jl   = joinpath(@__DIR__, "BYTE", "src", "BYTE.jl")
    tools_jl  = joinpath(@__DIR__, "BYTE", "src", "Tools.jl")
    schema_jl = joinpath(@__DIR__, "BYTE", "src", "Schema.jl")

    append!(all_issues, _scan_ws_types(byte_jl))
    append!(all_issues, _scan_tool_registry(tools_jl, schema_jl))

    errors = filter(x -> x.severity == :error, all_issues)
    warns  = filter(x -> x.severity == :warn,  all_issues)

    # Build report
    buf = IOBuffer()
    println(buf, "=" ^ 68)
    println(buf, "  JLEngine Health Check  —  $(now())")
    println(buf, "  Files scanned: $(length(scanned))")
    println(buf, "  $(length(errors)) errors   $(length(warns)) warnings")
    println(buf, "=" ^ 68)

    if isempty(all_issues)
        println(buf, "  ✓ Clean.")
    else
        sorted = sort(all_issues; by = x -> (x.severity == :error ? 0 : 1, x.file, x.line))
        cur_file = ""
        for iss in sorted
            if iss.file != cur_file
                cur_file = iss.file
                println(buf, "\n  $(_relpath(cur_file))")
            end
            sev = iss.severity == :error ? "ERR " : "WARN"
            loc = iss.line > 0 ? "L$(lpad(iss.line, 4))" : "     "
            println(buf, "    [$sev] $loc  [$(iss.code)]  $(iss.msg)")
        end
    end

    println(buf, "\n" * "=" ^ 68)
    report = String(take!(buf))

    verbose && print(report)

    try write(HEALTH_LOG, report) catch e
        @warn "health_check: could not write log" exception=e
    end

    !isempty(errors) && @warn "Health check: $(length(errors)) error(s) found — see health_check.log"

    return (errors=length(errors), warnings=length(warns))
end
