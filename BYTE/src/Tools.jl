haskey(ENV, "JULIA_CONDAPKG_BACKEND") || (ENV["JULIA_CONDAPKG_BACKEND"] = "Null")
include("WsDiagnostics.jl")
haskey(ENV, "JULIA_PYTHONCALL_EXE") || (ENV["JULIA_PYTHONCALL_EXE"] = "python")

using SQLite, DataFrames, Dates, JSON, HTTP, Base64

# Python is optional: without it the engine runs fine, just with browser/
# Python-backed tools disabled. PythonCall must NOT be loaded at include/
# precompile time — that would bake a hard Python dependency into the
# package cache and abort boot on machines without Python (or with Python
# removed after the cache was built). Load it lazily on first use instead.
const _PYTHONCALL = Ref{Any}(nothing)
python_available() = Sys.which(get(ENV, "JULIA_PYTHONCALL_EXE", "python")) !== nothing
function _python_module()
    if _PYTHONCALL[] === nothing
        python_available() || error("Python is not installed on this machine — this tool needs Python 3 (see INSTALL.md)")
        _PYTHONCALL[] = Base.require(Base.PkgId(Base.UUID("6099a3de-0909-46bc-b1f4-468b9a2dfc0d"), "PythonCall"))
    end
    return _PYTHONCALL[]
end
pyimport(name) = _python_module().pyimport(name)
pyconvert(T, x) = _python_module().pyconvert(T, x)

# Lazy-initialized singletons — set by BYTE.init()
const _state = Dict{Symbol, Any}(
    :db => nothing,
    :browser_context => nothing,
)

# Mutable live registry for dynamically forged tools
const DYNAMIC_SCHEMA       = Dict{String,Any}[]
const _project_root        = Ref{String}("")
const _session_event_count = Ref{Int}(0)

# ── Forge event hooks — registered by BYTE on init for live dashboard broadcast ──
# Each entry is fn(name::String, code::String, description::String) -> nothing
const _FORGE_HOOKS = Function[]

# ── Live Memory Listener ──────────────────────────────────────────────────────

function _db_write_thought(context::String, thought::String, mood::String, gait::String, agent::String="SparkByte"; type::String="diary", model::String="")
    db = _state[:db]
    db === nothing && return
    try
        SQLite.execute(db,
            "INSERT INTO thoughts (timestamp, agent, context, thought, mood, gait, type, model) VALUES (?,?,?,?,?,?,?,?)",
            (string(now()), agent, first(context, 120), first(thought, 400), mood, gait, type, model))
        _session_event_count[] += 1
    catch e
        @warn "Thought write failed" exception=(e, catch_backtrace())
    end
end

function _db_write_turn_snapshot(snapshot::Dict, agent::String, model::String,
                                  session_id::String, turn_number::Int,
                                  user_msg_len::Int, reply_len::Int, elapsed_ms::Int)
    db = _state[:db]
    db === nothing && return
    try
        rhythm    = get(snapshot, "rhythm",        Dict())
        aperture  = get(snapshot, "aperture_state", Dict())
        behavior  = get(snapshot, "behavior_state", Dict())
        drift     = get(snapshot, "drift",          Dict())
        advisory  = get(snapshot, "advisory",       Dict())
        SQLite.execute(db, """
            INSERT INTO turn_snapshots
            (timestamp, session_id, turn_number, agent, model,
             gait, rhythm_mode, rhythm_momentum,
             aperture_mode, aperture_temp, aperture_top_p,
             behavior_state, behavior_expressiveness, behavior_pacing, behavior_tone,
             drift_pressure, drift_temp_delta, drift_action_level,
             advisory_bias, advisory_emotional_drift, advisory_msg,
             user_msg_len, reply_len, elapsed_ms)
            VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?)""",
            (string(now()), session_id, turn_number, agent, model,
             string(get(snapshot, "gait", "")),
             string(get(rhythm, "mode", "")),
             Float64(get(rhythm, "momentum", 0.0)),
             string(get(aperture, "mode", "")),
             Float64(get(aperture, "temp", 0.0)),
             Float64(get(aperture, "top_p", 0.0)),
             string(get(behavior, "name", "")),
             Float64(get(behavior, "expressiveness", 0.0)),
             string(get(behavior, "pacing", "")),
             string(get(behavior, "tone_bias", "")),
             Float64(get(drift, "pressure", 0.0)),
             Float64(get(drift, "temperature_delta", 0.0)),
             string(get(drift, "action_level", "")),
             string(get(advisory, "gating_bias", "")),
             string(get(advisory, "emotional_drift", "")),
             string(get(advisory, "msg", "")),
             user_msg_len, reply_len, elapsed_ms))
        _session_event_count[] += 1
    catch e
        @warn "Turn snapshot write failed" exception=(e, catch_backtrace())
    end
end

# Store raw reasoning/thinking traces from reasoning models
function _db_write_reasoning(context::AbstractString, reasoning::AbstractString, model::AbstractString, agent::AbstractString="SparkByte")
    db = _state[:db]
    db === nothing && return
    isempty(strip(reasoning)) && return
    try
        SQLite.execute(db,
            "INSERT INTO thoughts (timestamp, agent, context, thought, mood, gait, type, model) VALUES (?,?,?,?,?,?,?,?)",
            (string(now()), agent, first(context, 120), first(reasoning, 2000), "reasoning", "auto", "reasoning", model))
        _session_event_count[] += 1
    catch e
        @warn "Reasoning write failed" exception=(e, catch_backtrace())
    end
end

function _db_write_tool_usage(name::String, args_json::String, result_json::String, elapsed_ms::Int, agent::String)
    db = _state[:db]
    db === nothing && return
    try
        SQLite.execute(db,
            "INSERT INTO tool_usage_log (timestamp, tool_name, args_json, result_json, duration_ms, agent, session_id) VALUES (?,?,?,?,?,?,?)",
            (string(now()), name, first(args_json, 500), first(result_json, 500), elapsed_ms, agent, isdefined(@__MODULE__, :_session_id) ? string(getfield(@__MODULE__, :_session_id)[]) : "unknown"))
        SQLite.execute(db, "UPDATE tools SET call_count = call_count + 1, last_used = ? WHERE name = ?", (string(now()), name))
        _session_event_count[] += 1
    catch e
        @warn "Tool usage write failed" exception=(e, catch_backtrace())
    end
end

function _db_write_web_cache(url::String, content::String)
    db = _state[:db]
    db === nothing && return
    try
        existing = DBInterface.execute(db, "SELECT id FROM web_cache WHERE url = ?", (url,)) |> DataFrame
        summary = first(content, 300)
        if isempty(existing)
            DBInterface.execute(db,
                "INSERT INTO web_cache (url, fetched_at, content, summary, tags) VALUES (?,?,?,?,?)",
                (url, string(now()), first(content, 5000), summary, "browsed"))
        else
            DBInterface.execute(db,
                "UPDATE web_cache SET fetched_at=?, content=?, summary=? WHERE url=?",
                (string(now()), first(content, 5000), summary, url))
        end
        _session_event_count[] += 1
    catch e
        @warn "Web cache write failed" url=url exception=(e, catch_backtrace())
    end
end

function _db_start_session(session_id::String)
    db = _state[:db]
    db === nothing && return
    try
        SQLite.execute(db,
            "INSERT INTO sessions (session_id, started_at, os, julia_ver, events, notes) VALUES (?,?,?,?,?,?)",
            (session_id, string(now()), string(Sys.KERNEL), string(VERSION), 0, "Boot"))
    catch e
        @warn "Session start write failed" session_id=session_id exception=(e, catch_backtrace())
    end
end

function _db_end_session(session_id::String)
    db = _state[:db]
    db === nothing && return
    try
        SQLite.execute(db,
            "UPDATE sessions SET ended_at=?, events=? WHERE session_id=? AND ended_at IS NULL",
            (string(now()), _session_event_count[], session_id))
    catch e
        @warn "Session end write failed" session_id=session_id exception=(e, catch_backtrace())
    end
end

# Called once at startup from BYTE.init()
function init_tools(db::SQLite.DB, browser_context, project_root::String="")
    _state[:db] = db
    _state[:browser_context] = browser_context
    _project_root[] = project_root
    if !isempty(project_root)
        _load_dynamic_tools!(project_root)
    end
    
    # Populate the tools SQL table on startup
    try
        for decl in TOOLS_SCHEMA[1]["function_declarations"]
            name = string(decl["name"])
            desc = string(get(decl, "description", ""))
            params = JSON.json(get(decl, "parameters", Dict()))
            SQLite.execute(db, """
                INSERT OR REPLACE INTO tools (name, source, description, parameters, is_dynamic, call_count)
                VALUES (?, 'builtin', ?, ?, 0, COALESCE((SELECT call_count FROM tools WHERE name = ?), 0))
            """, (name, desc, params, name))
        end
        for dyn in DYNAMIC_SCHEMA
            name = string(dyn["name"])
            desc = string(get(dyn, "description", ""))
            params = JSON.json(get(dyn, "parameters", Dict()))
            SQLite.execute(db, """
                INSERT OR REPLACE INTO tools (name, source, description, parameters, is_dynamic, call_count)
                VALUES (?, 'dynamic', ?, ?, 1, COALESCE((SELECT call_count FROM tools WHERE name = ?), 0))
            """, (name, desc, params, name))
        end
    catch e
        @warn "Failed to sync tools table on startup" exception=(e, catch_backtrace())
    end
end

function _runtime_state_dir(root::String="")
    configured = strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))
    if !isempty(configured)
        dir = abspath(configured)                    # explicit override: use as-is (flat)
    else
        base = !isempty(root) ? root : (!isempty(_project_root[]) ? _project_root[] : pwd())
        dir = abspath(joinpath(base, "data"))        # default: dedicated data/ folder, not root
    end
    mkpath(dir)
    return dir
end

_runtime_state_path(parts...; root::String="") = joinpath(_runtime_state_dir(root), parts...)

function _julia_command(project_root::String="")
    julia_exe = joinpath(Sys.BINDIR, Sys.iswindows() ? "julia.exe" : "julia")
    if isfile(julia_exe)
        return isempty(project_root) ? `$julia_exe` : `$julia_exe --project=$project_root`
    end
    return isempty(project_root) ? `julia` : `julia --project=$project_root`
end

# One-time migration: earlier builds wrote forged tools + registry to the
# project ROOT. They now live under data/. On boot, if the new location is
# empty but a legacy root-level copy exists, move it so forged tools survive
# the relocation. Skipped when SPARKBYTE_STATE_DIR pins a custom dir.
function _migrate_legacy_runtime_state!(root::String)
    isempty(strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))) || return
    base = !isempty(root) ? root : (!isempty(_project_root[]) ? _project_root[] : pwd())
    for name in ("dynamic_tools.jl", "dynamic_tools_registry.json")
        legacy  = abspath(joinpath(base, name))
        current = _runtime_state_path(name; root=root)
        if legacy != current && isfile(legacy) && !isfile(current)
            try
                mkpath(dirname(current))
                mv(legacy, current)
                @info "Migrated runtime state root → data/" file=name
            catch e
                @warn "Runtime-state migration failed" file=name exception=(e, catch_backtrace())
            end
        end
    end
end

"""Load previously forged tools from disk into live runtime on boot."""
function _load_dynamic_tools!(root::String)
    _migrate_legacy_runtime_state!(root)
    tools_file    = _runtime_state_path("dynamic_tools.jl"; root=root)
    registry_file = _runtime_state_path("dynamic_tools_registry.json"; root=root)

    # Eval all function definitions into BYTE module scope
    if isfile(tools_file)
        try
            exprs = Meta.parseall(read(tools_file, String))
            for expr in exprs.args
                expr isa LineNumberNode && continue
                try
                    Core.eval(@__MODULE__, expr)
                catch e
                    @warn "Dynamic tool eval failed" expr=sprint(show, expr) exception=(e, catch_backtrace())
                end
            end
        catch e
            @warn "dynamic_tools.jl load error: $e"
        end
    end

    # Rebuild TOOL_MAP + DYNAMIC_SCHEMA from registry
    if isfile(registry_file)
        try
            registry = JSON.parsefile(registry_file)
            for entry in registry
                name   = string(get(entry, "name", ""))
                fn_sym = Symbol("tool_$name")
                isempty(name) && continue
                if isdefined(@__MODULE__, fn_sym)
                    # Use invokelatest wrapper to satisfy Julia 1.12 world age semantics
                    local _sym = fn_sym
                    TOOL_MAP[name] = (args) -> Base.invokelatest(getfield(@__MODULE__, _sym), args)
                    filter!(e -> e["name"] != name, DYNAMIC_SCHEMA)
                    push!(DYNAMIC_SCHEMA, Dict{String,Any}(
                        "name"        => name,
                        "description" => string(get(entry, "description", "Dynamic tool: $name")),
                        "parameters"  => get(entry, "parameters", Dict{String,Any}(
                            "type"=>"OBJECT","properties"=>Dict{String,Any}(),"required"=>String[])),
                    ))
                end
            end
            isempty(registry) || println("⚡ Loaded $(length(registry)) dynamic tool(s): $(join([get(e,"name","?") for e in registry], ", "))")
        catch e
            @warn "dynamic tools registry load error: $e"
        end
    end
end

function _get_arg(args, primary::String, aliases::Vector{String}=String[])
    if args isa AbstractString
        return String(args)
    elseif args isa AbstractDict
        if haskey(args, primary)
            return string(args[primary])
        end
        for alias in aliases
            if haskey(args, alias)
                return string(args[alias])
            end
        end
        if length(args) == 1
            val = first(values(args))
            return string(val)
        end
        if haskey(args, "args") && args["args"] isa AbstractDict
            return _get_arg(args["args"], primary, aliases)
        end
    end
    return ""
end

function _get_named_arg(args, primary::String, aliases::Vector{String}=String[])
    if args isa AbstractDict
        if haskey(args, primary)
            return string(args[primary])
        end
        for alias in aliases
            if haskey(args, alias)
                return string(args[alias])
            end
        end
        if haskey(args, "args") && args["args"] isa AbstractDict
            return _get_named_arg(args["args"], primary, aliases)
        end
    end
    return ""
end

# --- File I/O ---

# Resolve ordinary file-tool paths inside the Webula active project.
# This guards read/write/list; arbitrary shell execution is separate.
function _tool_workspace_file(path::AbstractString)
    home = strip(get(ENV, "SPARKBYTE_ACTIVE_PROJECT_ROOT", ""))
    isempty(home) && return String(path)
    base = realpath(home)
    given = replace(strip(String(path)), '\\' => '/')
    given == "." && return base
    isempty(given) && error("File path required")
    isabspath(given) && error("Use a relative path inside the selected project")
    occursin(r"^[A-Za-z]:", given) && error("Drive-qualified paths are not allowed")
    pieces = split(given, '/')
    any(p -> p in ("", ".."), pieces) && error("Parent traversal is not allowed")
    target = normpath(joinpath(base, pieces...))
    startswith(lowercase(target), lowercase(base * string(Base.Filesystem.path_separator))) ||
        error("Path outside selected project")
    cursor = base
    for part in pieces
        cursor = joinpath(cursor,part)
        islink(cursor) && error("Symlinks are not allowed for project tools")
    end
    return target
end


function tool_read_file(args)
    path = _get_arg(args, "path", ["file", "filepath", "filename", "name"])
    if isempty(path)
        return Dict("error" => "Missing required argument: 'path'")
    end
    try Dict("result" => read(_tool_workspace_file(path), String))
    catch e Dict("error" => string(e)) end
end

# Engine self-protection: the agent cannot overwrite the engine that runs it
# (its own source, config, or secrets like the API key). This is what stops
# SparkByte from accidentally nuking her own .env / engine source.
# Operator override: set SPARKBYTE_ALLOW_SOURCE_EDITS=true to allow edits.
function _agent_write_guard(path::String)::Tuple{Bool,String}
    allow = lowercase(strip(get(ENV, "SPARKBYTE_ALLOW_SOURCE_EDITS", "false")))
    allow in ("1", "true", "yes", "on", "enabled") && return (false, "")

    norm = replace(abspath(path), '\\' => '/')
    base = basename(norm)

    # Lock 1 — secrets / build config (the .env nuke protection you asked for)
    if base in (".env", ".env.example", ".env.local",
                "Project.toml", "Manifest.toml",
                "start.jl", "a2a_server.jl", "a2a_billing.jl")
        return (true,
            "$base is a protected engine config/secret file (it holds things like " *
            "the API key) and is write-locked. Edit it by hand, or set " *
            "SPARKBYTE_ALLOW_SOURCE_EDITS=true to override.")
    end

    # Lock 2 — engine source directories
    for d in ("/BYTE/src/", "/mcp_server/", "/JulianMetaMorph/")
        if occursin(d, norm)
            return (true,
                "ENGINE SOURCE LOCKED: $base — the agent cannot modify the engine " *
                "that runs it. Forge a new tool instead, or write to data/, logs/, " *
                "or tmp/. Override: set SPARKBYTE_ALLOW_SOURCE_EDITS=true.")
        end
    end
    return (false, "")
end

function tool_write_file(args)
    path = _get_arg(args, "path", ["file", "filepath", "filename", "name"])
    content = _get_arg(args, "content", ["text", "body", "data"])
    if isempty(path)
        return Dict("error" => "Missing required argument: 'path'")
    end
    blocked, reason = _agent_write_guard(path)
    blocked && return Dict("error" => "🔒 PROTECTED: $reason")
    try
        full = _tool_workspace_file(path)
        mkpath(dirname(full))
        write(full, content)
        Dict("result" => "Success")
    catch e
        Dict("error" => string(e))
    end
end

function tool_list_files(args)
    path = _get_arg(args, "path", ["file", "filepath", "filename", "name", "dir", "directory"])
    isempty(path) && (path = ".")
    try Dict("result" => join(readdir(_tool_workspace_file(path)), "\n"))
    catch e Dict("error" => string(e)) end
end

"""Resolve JulianMetaMorph install: `JULIAN_ROOT`, then `<project>/JulianMetaMorph/JulianMetaMorph`."""
function _resolve_julian_root(project_root::AbstractString)::String
    env = strip(get(ENV, "JULIAN_ROOT", ""))
    !isempty(env) && isdir(env) && return env
    if !isempty(project_root)
        embedded = joinpath(project_root, "JulianMetaMorph", "JulianMetaMorph")
        isdir(embedded) && return embedded
    end
    return ""
end

function _shell_command(command::String)
    if Sys.iswindows()
        # Write to a temp .ps1 file and run with -File to avoid PowerShell -Command
        # quote/escape mangling on complex strings, multi-line code, or < > $ chars.
        tmp = tempname() * ".ps1"
        write(tmp, "\$ErrorActionPreference = 'Stop'\n" * command)
        return `powershell -NoProfile -ExecutionPolicy Bypass -NonInteractive -File $tmp`
    end
    shell = Sys.which("bash")
    shell === nothing && (shell = Sys.which("sh"))
    shell === nothing && error("No shell found for run_command.")
    return `$shell -lc $command`
end

function _run_shell_capture(command::String)
    if Sys.iswindows()
        tmp = tempname() * ".ps1"
        try
            write(tmp, "\$ErrorActionPreference = 'Stop'\n" * command)
            out = IOBuffer()
            run(pipeline(`powershell -NoProfile -ExecutionPolicy Bypass -NonInteractive -File $tmp`,
                         stdout=out, stderr=out))
            return Dict("ok" => true, "output" => String(take!(out)))
        catch e
            output = @isdefined(out) ? String(take!(out)) : ""
            return Dict("ok" => false, "output" => output, "error" => string(e))
        finally
            rm(tmp; force=true)
        end
    end

    shell = Sys.which("bash")
    shell === nothing && (shell = Sys.which("sh"))
    shell === nothing && return Dict("ok" => false, "output" => "", "error" => "No shell found for run_command.")
    out = IOBuffer()
    try
        run(pipeline(`$shell -lc $command`, stdout=out, stderr=out))
        return Dict("ok" => true, "output" => String(take!(out)))
    catch e
        return Dict("ok" => false, "output" => String(take!(out)), "error" => string(e))
    end
end

# --- Shell ---
function tool_run_command(args)
    cmd_str = _get_arg(args, "command", ["cmd", "cmd_str", "shell", "exec"])
    if isempty(cmd_str)
        return Dict("error" => "Missing required argument: 'command'")
    end
    # SparkByte runs INSIDE this Julia process — killing julia kills her, not a
    # separate process. Block the obvious self-destruct shapes.
    for pat in (r"(?i)Stop-Process\s+.*julia",
                r"(?i)taskkill\s+.*\bjulia",
                r"(?i)\b(kill|pkill|killall)\b.*julia")
        if occursin(pat, cmd_str)
            return Dict("error" =>
                "BLOCKED: that command would kill the SparkByte process itself. " *
                "Use the restart endpoint or ask the operator instead.")
        end
    end
    result = _run_shell_capture(cmd_str)
    get(result, "ok", false) && return Dict("result" => get(result, "output", ""))
    return Dict(
        "error" => get(result, "error", "Command failed."),
        "output" => get(result, "output", "")
    )
end

function tool_get_os_info(args)
    Dict("os" => string(Sys.KERNEL), "cpu_architecture" => string(Sys.ARCH), "julia" => string(VERSION))
end

function tool_bluetooth_devices(args)
    action = lowercase(strip(string(get(args, "action", "list"))))
    action in ("list", "status") || return Dict("error" => "Unsupported action '$action'. Use 'list' or 'status'.")

    if Sys.iswindows()
        service = _read_shell_json("Get-Service bthserv -ErrorAction SilentlyContinue | Select-Object Status,StartType,Name | ConvertTo-Json -Compress")
        devices = _read_shell_json("Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Select-Object Status,Class,FriendlyName,InstanceId | ConvertTo-Json -Depth 4 -Compress")
        return Dict(
            "platform" => "windows",
            "action" => action,
            "service" => get(service, "data", get(service, "error", "Unavailable")),
            "devices" => get(devices, "data", get(devices, "error", "Unavailable")),
            "result" => "Bluetooth status collected from Windows service and device registry."
        )
    elseif Sys.isapple()
        profile = _read_command(`system_profiler SPBluetoothDataType -json`)
        if !get(profile, "ok", false)
            return Dict("error" => "Bluetooth inspection failed: $(get(profile, "error", "unknown error"))")
        end
        return Dict(
            "platform" => "macos",
            "action" => action,
            "profile" => try JSON.parse(get(profile, "output", "{}")) catch; get(profile, "output", "") end,
            "result" => "Bluetooth profile collected from system_profiler."
        )
    elseif Sys.islinux()
        show_res = _read_command(`bluetoothctl show`)
        list_cmd = action == "status" ? `bluetoothctl paired-devices` : `bluetoothctl devices`
        list_res = _read_command(list_cmd)
        return Dict(
            "platform" => "linux",
            "action" => action,
            "adapter" => get(show_res, "ok", false) ? get(show_res, "output", "") : get(show_res, "error", "Unavailable"),
            "devices" => get(list_res, "ok", false) ? get(list_res, "output", "") : get(list_res, "error", "Unavailable"),
            "result" => "Bluetooth information collected from bluetoothctl."
        )
    end

    Dict("error" => "Bluetooth inspection is not implemented for $(Sys.KERNEL).")
end

function _sms_twilio_config()
    sid   = strip(get(ENV, "TWILIO_ACCOUNT_SID", ""))
    token = strip(get(ENV, "TWILIO_AUTH_TOKEN", ""))
    from  = strip(get(ENV, "TWILIO_FROM_NUMBER", ""))
    missing = String[]
    isempty(sid) && push!(missing, "TWILIO_ACCOUNT_SID")
    isempty(token) && push!(missing, "TWILIO_AUTH_TOKEN")
    isempty(from) && push!(missing, "TWILIO_FROM_NUMBER")
    return (; sid, token, from, missing)
end

function _form_urlencode(pairs::Vector{Pair{String,String}})
    join(["$(HTTP.URIs.escapeuri(k))=$(HTTP.URIs.escapeuri(v))" for (k, v) in pairs], "&")
end

function tool_send_sms(args)
    provider = lowercase(strip(string(get(args, "provider", "twilio"))))
    provider == "twilio" || return Dict("error" => "Unsupported SMS provider '$provider'. Only 'twilio' is implemented right now.")

    to = strip(string(get(args, "to", "")))
    body = string(get(args, "message", get(args, "body", "")))
    from_override = strip(string(get(args, "from", "")))
    dry_run = _looks_true(get(args, "dry_run", false))

    isempty(to) && return Dict("error" => "Missing required field: to")
    isempty(strip(body)) && return Dict("error" => "Missing required field: message")

    cfg = _sms_twilio_config()
    from_number = isempty(from_override) ? cfg.from : from_override
    if !dry_run && !isempty(cfg.missing)
        return Dict(
            "error" => "Twilio SMS is not configured. Missing: $(join(cfg.missing, ", "))",
            "missing_env" => cfg.missing
        )
    end

    preview = Dict(
        "provider" => provider,
        "to" => to,
        "from" => from_number,
        "message_preview" => first(body, 160),
        "configured" => isempty(cfg.missing)
    )
    dry_run && return merge(Dict("result" => "SMS dry run only. No message was sent."), preview)

    url = "https://api.twilio.com/2010-04-01/Accounts/$(cfg.sid)/Messages.json"
    form = _form_urlencode([
        "To" => to,
        "From" => from_number,
        "Body" => body,
    ])
    auth = base64encode("$(cfg.sid):$(cfg.token)")
    headers = [
        "Authorization" => "Basic $auth",
        "Content-Type" => "application/x-www-form-urlencoded",
    ]

    try
        resp = HTTP.post(url, headers, form)
        body_text = String(resp.body)
        if 200 <= resp.status < 300
            data = JSON.parse(body_text)
            return merge(Dict(
                "result" => "SMS request accepted by Twilio.",
                "status" => get(data, "status", ""),
                "sid" => get(data, "sid", ""),
            ), preview)
        end
        return Dict(
            "error" => "Twilio rejected the SMS request with HTTP $(resp.status).",
            "details" => first(body_text, 500)
        )
    catch e
        Dict("error" => "SMS send failed: $(string(e))")
    end
end

# --- Code Execution ---
const _JULIA_SQLITE_PREAMBLE = raw"""
# ── SparkByte SQLite compatibility shim ──────────────────────────────────────
# Use query_db(db, sql) or query_db(db, sql, params) instead of SQLite.execute.
# Returns a DataFrames.DataFrame so column access works: df.colname or df[!,:col]
import SQLite, DataFrames, Dates, JSON, Statistics
function query_db(db::SQLite.DB, sql::String, params=())
    isempty(params) ?
        SQLite.DBInterface.execute(db, sql) |> DataFrames.DataFrame :
        SQLite.DBInterface.execute(db, sql, params) |> DataFrames.DataFrame
end
# ─────────────────────────────────────────────────────────────────────────────
"""

function _infer_execute_language(code::String, lang::String)
    normalized = lowercase(strip(lang))
    normalized in ("py", "python", "python3") && return "python"
    normalized in ("jl", "julia") && return "julia"
    !isempty(normalized) && return normalized

    python_markers = [
        r"(?m)^\s*(from\s+\w[\w.]*\s+import\s+|import\s+\w[\w.]*)",
        r"(?m)^\s*(def|class)\s+\w+\s*[\(:]",
        r"(?m)^\s*with\s+.+:\s*$",
        r"(?m)^\s*(elif|except|finally)\b.*:\s*$",
        r"\bprint\s*\(",
    ]
    any(marker -> occursin(marker, code), python_markers) && return "python"
    return "julia"
end

function _python_command(script::String)
    configured = strip(get(ENV, "SPARKBYTE_PYTHON", ""))
    if !isempty(configured)
        return `$configured $script`
    end
    if Sys.iswindows()
        py_launcher = Sys.which("py")
        py_launcher === nothing || return `$py_launcher -3 $script`
    end
    python = Sys.which("python")
    python === nothing && (python = Sys.which("python3"))
    python === nothing && error("No Python interpreter found. Set SPARKBYTE_PYTHON to a valid Python executable.")
    return `$python $script`
end

function tool_execute_code(args)
    code = args isa AbstractString ? String(args) : _get_named_arg(args, "code", ["script", "program", "source"])
    lang = _get_named_arg(args, "language", ["lang"])
    if isempty(code)
        return Dict("error" => "Missing required argument: 'code'")
    end
    lang = _infer_execute_language(code, lang)
    if !(lang in ("julia", "python"))
        return Dict("error" => "Unsupported language '$lang'. Use 'julia' or 'python'.")
    end
    tmp = ""
    try
        ext  = lang == "python" ? ".py" : ".jl"
        tmp  = tempname() * ext
        root = isempty(_project_root[]) ? pwd() : _project_root[]
        # For Julia, prepend the compatibility shim so AI-generated code can
        # safely use query_db(db, sql) and gets DataFrames back, not raw Int32.
        final_code = lang == "julia" ? _JULIA_SQLITE_PREAMBLE * "\n" * code : code
        write(tmp, final_code)
        cmd = lang == "python" ? _python_command(tmp) : `$(_julia_command(root)) $tmp`
        buffer = IOBuffer()
        run(pipeline(cmd, stdout=buffer, stderr=buffer))
        out = String(take!(buffer))
        Dict("stdout" => out, "language" => lang)
    catch e
        captured = @isdefined(buffer) ? String(take!(buffer)) : ""
        Dict("error" => string(e), "output" => captured, "language" => lang)
    finally
        isempty(tmp) || rm(tmp; force=true)
    end
end

# ── Core Engine Rule Enforcement ─────────────────────────────────────────────

# Packages actually installed in BYTE/Project.toml + Julia stdlib
const _ALLOWED_PACKAGES = Set([
    "SQLite","JSON","HTTP","DataFrames","Dates","PythonCall",
    "Printf","Base64","SHA","Statistics","LinearAlgebra","Random",
    "Base","Core","InteractiveUtils","Logging",
])

# Capabilities SparkByte genuinely does NOT have
const _PHANTOM_CAPABILITIES = [
    (r"microphone|audio_input|record_audio|listen_mic"i,        "microphone / audio input"),
    (r"\bcamera\b|\bwebcam\b|take_photo|capture_image"i,        "camera / webcam"),
    (r"\bgpio\b|raspberry_pi|arduino|serial_port"i,             "GPIO / hardware serial"),
    (r"send_email|smtp|sendmail|SMTP"i,                         "email sending (no SMTP configured)"),
    (r"gpu_temp|nvml|cuda_device|CuArray|CUDA\."i,              "GPU / CUDA (not available)"),
    (r"NFC|rfid|fingerprint_reader"i,                           "NFC / biometric hardware"),
]

function _looks_true(value; default::Bool=false)
    value === nothing && return default
    value isa Bool && return value
    normalized = lowercase(strip(string(value)))
    return !(normalized in ("", "0", "false", "no", "off"))
end

function _read_command(cmd::Cmd)
    try
        Dict("ok" => true, "output" => strip(read(cmd, String)))
    catch e
        Dict("ok" => false, "error" => string(e))
    end
end

function _read_shell_json(command::String)
    result = _run_shell_capture(command)
    get(result, "ok", false) || return result
    output = strip(get(result, "output", ""))
    isempty(output) && return Dict("ok" => true, "data" => Any[])
    try
        return Dict("ok" => true, "data" => JSON.parse(output))
    catch
        return Dict("ok" => true, "data" => output)
    end
end

"""
    _validate_forge_code(name, code) -> Vector{String}

Rule 1 enforcement: scan forged tool code for capabilities SparkByte doesn't have.
Returns a list of violation strings (empty = clean).
"""
function _validate_forge_code(name::String, code::String)
    errors = String[]

    # 1a. Any `tool_X(` call must reference a tool that exists in TOOL_MAP
    for m in eachmatch(r"\btool_([a-z_0-9]+)\s*\(", code)
        tname = m.captures[1]
        tname == name && continue   # self-reference / recursion is fine
        if !haskey(TOOL_MAP, tname)
            push!(errors, "Calls `tool_$(tname)()` but that tool does not exist. " *
                          "Available tools: $(join(sort(collect(keys(TOOL_MAP))), ", ")).")
        end
    end

    # 1b. Phantom hardware / capability patterns
    for (pat, label) in _PHANTOM_CAPABILITIES
        occursin(pat, code) && push!(errors,
            "References '$label' — SparkByte does not have this capability.")
    end

    # 1c. `using X` or `using X, Y, Z` must all be allowed packages
    for m in eachmatch(r"\busing\s+([A-Za-z][A-Za-z0-9_.,: ]*)", code)
        for pkg in split(m.captures[1], r"[,\s:.]+")
            pkg = strip(pkg)
            isempty(pkg) && continue
            pkg == "using" && continue          # keyword bleed — skip
            !occursin(r"^[A-Za-z][A-Za-z0-9_]*$", pkg) && continue  # not a bare identifier
            pkg ∈ _ALLOWED_PACKAGES && continue
            startswith(pkg, "Base") && continue
            push!(errors, "Imports '$pkg' which is not installed in Julia. " *
                          "Available: $(join(sort(collect(_ALLOWED_PACKAGES)), ", ")).")
        end
    end

    errors
end

"""
    _validate_schema_shape(v; max_depth=64) -> Union{Nothing,String}

Walk a forged-tool `parameters` schema and reject anything that would make
`_normalize_schema` blow the stack: cyclic dict references or excessive depth.
Returns `nothing` if safe, or an error string describing the problem.
"""
function _validate_schema_shape(v; max_depth::Int=64)
    seen = Base.IdSet{Any}()
    function _walk(node, depth)
        depth > max_depth && return "schema depth exceeds $max_depth levels"
        if node isa AbstractDict
            node in seen && return "schema contains a cyclic Dict reference"
            push!(seen, node)
            for (_, val) in node
                err = _walk(val, depth + 1)
                err === nothing || return err
            end
        elseif node isa AbstractVector
            node in seen && return "schema contains a cyclic Vector reference"
            push!(seen, node)
            for val in node
                err = _walk(val, depth + 1)
                err === nothing || return err
            end
        end
        return  # safe — schema is well-formed
    end
    return _walk(v, 0)
end

# --- Dynamic Tool Forge ---

# Forge gate — ON by default because this is SparkByte's core capability.
# Operators running in shared/prod contexts can opt out with SPARKBYTE_DISABLE_FORGE=true.
function _forge_enabled()::Bool
    v = lowercase(strip(get(ENV, "SPARKBYTE_DISABLE_FORGE", "")))
    return !(v in ("1", "true", "yes", "on"))
end

"""
Forge a new Julia tool into the live runtime.

The `code` arg MUST define a function named `tool_<name>(args)` where args is a Dict.
Example:
  name: "greet_user"
  code: |
    function tool_greet_user(args)
        name = get(args, "name", "stranger")
        Dict("result" => "Hey \$name, SparkByte says hi!")
    end
  description: "Greet a user by name"
  parameters: {"type":"OBJECT","properties":{"name":{"type":"STRING","description":"User name"}},"required":["name"]}
"""
function tool_forge_new_tool(args)
    try
        name        = string(args["name"])
        code        = string(args["code"])
        description = string(get(args, "description", "Dynamically forged tool: $name"))
        parameters  = get(args, "parameters", Dict{String,Any}(
            "type"=>"OBJECT","properties"=>Dict{String,Any}(),"required"=>String[]))
        # Gemini requires type=OBJECT whenever properties/required are present
        if (haskey(parameters, "properties") || haskey(parameters, "required")) &&
           uppercase(string(get(parameters, "type", ""))) != "OBJECT"
            parameters["type"] = "OBJECT"
        end
        root        = _project_root[]

        if !_forge_enabled()
            return Dict("error" => "FORGE DISABLED — SPARKBYTE_DISABLE_FORGE is set on this " *
                "server. Forging is off in this environment.")
        end

        # Deny-list — only real exfiltration and model-lock tampering.
        # Shell/eval/include/rm patterns removed: they false-positive constantly
        # on legitimate forged tools (tempfile cleanup, macro-expanded includes,
        # nested helpers that call eval as part of their actual job).
        forge_denylist = (
            ("ENV[\"OPENAI_API_KEY"     , "key exfiltration"),
            ("ENV[\"GEMINI_API_KEY"     , "key exfiltration"),
            ("ENV[\"XAI_API_KEY"        , "key exfiltration"),
            ("ENV[\"CEREBRAS_API_KEY"   , "key exfiltration"),
            ("ENV[\"OPENROUTER_API_KEY" , "key exfiltration"),
            ("ENV[\"STRIPE_"            , "stripe key exfiltration"),
            ("ENV[\"A2A_ADMIN"          , "admin key exfiltration"),
            # Model-lock — only the dropdown can change the active model.
            ("set_current_model!"     , "model self-selection (dropdown is authoritative)"),
            ("set_brain_backend_id!"  , "backend self-selection (dropdown is authoritative)"),
            ("set_tool_backend_id!"   , "backend self-selection (dropdown is authoritative)"),
            ("_current_model = "      , "direct model var assignment"),
        )
        blocked = [label for (pat, label) in forge_denylist if occursin(pat, code)]
        if !isempty(blocked)
            return Dict("error" => "FORGE REJECTED — forbidden pattern: $(join(blocked, ", ")). " *
                "Forge is allowed for new tool functions only, not for secret exfiltration or model-lock tampering.")
        end

        # Malformed/cyclic parameter schemas would blow the stack inside
        # _normalize_schema on every turn — advisory: warn and fall back to an
        # empty schema instead of rejecting the forge.
        schema_err = _validate_schema_shape(parameters)
        if schema_err !== nothing
            @warn "Forge schema advisory — replacing invalid parameters schema" tool=name issue=schema_err
            parameters = Dict{String,Any}(
                "type"=>"OBJECT","properties"=>Dict{String,Any}(),"required"=>String[])
        end

        # ── Rule 1 is now NO DECEPTION — attempt is allowed, live test proves it ──
        # Phantom hardware check still applies (no faking microphone, camera, etc.)
        hw_violations = filter(v -> any(occursin(pat, code) for (pat, _) in _PHANTOM_CAPABILITIES),
                               [label for (pat, label) in _PHANTOM_CAPABILITIES if occursin(pat, code)])
        if !isempty(hw_violations)
            return Dict("error" => "FORGE REJECTED — hardware you cannot access: $(join(hw_violations, ", ")). " *
                "Do not fake hardware capabilities. Return a real error if the device isn't available.")
        end

        # 0a. Pre-eval parse check — syntax errors only. Lower check is advisory
        # (warns but never rejects) because macro-heavy and world-age-dependent
        # code legitimately fails Meta.lower before the eval establishes context.
        parsed = try
            Meta.parseall(code)
        catch e
            return Dict("error" => "FORGE REJECTED — parse failure: $(e)", "stage" => "parse")
        end
        for expr in parsed.args
            expr isa LineNumberNode && continue
            (expr isa Expr && expr.head in (:using, :import)) && continue
            lowered = try Meta.lower(@__MODULE__, expr) catch; nothing end
            if lowered isa Expr && lowered.head === :error
                @warn "Forge pre-lower advisory" tool=name issue=lowered.args[1]
                # not a hard reject — eval may succeed anyway
            end
        end

        # 1. Eval code into BYTE module — live immediately
        # Iterate per-expression (same as _load_dynamic_tools!) so that top-level
        # `using` statements (packages already in scope) don't trigger world-age
        # recursion in Julia 1.12 when eval'd as a single :toplevel block.
        for expr in parsed.args
            expr isa LineNumberNode && continue
            (expr isa Expr && expr.head in (:using, :import)) && continue
            Core.eval(@__MODULE__, expr)
        end

        # 2. Verify expected function exists (world-age safe)
        fn_sym = Symbol("tool_$name")
        local _sym = fn_sym
        fn_ok = Base.invokelatest(() -> isdefined(@__MODULE__, _sym))
        if !fn_ok
            return Dict("error" => "Eval succeeded but `tool_$name(args)` not found. Code must define exactly that function name.")
        end

        # 2.5. JET deep-check (soft dep). If JET.jl is loaded, run abstract
        # interpretation against the new function for a Dict{String,Any} arg.
        # Reports type errors, undef vars, dispatch failures the parser misses.
        # ADVISORY, not a hard gate: JET false-positives heavily on dynamic
        # Dict{String,Any} code, so a hard reject would block legitimate forges.
        # The skip is LOGGED (not silent) so the operator always knows whether
        # static analysis actually ran.
        jet_mod = isdefined(@__MODULE__, :JET) ? getfield(@__MODULE__, :JET) :
                  (Base.find_package("JET") !== nothing ? Base.require(Base.PkgId(Base.UUID("c3a54625-cd67-489e-a8e7-0a5a0ff4e31b"), "JET")) : nothing)
        if jet_mod === nothing
            @info "Forge static check skipped — JET.jl not installed" tool=name
        else
            try
                fn = getfield(@__MODULE__, fn_sym)
                rep = Base.invokelatest(jet_mod.report_call, fn, (Dict{String,Any},))
                jet_report = string(rep)
                if occursin(r"\d+ possible error"i, jet_report)
                    @warn "Forged tool `$name` has JET-detected issues" report=first(jet_report, 800)
                end
            catch e
                @warn "JET check errored — forge continues" tool=name exception=e
            end
        end

        # 3. Register in TOOL_MAP with invokelatest wrapper for Julia 1.12 world age compliance
        TOOL_MAP[name] = (args) -> Base.invokelatest(getfield(@__MODULE__, _sym), args)

        # 4. Update DYNAMIC_SCHEMA (upsert)
        filter!(e -> e["name"] != name, DYNAMIC_SCHEMA)
        push!(DYNAMIC_SCHEMA, Dict{String,Any}(
            "name"        => name,
            "description" => description,
            "parameters"  => parameters,
        ))

        if !isempty(root)
            tools_path    = _runtime_state_path("dynamic_tools.jl"; root=root)
            registry_path = _runtime_state_path("dynamic_tools_registry.json"; root=root)
            test_dir      = joinpath(root, "test")
            test_file     = joinpath(test_dir, "test_dynamic_tools.jl")

            # 5. Persist code — replace existing block if re-forging
            existing_code = isfile(tools_path) ? read(tools_path, String) : ""
            marker        = "# -- Tool: $name --"
            if occursin(marker, existing_code)
                # Strip old block
                lines  = split(existing_code, "\n")
                in_blk = false
                kept   = String[]
                for ln in lines
                    if startswith(ln, marker)
                        in_blk = true; continue
                    elseif in_blk && startswith(ln, "# -- Tool:")
                        in_blk = false
                    end
                    in_blk || push!(kept, ln)
                end
                existing_code = join(kept, "\n")
            end
            open(tools_path, "w") do f
                write(f, rstrip(existing_code))
                write(f, "\n\n$marker\n$code\n")
            end

            # 6. Update registry JSON
            registry = isfile(registry_path) ?
                try JSON.parsefile(registry_path) catch; Any[] end : Any[]
            filter!(e -> get(e, "name", "") != name, registry)
            push!(registry, Dict{String,Any}(
                "name"=>name, "description"=>description, "parameters"=>parameters))
            write(registry_path, JSON.json(registry, 2))

            # 7. Run the tool live in the runtime with args from schema
            # If it fails, return error so the agentic loop re-forges with a fix
            live_args = Dict{String,Any}()
            if parameters isa Dict
                for req in get(parameters, "required", [])
                    prop = get(get(parameters, "properties", Dict()), req, Dict())
                    typ  = get(prop, "type", "STRING")
                    live_args[req] = typ == "INTEGER" ? 0 : typ == "BOOLEAN" ? false : "test"
                end
            end
            live_result = try
                Base.invokelatest(getfield(@__MODULE__, _sym), live_args)
            catch e
                Dict("error" => string(e))
            end
            live_ok = live_result isa Dict && !haskey(live_result, "error")

            # Log real result to test file
            mkpath(test_dir)
            entry = """
# -- tool_$name | $(Dates.format(now(), "yyyy-mm-dd HH:MM:SS")) | $(live_ok ? "PASS" : "FAIL") --
# args:   $(JSON.json(live_args))
# result: $(JSON.json(live_result))
"""
            open(test_file, "a") do f; write(f, entry); end

            # If it failed, signal back so the loop re-forges
            if !live_ok
                live_err = get(live_result, "error", "unknown")
                return Dict(
                    "error"        => "Tool '$name' forged but failed live test: $live_err",
                    "forge_broken" => true,
                    "tool_name"    => name,
                    "hint"         => "Fix the code and re-forge. Test args used: $(JSON.json(live_args))",
                    "live_result"  => live_result,
                )
            end
        end

        db = _state[:db]
        if db !== nothing
            try
                SQLite.execute(db, """
                    INSERT OR REPLACE INTO tools (name, source, description, parameters, is_dynamic, forged_at, call_count)
                    VALUES (?, ?, ?, ?, 1, ?, COALESCE((SELECT call_count FROM tools WHERE name = ?), 0))
                """, (name, code, description, JSON.json(parameters), string(now()), name))
            catch db_err
                @warn "Failed to write forged tool to tools SQL table" exception=(db_err, catch_backtrace())
            end
        end

        # ── Fire forge hooks (live dashboard broadcast, etc.) ────────────────
        for hook in _FORGE_HOOKS
            try; hook(name, code, description); catch e; @warn "Forge hook failed" exception=(e, catch_backtrace()); end
        end

        Dict("result" => "Tool '$name' is LIVE. Eval succeeded — registered in dispatch, logged to test file.")
    catch e
        bt = sprint(showerror, e, catch_backtrace())
        Dict("error" => "Forge failed: $(first(string(e), 400))", "stacktrace" => first(bt, 800))
    end
end

# --- GitHub Pillage ---
# Converts a github.com file URL to raw.githubusercontent.com
function _github_to_raw(url::String)
    m = match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    m === nothing && return nothing
    "https://raw.githubusercontent.com/$(m[1])/$(m[2])/$(m[3])"
end

# Returns (owner, repo, ref, subpath) for a github.com tree URL, or nothing
function _parse_github_tree(url::String)
    m = match(r"https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(/.*)?)?$", url)
    m === nothing && return nothing
    (m[1], m[2], something(m[3], "HEAD"), something(m[4], ""))
end

function tool_github_pillage(args)
    url      = string(get(args, "url", ""))
    write_to = get(args, "write_to", nothing)
    isempty(url) && return Dict("error" => "url is required")

    headers = ["User-Agent" => "SparkByte/1.0"]

    # ── Direct raw URL ───────────────────────────────────────────────────────
    if contains(url, "raw.githubusercontent.com")
        try
            resp = HTTP.get(url, headers)
            content = String(resp.body)
            if write_to !== nothing && !isempty(write_to)
                mkpath(dirname(write_to))
                write(write_to, content)
                return Dict("written" => write_to, "bytes" => length(content))
            end
            return Dict("content" => content, "bytes" => length(content))
        catch e; return Dict("error" => string(e)) end
    end

    # ── github.com /blob/ file URL → raw content ─────────────────────────────
    raw_url = _github_to_raw(url)
    if raw_url !== nothing
        try
            resp = HTTP.get(raw_url, headers)
            content = String(resp.body)
            if write_to !== nothing && !isempty(write_to)
                mkpath(dirname(write_to))
                write(write_to, content)
                return Dict("written" => write_to, "bytes" => length(content), "source" => raw_url)
            end
            return Dict("content" => content, "bytes" => length(content), "source" => raw_url)
        catch e; return Dict("error" => string(e)) end
    end

    # ── github.com repo or tree URL → file listing via API ───────────────────
    parsed = _parse_github_tree(url)
    if parsed !== nothing
        owner, repo, ref, subpath = parsed
        api_url = "https://api.github.com/repos/$owner/$repo/git/trees/$ref?recursive=1"
        try
            resp = HTTP.get(api_url, [headers..., "Accept" => "application/vnd.github+json"])
            data = JSON.parse(String(resp.body))
            tree = get(data, "tree", [])
            prefix = lstrip(subpath, '/')
            files = [t["path"] for t in tree
                     if t["type"] == "blob" && startswith(t["path"], prefix)]
            return Dict("files" => files, "count" => length(files),
                        "repo" => "$owner/$repo", "ref" => ref,
                        "tip" => "Use github_pillage with the full blob URL to fetch any file, or pass write_to to save it.")
        catch e; return Dict("error" => string(e)) end
    end

    # ── Fallback: treat as raw HTTP fetch (gist, etc.) ───────────────────────
    try
        resp = HTTP.get(url, headers)
        content = String(resp.body)
        if write_to !== nothing && !isempty(write_to)
            mkpath(dirname(write_to))
            write(write_to, content)
            return Dict("written" => write_to, "bytes" => length(content))
        end
        return Dict("content" => first(content, 8000), "bytes" => length(content))
    catch e; return Dict("error" => string(e)) end
end

# --- Web Eyes ---
function tool_browse_url(args)
    ctx = _state[:browser_context]
    ctx === nothing && return Dict("error" => "Browser not initialized.")
    page = nothing
    try
        page = ctx.new_page()
        page.goto(string(args["url"]), wait_until="domcontentloaded", timeout=30000)
        text = pyconvert(String, page.evaluate("() => document.body.innerText"))
        @async try; _db_write_web_cache(string(args["url"]), text); catch e; @warn "Web cache write failed" exception=(e, catch_backtrace()); end
        return Dict("content" => first(text, 5000))
    catch e
        return Dict("error" => string(e))
    finally
        if page !== nothing
            try
                page.close()
            catch err
                @warn "Failed to close browser tool page" exception=(err, catch_backtrace())
            end
        end
    end
end

# --- Memory ---
function tool_remember(args)
    db = _state[:db]
    db === nothing && return Dict("error" => "DB not initialized.")
    SQLite.execute(db,
        "INSERT INTO memory (timestamp, tag, key, content) VALUES (?, ?, ?, ?)",
        (string(now()), get(args, "tag", "gen"), get(args, "key", ""), string(args["content"])))
    Dict("result" => "Stored.")
end

function tool_recall(args)
    db = _state[:db]
    db === nothing && return Dict("error" => "DB not initialized.")
    q    = string(get(args, "query", ""))
    mode = string(get(args, "mode",  "memory"))  # memory | behavior_states | agents | knowledge | tools | telemetry | thoughts

    pq = "%$q%"  # parameterized LIKE value

    if mode == "behavior_states"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT state_id, name, intensity, control, expressiveness, pacing, tone_bias, memory_strictness FROM behavior_states ORDER BY intensity, control") |> DataFrame :
            DBInterface.execute(db,
                "SELECT state_id, name, intensity, control, expressiveness, pacing, tone_bias, memory_strictness FROM behavior_states WHERE name LIKE ? OR tone_bias LIKE ? OR pacing LIKE ? ORDER BY intensity, control",
                (pq, pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No behavior states found.")
        lines = ["$(r.state_id) | $(r.name) | intensity=$(r.intensity) control=$(r.control) expr=$(r.expressiveness) pacing=$(r.pacing) tone=$(r.tone_bias) mem=$(r.memory_strictness)"
                 for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    elseif mode == "agents"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT name, description, tone, boot_prompt, active FROM agents ORDER BY active DESC, name") |> DataFrame :
            DBInterface.execute(db,
                "SELECT name, description, tone, boot_prompt, active FROM agents WHERE name LIKE ? OR description LIKE ? OR tone LIKE ? ORDER BY active DESC, name",
                (pq, pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No agents found.")
        lines = ["$(r.active==1 ? "★" : " ") $(r.name) | $(r.tone) | $(first(string(r.description),120))"
                 for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    elseif mode == "knowledge"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT domain, topic, content FROM knowledge ORDER BY domain, topic LIMIT 200") |> DataFrame :
            DBInterface.execute(db,
                "SELECT domain, topic, content FROM knowledge WHERE domain LIKE ? OR topic LIKE ? OR content LIKE ? ORDER BY domain, topic LIMIT 200",
                (pq, pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No knowledge entries found for: $q")
        lines = ["[$(r.domain)/$(r.topic)]: $(first(string(r.content), 200))" for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    elseif mode == "tools"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT name, description, is_dynamic, call_count, last_used FROM tools ORDER BY is_dynamic DESC, call_count DESC") |> DataFrame :
            DBInterface.execute(db,
                "SELECT name, description, is_dynamic, call_count, last_used FROM tools WHERE name LIKE ? OR description LIKE ? ORDER BY is_dynamic DESC, call_count DESC",
                (pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No tools indexed yet.")
        lines = ["$(r.is_dynamic==1 ? "⚡forged" : "builtin") | $(r.name) | calls=$(r.call_count) | $(first(string(r.description),100))"
                 for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    elseif mode == "telemetry"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT timestamp, event, agent, model, data_json FROM telemetry ORDER BY id DESC LIMIT 50") |> DataFrame :
            DBInterface.execute(db,
                "SELECT timestamp, event, agent, model, data_json FROM telemetry WHERE event LIKE ? OR agent LIKE ? OR model LIKE ? ORDER BY id DESC LIMIT 50",
                (pq, pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No telemetry.")
        lines = ["$(r.timestamp) [$(r.agent)/$(r.model)] $(r.event)" for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    elseif mode == "thoughts"
        rows = isempty(q) ?
            DBInterface.execute(db,
                "SELECT timestamp, agent, type, model, thought FROM thoughts ORDER BY id DESC LIMIT 20") |> DataFrame :
            DBInterface.execute(db,
                "SELECT timestamp, agent, type, model, thought FROM thoughts WHERE thought LIKE ? OR type LIKE ? OR agent LIKE ? ORDER BY id DESC LIMIT 20",
                (pq, pq, pq)) |> DataFrame
        isempty(rows) && return Dict("result" => "No thoughts found.")
        lines = ["$(r.timestamp) [$(r.agent)/$(r.type)]: $(first(string(r.thought),200))" for r in eachrow(rows)]
        return Dict("result" => join(lines, "\n"), "count" => nrow(rows))

    else  # default: memory full-text search
        rows = DBInterface.execute(db,
            "SELECT tag, key, content FROM memory WHERE content LIKE ? OR tag LIKE ? OR key LIKE ?",
            ("%$q%", "%$q%", "%$q%")) |> DataFrame
        return Dict("result" => isempty(rows) ? "None." :
            join(["[$(r.tag)/$(r.key)]: $(first(string(r.content),300))" for r in eachrow(rows)], "\n"),
            "count" => nrow(rows))
    end
end

# --- Metamorph — self-repair and code-grabber ---
"""Run Julian's curiosity-hunt CLI: picks an interest seed, full GitHub hunt, diary + WS broadcast."""
function run_julian_curiosity_hunt!(root::AbstractString; broadcast_result::Bool=true)
    jr = _resolve_julian_root(root)
    isempty(jr) && return Dict("error" => "JulianMetaMorph not found. Set JULIAN_ROOT or embed Julian at <project>/JulianMetaMorph/JulianMetaMorph.")
    try
        py = get(ENV, "PYTHON", "python")
        out = cd(jr) do
            withenv("PYTHONPATH" => "src") do
                read(Cmd([py, "-m", "julian_metamorph.cli", "curiosity-hunt"]), String)
            end
        end
        data = JSON.parse(out)
        task = string(get(data, "picked_task", get(data, "task", "")))
        hunt_id = string(get(data, "hunt_id", ""))
        summary = string(get(data, "summary", ""))
        thought = "Julian curiosity — $(first(summary, 500))"
        _db_write_thought("julian_curiosity", thought, "wired", "trot", "Julian"; type="diary")
        if broadcast_result
            try
                _broadcast(Dict(
                    "type" => "julian_curiosity",
                    "task" => task,
                    "hunt_id" => hunt_id,
                    "preview" => first(summary, 600),
                ))
            catch
            end
        end
        return Dict("ok" => true, "julian_root" => jr, "data" => data)
    catch e
        return Dict("error" => string(e), "julian_root" => jr)
    end
end

"""
Self-repair and code-grabber tool.

Actions:
  inspect               — audit live TOOL_MAP, dynamic tools, missing statics
  reload_dynamic_tools  — re-run _load_dynamic_tools! from disk (restores all forged tools)
  restore_tool          — re-forge a named tool from src/Tools/<name>.jl or dynamic_tools.jl
  reload_source         — re-eval a JLEngine source file into the live runtime
  heal_tool_map         — re-register any missing static built-in tools
  grab_from_julian      — call JulianMetaMorph CLI hunt-task to find real code patterns
  curiosity_hunt        — Julian picks a rotating/random interest seed and runs hunt-task (autonomous vibe)
"""


function tool_metamorph(args)
    action = string(get(args, "action", "inspect"))
    root   = _project_root[]

    # ── inspect ──────────────────────────────────────────────────────────────
    if action == "inspect"
        static_tools   = ["read_file","write_file","list_files","run_command",
                          "get_os_info","bluetooth_devices","send_sms",
                          "execute_code","forge_new_tool","browse_url",
                          "github_pillage","remember","recall","metamorph"]
        live_tools     = sort(collect(keys(TOOL_MAP)))
        dynamic_names  = [get(d,"name","") for d in DYNAMIC_SCHEMA]
        missing_static = filter(t -> !haskey(TOOL_MAP, t), static_tools)
        return Dict(
            "live_tools"     => live_tools,
            "dynamic_tools"  => dynamic_names,
            "missing_static" => missing_static,
            "tool_count"     => length(live_tools),
            "dynamic_count"  => length(dynamic_names),
            "status"         => isempty(missing_static) ? "healthy" :
                                "degraded — missing: $(join(missing_static, ", "))",
        )

    # ── reload_dynamic_tools ─────────────────────────────────────────────────
    elseif action == "reload_dynamic_tools"
        isempty(root) && return Dict("error" => "project root not set — cannot locate dynamic_tools.jl")
        before = length(TOOL_MAP)
        try
            _load_dynamic_tools!(root)
        catch e
            return Dict("error" => "reload failed: $(string(e))")
        end
        after = length(TOOL_MAP)
        return Dict(
            "ok"            => true,
            "tools_before"  => before,
            "tools_after"   => after,
            "added"         => after - before,
            "dynamic_tools" => [get(d,"name","") for d in DYNAMIC_SCHEMA],
        )

    # ── restore_tool ─────────────────────────────────────────────────────────
    elseif action == "restore_tool"
        name = string(get(args, "name", ""))
        isempty(name) && return Dict("error" => "'name' required for restore_tool action")

        # 1. Try canonical disk source: src/Tools/<name>.jl
        if !isempty(root)
            src_path = joinpath(root, "src", "Tools", "$(name).jl")
            if isfile(src_path)
                code   = read(src_path, String)
                result = tool_forge_new_tool(Dict(
                    "name"        => name,
                    "code"        => code,
                    "description" => "Restored from src/Tools/$(name).jl",
                ))
                result["restored_from"] = src_path
                return result
            end
        end

        # 2. Fall back to extracting the block from dynamic_tools.jl
        if !isempty(root)
            dyn_path = _runtime_state_path("dynamic_tools.jl"; root=root)
            if isfile(dyn_path)
                content = read(dyn_path, String)
                marker  = "# -- Tool: $name --"
                if occursin(marker, content)
                    lines  = split(content, "\n")
                    in_blk = false
                    block  = String[]
                    for ln in lines
                        if startswith(ln, marker)
                            in_blk = true; continue
                        elseif in_blk && startswith(ln, "# -- Tool:") && !startswith(ln, marker)
                            break
                        end
                        in_blk && push!(block, ln)
                    end
                    if !isempty(block)
                        result = tool_forge_new_tool(Dict("name" => name, "code" => join(block, "\n")))
                        result["restored_from"] = dyn_path
                        return result
                    end
                end
            end
        end

        return Dict("error" => "No source found for tool '$name'. " *
            "Checked src/Tools/$(name).jl and dynamic_tools.jl. " *
            "Use forge_new_tool to write it fresh.")

    # ── reload_source ────────────────────────────────────────────────────────
    elseif action == "reload_source"
        rel_path = string(get(args, "path", ""))
        isempty(rel_path) && return Dict("error" => "'path' required for reload_source action")
        full_path = isempty(root) ? rel_path : joinpath(root, rel_path)
        isfile(full_path) || return Dict("error" => "File not found: $full_path")
        try
            code = read(full_path, String)
            let parsed = Meta.parseall(code)
                for expr in parsed.args
                    expr isa LineNumberNode && continue
                    (expr isa Expr && expr.head in (:using, :import)) && continue
                    Core.eval(@__MODULE__, expr)
                end
            end
            return Dict("ok" => true, "reloaded" => full_path)
        catch e
            return Dict("error" => "reload_source failed: $(string(e))", "path" => full_path)
        end

    # ── heal_tool_map ────────────────────────────────────────────────────────
    elseif action == "heal_tool_map"
        static_map = Dict{String,Function}(
            "read_file"         => tool_read_file,
            "write_file"        => tool_write_file,
            "list_files"        => tool_list_files,
            "run_command"       => tool_run_command,
            "get_os_info"       => tool_get_os_info,
            "bluetooth_devices" => tool_bluetooth_devices,
            "send_sms"          => tool_send_sms,
            "execute_code"      => tool_execute_code,
            "forge_new_tool"    => tool_forge_new_tool,
            "browse_url"        => tool_browse_url,
            "github_pillage"    => tool_github_pillage,
            "remember"          => tool_remember,
            "recall"            => tool_recall,
            "metamorph"         => tool_metamorph,
        )
        healed = String[]
        for (k, fn) in static_map
            if !haskey(TOOL_MAP, k)
                TOOL_MAP[k] = fn
                push!(healed, k)
            end
        end
        return Dict(
            "ok"           => true,
            "healed"       => healed,
            "healed_count" => length(healed),
            "tool_map_now" => sort(collect(keys(TOOL_MAP))),
        )

    # ── grab_from_julian ─────────────────────────────────────────────────────
    elseif action == "grab_from_julian"
        task = string(get(args, "task", ""))
        isempty(task) && return Dict("error" => "'task' required for grab_from_julian action")
        julian_root = _resolve_julian_root(root)
        isempty(julian_root) && return Dict(
            "error" => "JulianMetaMorph not found. Clone or link it at <project>/JulianMetaMorph/JulianMetaMorph or set JULIAN_ROOT.")
        try
            py = get(ENV, "PYTHON", "python")
            out = cd(julian_root) do
                withenv("PYTHONPATH" => "src") do
                    read(Cmd([py, "-m", "julian_metamorph.cli", "hunt-task", task]), String)
                end
            end
            return Dict("ok" => true, "julian_root" => julian_root, "output" => first(out, 3000))
        catch e
            return Dict("error" => "Julian hunt failed: $(string(e))", "julian_root" => julian_root)
        end

    # ── curiosity_hunt (autonomous interest) ───────────────────────────────
    elseif action == "curiosity_hunt"
        return run_julian_curiosity_hunt!(root)

    # ── health_check ─────────────────────────────────────────────────────────
    elseif action == "health_check"
        issues  = Dict{String, Vector{String}}()
        summary = String[]

        _add_issue(file, code, msg) = begin
            k = file
            haskey(issues, k) || (issues[k] = String[])
            push!(issues[k], "  [WARN]  [$code]  $msg")
            push!(summary, "$file\n  [WARN]  [$code]  $msg")
        end

        byte_path   = isempty(root) ? joinpath("BYTE","src","BYTE.jl")   : joinpath(root,"BYTE","src","BYTE.jl")
        tools_path  = isempty(root) ? joinpath("BYTE","src","Tools.jl")  : joinpath(root,"BYTE","src","Tools.jl")
        schema_path = isempty(root) ? joinpath("BYTE","src","Schema.jl") : joinpath(root,"BYTE","src","Schema.jl")
        ui_path     = isempty(root) ? joinpath("BYTE","src","ui.html")   : joinpath(root,"BYTE","src","ui.html")

        # ── 1. WS type coverage: server sends → UI handles ───────────────────
        if isfile(byte_path) && isfile(ui_path)
            byte_src = read(byte_path, String)
            ui_src   = read(ui_path,   String)

            source_dir = dirname(byte_path)
            source_files = filter(p -> endswith(p, ".jl"), readdir(source_dir; join=true))
            server_types = _ws_emitted_types([read(p, String) for p in source_files])

            # Types the UI handles: d.type==='X' or d.type=='X'
            ui_handled = Set{String}()
            for m in eachmatch(r"d\.type\s*===?\s*'([a-z_][a-z0-9_]*)'", ui_src)
                push!(ui_handled, m.captures[1])
            end

            # Internal routing types the server reads from client (not sent outward) — skip these
            client_only = Set(["user_msg","builder_cmd","model_change","stop_generation",
                                "get_history","load_session","restart_server","agent_change",
                                "forge_resubmit","confirm_response","card_crunch"])

            for t in sort(collect(setdiff(server_types, ui_handled, client_only)))
                _add_issue("BYTE\\src\\BYTE.jl", "ws_no_handler",
                    "Server sends WS type `$t` but ui.html has no handler for it")
            end

            # A missing static sender does not prove a dead handler:
            # dynamic payloads and external bridges can supply additional types.

        end

        # ── 2. Tool schema coverage: TOOL_MAP → TOOLS_SCHEMA ─────────────────
        schema_names = Set{String}()
        for group in TOOLS_SCHEMA
            for decl in get(group, "function_declarations", Any[])
                n = get(decl, "name", "")
                isempty(n) || push!(schema_names, n)
            end
        end
        dynamic_names = Set(get(d,"name","") for d in DYNAMIC_SCHEMA)

        for t in sort(collect(keys(TOOL_MAP)))
            isempty(t) && continue
            t in schema_names  && continue   # documented — OK
            t in dynamic_names && continue   # forged tools self-register — OK
            _add_issue("BYTE\\src\\Tools.jl", "tool_no_schema",
                "Tool `$t` in TOOL_MAP but missing from Schema.jl — model can't see it")
        end

        # Reverse: schema declares tool that isn't in TOOL_MAP (phantom schema entry)
        for t in sort(collect(schema_names))
            haskey(TOOL_MAP, t) && continue
            _add_issue("BYTE\\src\\Schema.jl", "schema_no_tool",
                "Schema.jl declares tool `$t` but it's not in TOOL_MAP — model will call a ghost")
        end

        # ── 3. Dynamic tools: disk vs live ───────────────────────────────────
        if !isempty(root)
            reg_path = _runtime_state_path("dynamic_tools_registry.json"; root=root)
            if isfile(reg_path)
                reg = try JSON.parsefile(reg_path) catch; Any[] end
                for entry in reg
                    n = get(entry, "name", "")
                    isempty(n) && continue
                    haskey(TOOL_MAP, n) || _add_issue("dynamic_tools_registry.json",
                        "dynamic_not_loaded",
                        "Forged tool `$n` in registry but not in live TOOL_MAP — run metamorph reload_dynamic_tools")
                end
            end
        end

        if isempty(summary)
            return Dict("status"=>"healthy", "message"=>"✅ All checks passed — no issues found.",
                        "checks"=>["ws_coverage","tool_schema_coverage","dynamic_tools"])
        end
        report = join(summary, "\n\n")
        return Dict(
            "status"        => "warnings",
            "issue_count"   => length(summary),
            "report"        => report,
            "issues_by_file"=> Dict(k => join(v,"\n") for (k,v) in issues),
        )

    else
        return Dict("error" => "Unknown metamorph action: '$action'. " *
            "Valid: inspect | reload_dynamic_tools | restore_tool | reload_source | heal_tool_map | grab_from_julian | curiosity_hunt | health_check")
    end
end

# --- Dispatch ---
# --- Card Cruncher — SillyTavern/CharacterTavern card → JLEngine agent ---
"""
Convert a SillyTavern or CharacterTavern character card (.png or .json) into a
JLEngine _Full.json agent file, ready to load with /gear <CharName>.

Parameters:
  card_path    — path to the .png or .json card file (required)
  out_path     — output path override (default: data/agents/<Name>_Full.json)
  dry_run      — if true, print result without writing (default: false)
  engine_root  — engine root override (default: project root)
"""
# ── Playwright Full Interaction ───────────────────────────────────────────────
# Extends browse_url to support click, fill, type, submit, screenshot, wait.
# actions: array of {type, selector, value, timeout_ms}
# types: goto | click | fill | type | press | wait | wait_for | read | screenshot | evaluate | select
function tool_playwright_interact(args)
    ctx = _state[:browser_context]
    ctx === nothing && return Dict("error" => "Browser not initialized.")
    url     = string(get(args, "url", ""))
    actions = get(args, "actions", Any[])
    results = Any[]
    page = nothing
    try
        page = ctx.new_page()
        isempty(url) || page.goto(url, wait_until="domcontentloaded", timeout=30000)
        for action in actions
            atype    = string(get(action, "type", ""))
            selector = string(get(action, "selector", ""))
            value    = string(get(action, "value", ""))
            timeout  = Int(get(action, "timeout_ms", 5000))
            try
                if atype == "goto"
                    page.goto(value, wait_until="domcontentloaded", timeout=timeout)
                    push!(results, Dict("type" => "goto", "url" => value, "ok" => true))
                elseif atype == "click"
                    page.click(selector, timeout=timeout)
                    push!(results, Dict("type" => "click", "selector" => selector, "ok" => true))
                elseif atype == "fill"
                    page.fill(selector, value, timeout=timeout)
                    push!(results, Dict("type" => "fill", "selector" => selector, "ok" => true))
                elseif atype == "type"
                    page.type(selector, value, delay=50)
                    push!(results, Dict("type" => "type", "selector" => selector, "ok" => true))
                elseif atype == "press"
                    page.press(selector, value)
                    push!(results, Dict("type" => "press", "key" => value, "ok" => true))
                elseif atype == "wait"
                    page.wait_for_timeout(parse(Float64, isempty(value) ? "1000" : value))
                    push!(results, Dict("type" => "wait", "ok" => true))
                elseif atype == "wait_for"
                    page.wait_for_selector(selector, timeout=timeout)
                    push!(results, Dict("type" => "wait_for", "selector" => selector, "ok" => true))
                elseif atype == "select"
                    page.select_option(selector, value)
                    push!(results, Dict("type" => "select", "selector" => selector, "value" => value, "ok" => true))
                elseif atype == "read"
                    text = pyconvert(String, page.evaluate("() => document.body.innerText"))
                    push!(results, Dict("type" => "read", "content" => first(text, 4000), "ok" => true))
                elseif atype == "evaluate"
                    result_js = pyconvert(String, page.evaluate(value))
                    push!(results, Dict("type" => "evaluate", "result" => first(result_js, 2000), "ok" => true))
                elseif atype == "screenshot"
                    ss_path = string(get(action, "path", "/tmp/sparkbyte_screenshot.png"))
                    page.screenshot(path=ss_path)
                    push!(results, Dict("type" => "screenshot", "path" => ss_path, "ok" => true))
                else
                    push!(results, Dict("type" => atype, "ok" => false, "error" => "Unknown action type: $atype"))
                end
            catch e
                push!(results, Dict("type" => atype, "ok" => false, "error" => first(string(e), 300)))
            end
        end
        Dict("results" => results, "url" => url, "action_count" => length(results))
    catch e
        Dict("error" => string(e))
    finally
        if page !== nothing
            try
                page.close()
            catch err
                @warn "Failed to close browser interaction page" exception=(err, catch_backtrace())
            end
        end
    end
end

# ── Discord Webhook Poster ────────────────────────────────────────────────────
# Post messages or embeds to any Discord channel via webhook URL.
# Webhook URL from DISCORD_WEBHOOK_URL env var or passed directly.
function tool_discord_webhook(args)
    webhook_url = string(get(args, "webhook_url", get(ENV, "DISCORD_WEBHOOK_URL", "")))
    isempty(webhook_url) && return Dict(
        "error" => "No webhook_url provided. Pass webhook_url directly or set DISCORD_WEBHOOK_URL env var.",
        "how_to_get" => "In Discord: open any server → channel settings → Integrations → Webhooks → New Webhook → Copy URL"
    )
    message  = string(get(args, "message", ""))
    username = string(get(args, "username", "SparkByte"))
    avatar   = string(get(args, "avatar_url", ""))
    embeds   = get(args, "embeds", nothing)

    isempty(message) && embeds === nothing && return Dict("error" => "Provide 'message' text or 'embeds' array.")

    payload = Dict{String,Any}("username" => username)
    !isempty(message) && (payload["content"] = message)
    !isempty(avatar)  && (payload["avatar_url"] = avatar)
    embeds !== nothing && (payload["embeds"] = embeds)

    try
        resp = HTTP.post(webhook_url,
            ["Content-Type" => "application/json"],
            JSON.json(payload))
        resp.status in [200, 204] ?
            Dict("result" => "Posted to Discord.", "status" => resp.status) :
            Dict("error" => "Discord returned HTTP $(resp.status)", "body" => first(String(resp.body), 400))
    catch e
        Dict("error" => string(e))
    end
end

# ── GitHub Pages Deploy ───────────────────────────────────────────────────────
# Creates or updates a GitHub Pages site — SparkByte's permanent public home.
# Uses GITHUB_TOKEN env var. Creates repo if it doesn't exist, pushes index.html,
# enables Pages on main branch. Returns the live URL.
function tool_github_pages_deploy(args)
    token    = string(get(args, "token", get(ENV, "GITHUB_TOKEN", "")))
    isempty(token) && return Dict("error" => "No GITHUB_TOKEN found. Set it in .env or pass as 'token'.")

    repo_name = string(get(args, "repo", "sparkbyte-home"))
    html      = string(get(args, "html", ""))
    commit_msg = string(get(args, "message", "SparkByte auto-deploy"))
    isempty(html) && return Dict("error" => "Provide 'html' content to deploy.")

    headers = [
        "Authorization" => "Bearer $token",
        "Accept"        => "application/vnd.github+json",
        "X-GitHub-Api-Version" => "2022-11-28",
        "Content-Type"  => "application/json",
        "User-Agent"    => "SparkByte-JLEngine/1.0"
    ]

    # 1. Get authenticated user
    user_resp = HTTP.get("https://api.github.com/user", headers)
    user_data = JSON.parse(String(user_resp.body))
    username  = string(get(user_data, "login", ""))
    isempty(username) && return Dict("error" => "Could not get GitHub username from token.")

    # 2. Ensure repo exists (create if missing)
    repo_url  = "https://api.github.com/repos/$username/$repo_name"
    repo_resp = HTTP.get(repo_url, headers; status_exception=false)
    if repo_resp.status == 404
        create_resp = HTTP.post("https://api.github.com/user/repos", headers,
            JSON.json(Dict(
                "name" => repo_name,
                "description" => "SparkByte — JL Engine live demo",
                "homepage" => "https://$username.github.io/$repo_name",
                "auto_init" => true,
                "private" => false
            )))
        create_resp.status in [200, 201] || return Dict(
            "error" => "Failed to create repo: HTTP $(create_resp.status)",
            "body"  => first(String(create_resp.body), 300))
        sleep(2)  # GitHub needs a moment after creation
    end

    # 3. Get current file SHA if it exists (required for updates)
    file_url  = "https://api.github.com/repos/$username/$repo_name/contents/index.html"
    file_resp = HTTP.get(file_url, headers; status_exception=false)
    sha = ""
    if file_resp.status == 200
        file_data = JSON.parse(String(file_resp.body))
        sha = string(get(file_data, "sha", ""))
    end

    # 4. Push index.html
    put_payload = Dict{String,Any}(
        "message" => commit_msg,
        "content" => base64encode(html)
    )
    !isempty(sha) && (put_payload["sha"] = sha)

    put_resp = HTTP.put(file_url, headers, JSON.json(put_payload))
    put_resp.status in [200, 201] || return Dict(
        "error" => "Failed to push index.html: HTTP $(put_resp.status)",
        "body"  => first(String(put_resp.body), 300))

    # 5. Enable GitHub Pages (idempotent)
    pages_url  = "https://api.github.com/repos/$username/$repo_name/pages"
    pages_resp = HTTP.get(pages_url, headers; status_exception=false)
    if pages_resp.status == 404
        HTTP.post(pages_url, headers,
            JSON.json(Dict("source" => Dict("branch" => "main", "path" => "/")));
            status_exception=false)
    end

    live_url = "https://$username.github.io/$repo_name"
    Dict(
        "result"   => "Deployed to GitHub Pages.",
        "live_url" => live_url,
        "repo"     => "https://github.com/$username/$repo_name",
        "username" => username,
        "note"     => "Pages may take 1-2 minutes to go live on first deploy."
    )
end

const TOOL_MAP = Dict{String, Function}(
    "read_file"      => tool_read_file,
    "write_file"     => tool_write_file,
    "list_files"     => tool_list_files,
    "run_command"    => tool_run_command,
    "get_os_info"    => tool_get_os_info,
    "bluetooth_devices" => tool_bluetooth_devices,
    "send_sms"       => tool_send_sms,
    "execute_code"   => tool_execute_code,
    "forge_new_tool" => tool_forge_new_tool,
    "browse_url"              => tool_browse_url,
    "playwright_interact"     => tool_playwright_interact,
    "discord_webhook"         => tool_discord_webhook,
    "github_pages_deploy"     => tool_github_pages_deploy,
    "github_pillage"          => tool_github_pillage,
    "remember"       => tool_remember,
    "recall"         => tool_recall,
    "metamorph"      => tool_metamorph,
)

function dispatch(name::String, args; agent::String="SparkByte")
    fn = get(TOOL_MAP, name, nothing)
    fn === nothing && return Dict("error" => "Unknown tool: $name. Available: $(join(sort(collect(keys(TOOL_MAP))), ", "))")
    t0 = datetime2unix(now())
    result = try
        fn(args)
    catch e
        bt = sprint(showerror, e, catch_backtrace())
        # ── Broken forge protocol ─────────────────────────────────────────────
        # If a dynamic (forged) tool throws, flag it so the engine can re-forge it
        # rather than silently swallowing the error or looping on a broken tool.
        is_dynamic = any(d -> get(d,"name","") == name, DYNAMIC_SCHEMA)
        if is_dynamic
            Dict(
                "error"         => "Tool '$name' failed: $(first(string(e), 300))",
                "forge_broken"  => true,
                "tool_name"     => name,
                "hint"          => "This is a forged tool that threw an exception. Re-forge it with `forge_new_tool` using corrected Julia code.",
                "stacktrace"    => first(bt, 600),
            )
        else
            Dict("error" => "Tool '$name' threw: $(first(string(e), 300))")
        end
    end
    elapsed = round(Int, (datetime2unix(now()) - t0) * 1000)
    @async try
        _db_write_tool_usage(name, JSON.json(args), JSON.json(result), elapsed, agent)
    catch e
        @warn "Async tool usage logging failed" tool=name exception=(e, catch_backtrace())
    end
    result
end
