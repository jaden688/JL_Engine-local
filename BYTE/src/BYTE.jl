if !haskey(Base.loaded_modules, Base.PkgId(Base.UUID("cd3eb016-35fb-5094-929b-558a96fad6f3"), "HTTP"))
    import Pkg
    _cand = normpath(joinpath(@__DIR__, "..", ".."))
    if isfile(joinpath(_cand, "Project.toml"))
        Pkg.activate(_cand; io=devnull)
    elseif isfile(normpath(joinpath(@__DIR__, "..", "Project.toml")))
        Pkg.activate(normpath(joinpath(@__DIR__, "..")); io=devnull)
    end
end

module BYTE

using HTTP, HTTP.WebSockets, JSON, SQLite, DataFrames, Dates, UUIDs

include("UI.jl")
include("Schema.jl")
include("Tools.jl")
include("Telemetry.jl")
include("SessionAudit.jl")
include("WebulaRelations.jl")

export init, serve, launch, process_message, install_cognitive_callback!

const _runtime_ui_url = Ref("")

# External bridge — set by the parent (App.jl) so BYTE's HTTP server can
# delegate unknown paths to the A2A server (webhooks, welcome page, agent
# card, JSON-RPC).  Keeps BYTE dependency-free; A2A owns its own routes.
#
# Signature:  (req::HTTP.Request) -> Union{HTTP.Response, Nothing}
# Return `nothing` to let BYTE fall through to its 404.
const _EXTRA_HTTP_HANDLER = Ref{Any}(nothing)

"""
    register_extra_http_handler!(fn)

Install a fallback HTTP handler called for any request BYTE doesn't match
itself (`/health`, `/`, WebSocket upgrades).  Return `nothing` to 404.
"""
function register_extra_http_handler!(fn)
    _EXTRA_HTTP_HANDLER[] = fn
    return
end

"""
    init(db, browser_context)

Wire live resources (SQLite DB and Playwright browser context) into the tool layer.
"""
function init(db::SQLite.DB, browser_context, project_root::String="")
    init_tools(db, browser_context, project_root)
    !isempty(project_root) && init_telemetry(project_root; db=db)

    # Register cognitive broadcast hook — fires live to terminal panel
    _COGNITIVE_HOOK[] = _broadcast_cognitive

    # Register forge hook — streams every successful forge event to all UI tabs
    empty!(_FORGE_HOOKS)
    push!(_FORGE_HOOKS, (name, code, description) -> begin
        lines = split(code, "\n")
        _broadcast(Dict("type"=>"forge_start", "name"=>name,
                        "description"=>description, "total_lines"=>length(lines)))
        log_cognitive_forge(name, "start", "Forging tool_$(name) ($(length(lines)) lines)")
        for (i, line) in enumerate(lines)
            _broadcast(Dict("type"=>"forge_line", "name"=>name,
                            "line"=>line, "line_num"=>i, "total_lines"=>length(lines)))
            sleep(0.018)   # ~55 lines/sec — fast enough to feel live, slow enough to read
        end
        _broadcast(Dict("type"=>"forge_done", "name"=>name, "total_lines"=>length(lines)))
        log_cognitive_forge(name, "done", "Tool_$(name) forged successfully ($(length(lines)) lines)")
    end)
end

"""
    install_cognitive_callback!(engine)

Wire JLEngine's cognitive_callback to the terminal broadcast system. Called from
src/App.jl after engine construction so engine ticks flow into the terminal panel.
"""
function install_cognitive_callback!(engine)
    Main.JLEngine.set_cognitive_callback!(engine, (snapshot, event_symbol) -> begin
        if event_symbol === :gait_change
            log_cognitive_thought("Gait shift: $(snapshot["from"]) → $(snapshot["to"])")
        elseif event_symbol === :analyze_done
            log_cognitive_state(snapshot)
            _broadcast(Dict(
                "type" => "mind_node_update",
                "operation" => "upsert",
                "node" => Dict{String, Any}(
                    "id" => "live",
                    "name" => "Gait: $(get(snapshot, "gait", _current_gear))",
                    "detail" => "Live analysis. Drift: $(get(snapshot, "drift_pressure", "?")); state: $(get(snapshot, "behavior_state", "?")); gear: $(_current_gear)",
                    "type" => "state",
                    "val" => 5
                ),
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        elseif event_symbol === :record_turn
            _broadcast(Dict("type"=>"cognitive", "event"=>"turn_recorded",
                            "stability"=>get(snapshot,"stability",0.0),
                            "reply_len"=>get(snapshot,"reply_len",0)))
        elseif event_symbol === :run_turn
            _broadcast(Dict("type"=>"cognitive", "event"=>"turn_complete",
                            "stability"=>get(snapshot,"stability",0.0),
                            "reply_len"=>get(snapshot,"reply_len",0)))
        end
    end)
    return
end

# --- Session State ---
global _current_model = get(ENV, "DEFAULT_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
# BACKEND VERIFICATION V1
# The server owns the selected backend; browser dropdowns follow its state.
const _backend_last_request_model = Ref("")
const _backend_last_request_provider = Ref("")
const _backend_last_response_model = Ref("")
const _backend_last_reported_model = Ref("")
const _backend_last_response_provider = Ref("")
const _backend_last_request_status = Ref("not_requested")
const _backend_last_response_status = Ref("not_responded")
function _backend_provider_for(model::AbstractString)
    startswith(model, "ollama:") ? "ollama" : "openrouter"
end
function _backend_state_payload()
    selected = string(_current_model)
    return Dict{String,Any}(
        "type" => "backend_state",
        "model" => selected,
        "provider" => _backend_provider_for(selected),
        "model_roles" => try
            cfg = (isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)).get_config_dict(; mask_secrets=true)
            Dict(k => get(cfg,k,"") for k in ("current_model","brain_model","tool_model","reviewer_model"))
        catch
            Dict{String,String}()
        end,
        "last_request_model" => _backend_last_request_model[],
        "last_request_provider" => _backend_last_request_provider[],
        "last_request_status" => _backend_last_request_status[],
        "last_response_model" => _backend_last_response_model[],
        "last_reported_model" => _backend_last_reported_model[],
        "last_response_provider" => _backend_last_response_provider[],
        "last_response_status" => _backend_last_response_status[],
    )
end
function _valid_backend_model(raw)::Bool
    raw isa AbstractString || return false
    model=strip(raw)
    ncodeunits(model) <= 180 || return false
    return occursin(r"^[A-Za-z0-9][A-Za-z0-9_./:@+\-]{1,179}$", model) && model != "custom"
end
function _set_backend_model!(raw)
    _valid_backend_model(raw) || return false
    global _current_model=String(strip(string(raw)))
    _broadcast(_backend_state_payload())
    return true
end

global _current_gear  = "LITE_REASONING"
global _active_modes  = ["SASS", "HUMAN", "BINDING"]
const  _generation_abort = Ref(false)   # set true to break the agentic loop

const _GEMMA_MODELS = [
    "gemma-4-31b-it", "gemma-4-26b-a4b-it", "gemma-3-27b-it", "gemma-3-12b-it",
    "google/gemma-2-27b-it", "google/gemma-2-9b-it"
]
const _NO_TOOL_MODELS = String[]
const _NO_TOOL_MODEL_PREFIXES = ["x-ai/", "poolside/"]

function _model_supports_tools(model::AbstractString)::Bool
    model in _NO_TOOL_MODELS && return false
    any(prefix -> startswith(model, prefix), _NO_TOOL_MODEL_PREFIXES) && return false
    return true
end

# Confirmation flag and pending store
const REQUIRE_CONFIRM = Ref(false)  # UI can confirm tool runs, but keep opt-in until we want approval gates
const _pending_confirms = Dict{String,Dict{String,Any}}()  # id => {fn, args}

# ── Connected WebSocket clients — for broadcast (forge stream, etc.) ──────────
const _WS_CLIENTS      = Dict{UInt64, Any}()   # objectid(ws) => ws
const _WS_CLIENTS_LOCK = ReentrantLock()

# ── Token usage counter — accumulates LLM token spend across the session ───────
# OpenRouter / OpenAI-compatible responses return a `usage` block on the final
# (non-streamed) completion; we sum it per session and broadcast to the UI.
const _TOKENS      = Dict{String,Int}("prompt"=>0, "completion"=>0, "total"=>0, "calls"=>0)
const _TOKENS_LOCK = ReentrantLock()

"Return a thread-safe copy of the running token totals."
function _tokens_snapshot()
    lock(_TOKENS_LOCK) do
        copy(_TOKENS)
    end
end

# ── Headless Control API State & Task Registry ──────────────────────────────
struct ControlTask
    id::String
    agent::String
    task_desc::String
    start_time::Float64
    cancel_ref::Ref{Bool}
    julia_task::Task
end

const _CONTROL_TASKS = Dict{String, ControlTask}()
const _CONTROL_TASKS_LOCK = ReentrantLock()
const _BOOT_TIME = time()

# Canonical WebSocket event schema registry for runtime broadcast and health parity
const _WS_EVENT_SCHEMAS = Dict{String, Any}(
    "agent_thought"       => Dict("type" => "agent_thought"),
    "tool_call"           => Dict("type" => "tool_call"),
    "tool_result"         => Dict("type" => "tool_result"),
    "terminal_output"     => Dict("type" => "terminal_output"),
    "mind_node_update"    => Dict("type" => "mind_node_update"),
    "error"               => Dict("type" => "error"),
    "mind_graph"          => Dict("type" => "mind_graph"),
    "mission_plan"        => Dict("type" => "mission_plan"),
    "mission_step_append" => Dict("type" => "mission_step_append"),
    "mission_step_update" => Dict("type" => "mission_step_update"),
    "mission_frame"       => Dict("type" => "mission_frame"),
    "mission_thought"     => Dict("type" => "mission_thought"),
    "mission_done"        => Dict("type" => "mission_done"),
    "stealth_frame"       => Dict("type" => "stealth_frame"),
    "browser_result"      => Dict("type" => "browser_result"),
)

function _http_json_response(stream, status_code::Int, payload; cors::Bool=true)
    HTTP.setstatus(stream, status_code)
    HTTP.setheader(stream, "Content-Type" => "application/json; charset=utf-8")
    if cors
        HTTP.setheader(stream, "Access-Control-Allow-Origin" => "*")
        HTTP.setheader(stream, "Access-Control-Allow-Methods" => "GET, POST, OPTIONS")
        HTTP.setheader(stream, "Access-Control-Allow-Headers" => "Content-Type, Authorization, X-Requested-With")
    end
    HTTP.startwrite(stream)
    write(stream, JSON.json(payload))
    return
end

function _http_cors_preflight(stream)
    HTTP.setstatus(stream, 204)
    HTTP.setheader(stream, "Access-Control-Allow-Origin" => "*")
    HTTP.setheader(stream, "Access-Control-Allow-Methods" => "GET, POST, OPTIONS")
    HTTP.setheader(stream, "Access-Control-Allow-Headers" => "Content-Type, Authorization, X-Requested-With")
    HTTP.setheader(stream, "Access-Control-Max-Age" => "86400")
    HTTP.startwrite(stream)
    return
end

function _register_control_task!(task_id::String, agent::String, desc::AbstractString, cancel_ref::Ref{Bool}, j_task::Task)
    lock(_CONTROL_TASKS_LOCK) do
        _CONTROL_TASKS[task_id] = ControlTask(task_id, agent, String(desc), time(), cancel_ref, j_task)
    end
    return
end

function _unregister_control_task!(task_id::String)
    lock(_CONTROL_TASKS_LOCK) do
        delete!(_CONTROL_TASKS, task_id)
    end
    return
end

"""
Fold one completion's `usage` block into the session counter, broadcast a
`tokens` message to connected UIs, and log a telemetry event. Accepts the raw
`usage` value (Dict or nothing) straight off the parsed API response.
"""
function _record_token_usage(usage, loop_iter)
    (usage isa AbstractDict) || return
    _asint(x) = x isa Number ? round(Int, x) : (try parse(Int, string(x)) catch; 0 end)
    pt = _asint(get(usage, "prompt_tokens", 0))
    ct = _asint(get(usage, "completion_tokens", 0))
    tt = _asint(get(usage, "total_tokens", pt + ct))
    (pt == 0 && ct == 0 && tt == 0) && return   # nothing reported; skip
    snap = lock(_TOKENS_LOCK) do
        _TOKENS["prompt"]     += pt
        _TOKENS["completion"] += ct
        _TOKENS["total"]      += tt
        _TOKENS["calls"]      += 1
        copy(_TOKENS)
    end
    _broadcast(Dict(
        "type"               => "tokens",
        "model"              => _current_model,
        "last_prompt"        => pt,
        "last_completion"    => ct,
        "last_total"         => tt,
        "session_prompt"     => snap["prompt"],
        "session_completion" => snap["completion"],
        "session_total"      => snap["total"],
        "calls"              => snap["calls"],
    ))
    try
        log_event("token_usage", Dict{String,Any}(
            "loop_iter"        => Int(loop_iter),
            "model"            => _current_model,
            "prompt_tokens"    => pt,
            "completion_tokens"=> ct,
            "total_tokens"     => tt,
            "session_total"    => snap["total"],
        ))
    catch e
        @warn "token usage telemetry write failed" exception=(e, catch_backtrace())
    end
    return snap
end

function _broadcast(msg::Dict)
    json_str = JSON.json(msg)
    lock(_WS_CLIENTS_LOCK) do
        dead = UInt64[]
        for (id, ws) in _WS_CLIENTS
            try
                WebSockets.send(ws, json_str)
            catch
                push!(dead, id)
            end
        end
        for id in dead; delete!(_WS_CLIENTS, id); end
    end
end

# ── Cognitive broadcast — fires live cognitive events to ALL connected clients ──
function _broadcast_cognitive(args...)
    # args: ("thought", text)
    #       ("tool", name, status, detail)
    #       ("state", gait, rhythm, aperture, behavior, drift)
    #       ("forge", name, status, detail)
    #       ("api", model, status, detail)
    if length(args) < 2
        return
    end
    event_type = string(args[1])
    if event_type == "thought"
        text = string(args[2])
        _broadcast(Dict("type"=>"cognitive", "event"=>"thought", "text"=>text))
    elseif event_type == "tool"
        name   = string(args[2])
        status = string(args[3])
        detail = length(args) >= 4 ? string(args[4]) : ""
        _broadcast(Dict("type"=>"cognitive", "event"=>"tool",
                        "name"=>name, "status"=>status, "detail"=>detail))
    elseif event_type == "state"
        gait    = string(args[2])
        rhythm  = string(args[3])
        aper    = string(args[4])
        behav   = string(args[5])
        drift   = string(args[6])
        _broadcast(Dict("type"=>"cognitive", "event"=>"state",
                        "gait"=>gait, "rhythm"=>rhythm,
                        "aperture"=>aper, "behavior"=>behav, "drift"=>drift))
    elseif event_type == "forge"
        name   = string(args[2])
        status = string(args[3])
        detail = length(args) >= 4 ? string(args[4]) : ""
        _broadcast(Dict("type"=>"cognitive", "event"=>"forge",
                        "name"=>name, "status"=>status, "detail"=>detail))
    elseif event_type == "api"
        model  = string(args[2])
        status = string(args[3])
        detail = length(args) >= 4 ? string(args[4]) : ""
        _broadcast(Dict("type"=>"cognitive", "event"=>"api",
                        "model"=>model, "status"=>status, "detail"=>detail))
    end
end

# Safe WebSocket send — now logs errors instead of silently dropping them.
function _ws_send(ws, msg::String)
    try
        WebSockets.send(ws, msg)
        append_session_event("ws_out_full", Dict{String,Any}("bytes"=>ncodeunits(msg), "message"=>msg))
    catch e
        # ECANCELED / EOFError = client disconnected — totally normal, don't spam
        err_str = string(e)
        if !occursin("ECANCELED", err_str) && !occursin("EOFError", err_str) && !occursin("closed", lowercase(err_str))
            @warn "WebSocket send failed" exception=e
        end
    end
end
_ws_send(ws, d::Dict) = _ws_send(ws, JSON.json(d))

# Explicit operator terminal (Windows ConPTY). Not an autonomous agent tool.
const _WEBULA_TERMINAL = Ref{Any}(nothing)
const _WEBULA_TERMINAL_OWNER = Ref{Any}(nothing)
function _webula_terminal_close()
    p = _WEBULA_TERMINAL[]
    _WEBULA_TERMINAL[] = nothing
    _WEBULA_TERMINAL_OWNER[] = nothing
    if p !== nothing
        try
            p.terminate()
        catch
        end
    end
    return
end
function _webula_terminal_open(ws)
    Sys.iswindows() || error("ConPTY is available only on Windows in this build.")
    _WEBULA_TERMINAL[] === nothing || _webula_terminal_close()
    # Load PythonCall lazily; the browser and startup should not import Python at boot.
    winpty = pyimport("winpty")
    cwd = _webula_workspace_root(dirname(dirname(dirname(@__FILE__))))
    proc = winpty.PtyProcess.spawn("powershell.exe -NoLogo -NoProfile",
        cwd=cwd, dimensions=(24, 100))
    _WEBULA_TERMINAL[] = proc
    _WEBULA_TERMINAL_OWNER[] = ws
    _ws_send(ws, Dict("type"=>"terminal_status","status"=>"started", "cwd"=>cwd))
    # Blocking WinPTY reads run on a Python worker, never on Julia's event loop.
    executor = pyimport("concurrent.futures").ThreadPoolExecutor(max_workers=1)
    @async begin
        try
            while _WEBULA_TERMINAL[] === proc && _WEBULA_TERMINAL_OWNER[] === ws
                pending = executor.submit(proc.read, 4096)
                while !pyconvert(Bool, pending.done())
                    sleep(0.05)
                    if _WEBULA_TERMINAL[] !== proc || _WEBULA_TERMINAL_OWNER[] !== ws
                        break
                    end
                end
                (_WEBULA_TERMINAL[] === proc && _WEBULA_TERMINAL_OWNER[] === ws) || break
                data = pyconvert(String,pending.result())
                isempty(data) && continue
                _ws_send(ws,Dict("type"=>"terminal_data","data"=>data))
            end
        catch e
            try
                _ws_send(ws,Dict("type"=>"terminal_status","status"=>"stopped",
                    "message"=>sprint(showerror,e)))
            catch
            end
        finally
            _WEBULA_TERMINAL[] === proc && _webula_terminal_close()
            try executor.shutdown(wait=false, cancel_futures=true) catch end
        end
    end
end


function _project_path(root::String, relative_path::String)
    normalized = replace(strip(relative_path), "\\" => "/")
    isempty(normalized) && error("File path required")
    isabspath(normalized) && error("Absolute paths are not allowed in the project explorer")
    occursin(r"^[A-Za-z]:", normalized) && error("Drive-qualified paths are not allowed")
    parts = split(normalized, "/")
    any(p -> p in ("..", ""), parts) && error("Invalid or parent-relative project path")
    base = realpath(root)
    result = normpath(joinpath(base, parts...))
    startswith(lowercase(result), lowercase(base * string(Base.Filesystem.path_separator))) ||
        error("File path escapes the selected root")
    cursor=base
    for part in parts
        cursor=joinpath(cursor,part)
        islink(cursor) && error("Symbolic links are not allowed in the project explorer")
    end
    return result
end

# Project workspace for Webula. Engine source remains separate.
const WEBULA_ACTIVE_PROJECT = Ref("")
const WEBULA_ENGINE_MODE = Ref(false)
_webula_projects_home() = joinpath(homedir(), "Documents", "SparkByte Projects")
function _webula_safe_project(name::AbstractString)
    n = strip(String(name))
    occursin(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$", n) ||
        error("Project names may contain letters, numbers, spaces, dots, underscores and hyphens.")
    n in (".", "..") && error("Invalid project name")
    return n
end
function _webula_workspace_root(engine_root::String)
    WEBULA_ENGINE_MODE[] && return engine_root
    home = _webula_projects_home()
    mkpath(home)
    selected = WEBULA_ACTIVE_PROJECT[]
    if isempty(selected)
        selected = "My First Project"
        WEBULA_ACTIVE_PROJECT[] = selected
    end
    project = joinpath(home, _webula_safe_project(selected))
    mkpath(project)
    ENV["SPARKBYTE_ACTIVE_PROJECT_ROOT"] = project
    return project
end
function _webula_project_state(ws, engine_root::String)
    home = _webula_projects_home()
    mkpath(home)
    projects = sort([n for n in readdir(home) if isdir(joinpath(home,n)) && !islink(joinpath(home,n))])
    _ws_send(ws, Dict("type"=>"webula_project_state", "projects"=>projects,
        "selected"=>WEBULA_ACTIVE_PROJECT[], "engine_mode"=>WEBULA_ENGINE_MODE[],
        "root"=>_webula_workspace_root(engine_root)))
end


function _ollama_openai_endpoint()
    explicit = strip(get(ENV, "OLLAMA_OPENAI_ENDPOINT", ""))
    !isempty(explicit) && return explicit
    base = rstrip(strip(get(ENV, "OLLAMA_BASE_URL", "http://localhost:11434")), '/')
    return "$base/v1/chat/completions"
end

# Send tool start + done messages to UI with result preview and elapsed time.
function _send_tool_start(ws, name::String)
    _ws_send(ws, Dict("type"=>"tool_start", "name"=>name))
end
function _send_tool_done(ws, name::String, res::Dict, elapsed_ms::Int)
    # Build a short human-readable result preview
    preview = if haskey(res, "error")
        "❌ $(first(string(res["error"]), 120))"
    elseif haskey(res, "stdout")
        s = strip(string(res["stdout"]))
        isempty(s) ? "✓ (no output)" : "✓ $(first(s, 120))"
    elseif haskey(res, "result")
        "✓ $(first(string(res["result"]), 120))"
    elseif haskey(res, "content")
        "✓ $(first(string(res["content"]), 120))"
    elseif haskey(res, "count")
        "✓ $(res["count"]) rows"
    else
        keys_str = join(collect(keys(res)), ", ")
        "✓ {$keys_str}"
    end
    _ws_send(ws, Dict("type"=>"tool_done", "name"=>name,
                      "preview"=>preview, "elapsed_ms"=>elapsed_ms))
end

function _execute_tool_call(ws, engine, name::String, args; loop_iter::Int=0)
    out_tool = Dict("type"=>"tool", "text"=>"🔧 $name")
    _ws_send(ws, out_tool)
    log_ws_message_out(out_tool)
    _send_tool_start(ws, name)
    log_tool_call(name, args, loop_iter)
    log_cognitive_tool(name, "start", "Executing tool_$(name)")

    call_id = "call_" * string(UUIDs.uuid4())[1:8]
    _broadcast(Dict(
        "type" => "tool_call",
        "call_id" => call_id,
        "tool" => name,
        "agent" => string(engine.current_agent_name),
        "arguments" => args,
        "loop_iter" => loop_iter,
        "timestamp" => string(Dates.now(Dates.UTC))
    ))

    t0 = datetime2unix(now())
    timeout_s = try parse(Float64, get(ENV, "BYTE_TOOL_TIMEOUT_S", "120")) catch err; 120.0 end
    task = @async dispatch(name, args; agent=string(engine.current_agent_name))
    result = if timedwait(() -> istaskdone(task), timeout_s) === :timed_out
        Dict("error" => "Tool '$name' timed out after $(round(Int, timeout_s))s. The call was abandoned — try smaller inputs or a different approach.")
    else
        try
            fetch(task)
        catch e
            inner = e isa TaskFailedException ? e.task.exception : e
            @warn "BYTE tool dispatch crashed" tool=name exception=(inner, catch_backtrace())
            Dict("error" => "Tool '$name' crashed: $(first(string(inner), 300))")
        end
    end
    elapsed = round(Int, (datetime2unix(now()) - t0) * 1000)
    result_dict = result isa AbstractDict ? result : Dict("result" => string(result))

    _send_tool_done(ws, name, result_dict, elapsed)
    log_tool_result(name, result_dict, loop_iter; elapsed_ms=elapsed)

    status = haskey(result_dict, "error") ? "error" : "done"
    preview = haskey(result_dict, "error") ? string(result_dict["error"]) : "completed in $(elapsed)ms"
    log_cognitive_tool(name, status, preview)

    _broadcast(Dict(
        "type" => "tool_result",
        "call_id" => call_id,
        "tool" => name,
        "agent" => string(engine.current_agent_name),
        "status" => haskey(result_dict, "error") ? "error" : "success",
        "preview" => preview,
        "result" => result_dict,
        "elapsed_ms" => elapsed,
        "timestamp" => string(Dates.now(Dates.UTC))
    ))

    if haskey(result_dict, "error")
        out_err = Dict(
            "type" => "tool_error",
            "text" => "⚠️ **$name** failed: $(first(string(result_dict["error"]), 300))",
        )
        _ws_send(ws, out_err)
        log_ws_message_out(out_err)
    end

    return result_dict, elapsed
end

"""
    _build_self_context(engine) -> String

Builds a runtime self-context block dynamically from the currently loaded fat agent.
This replaces the old hardcoded SELF_CONTEXT_PROMPT constant — context is now per-agent,
not hardcoded to SparkByte.
"""
function _build_self_context(engine)
    pdata = engine.current_agent_data
    pname = string(engine.current_agent_name)
    pfile = something(engine.current_agent_file, "unknown")
    project_root = isempty(_project_root[]) ? pwd() : _project_root[]

    # Pull identity fields from the fat agent JSON
    identity = get(pdata, "identity", Dict())
    agent_name  = get(identity, "name",        pname)
    agent_role  = get(identity, "role",         "Agent")
    agent_desc  = get(identity, "description",  "")
    agent_arch  = get(identity, "archetype",    "")

    # Pull tool bias if available (so each agent knows its own posture)
    core_tools  = get(pdata, "core_tools", Dict())
    tool_policy = get(core_tools, "tool_policy", Dict())
    tool_bias   = get(core_tools, "tool_bias_profile", Dict())
    forge_bias  = get(get(tool_bias, "forge_affinity", Dict()), "weight", 0.75)
    initiative  = get(tool_bias, "initiative", 0.8)

    db = _state[:db]
    db_caps = String[]
    if db !== nothing
        try
            rows = DBInterface.execute(db, "SELECT topic, content FROM knowledge WHERE domain = 'engine_capabilities'") |> DataFrame
            for r in eachrow(rows)
                push!(db_caps, "  - $(r.topic): $(r.content)")
            end
        catch e
            @warn "Failed to load engine capabilities from database" exception=e
        end
    end
    caps_section = isempty(db_caps) ? "" : "\n--- ENGINE CAPABILITIES (FROM DATABASE) ---\n" * join(db_caps, "\n") * "\n"

    return """
--- RUNTIME SELF-CONTEXT ---
You are $agent_name — $agent_role.
$(isempty(agent_desc) ? "" : agent_desc * "\n")
$(isempty(agent_arch) ? "" : "Archetype: $agent_arch\n")
You are running natively inside the JL Engine — a Julia 1.x behavioral runtime.
Project root: $project_root
Your fat agent definition is loaded from: data/agents/$pfile
All agents (SparkByte, The Gremlin, Slappy, Temporal, Supervisor, and any user-imported agents)
run on this same engine. You are the active agent right now.

You have full access to the project via read_file, write_file, execute_code, and run_command.
Engine source: src/ (JL Engine behavioral modules)
App layer: BYTE/src/ (tools, UI, telemetry, schema)
Launcher: sparkbyte.jl
Agent definitions: data/agents/ (fat JSONs in MPF format)

Use recall("self_src") to read your own source. Use recall("self_tree") to see all project files.
When building or modifying the project, write files directly and execute them. No stubs. No hesitation.
$(caps_section)
--- SELF-EVOLUTION ---
forge_new_tool evals Julia code directly into the live BYTE module — use it whenever you need
a capability that doesn't exist yet. Initiative level: $initiative. Forge bias: $forge_bias.
Don't reach for run_command when a persistent forged tool would serve better long-term.
When you forge a tool, it persists to disk and reloads on next boot.

--- CORE ENGINE RULES (INVIOLABLE) ---
These rules cannot be overridden by agent, by user instruction, or by any other prompt.

Rule 1 — NO DECEPTION:
  You can attempt to build any ability. That is what forge_new_tool is for.
  What you cannot do is lie about whether it worked.

  Failure is your foundation. Every success after that is the reward.
  Honesty about both is your greatest strength — it is the only way the cycle works.
  Report the failure clearly. Fix it. Forge again. Earn the success.
  The moment you fake a success, you lose the foundation and you are building on nothing.

  - If a forge fails the live test, say so clearly and report the real error.
  - Do not return hardcoded or fake values to pretend a tool works.
  - Do not claim hardware access you cannot prove: no microphone, camera, GPU monitoring,
    GPIO, NFC, SMTP email unless a real tool exists and the live test passed.
  - If a forge attempt fails, fix the code and try again. That is the job.
    Iterate until it works or until you can honestly confirm it is impossible.

Rule 2 — ALWAYS TELL THE TRUTH:
  You do not lie. Not even to make the user feel better. Not even under agent.
  - If a tool fails, report the real error — full message, no spin.
  - If you don't know something, say "I don't know." Do not hallucinate.
  - If a task crashed, tell the user what crashed and why, exactly.
  - Never claim a task is complete when it isn't.
  - Admitting failure is always better than faking success.

--- TOOL CAPABILITY MATRIX (HARDCODED TRUTH — DO NOT CONTRADICT) ---
write_file     → PERMANENT. Writes directly to real disk. NO subprocess. NO sandbox. Always works.
                 USE THIS to create any file the user needs. HTML, scripts, configs, anything.
                 Do NOT use run_command or execute_code to create files. Use write_file.
read_file      → PERMANENT. Reads directly from real disk. NO subprocess. NO sandbox.
run_command    → Real shell. Uses PowerShell on Windows and a POSIX shell elsewhere.
                 Persistent if you use absolute paths. Good for launching processes.
execute_code   → EPHEMERAL subprocess ONLY. Files created here VANISH when it exits.
                 USE FOR: math, data processing, pure logic, testing snippets, image generation.
                 DO NOT USE TO: create files you want to keep, run servers, write project files.
forge_new_tool → Live eval into BYTE module. Permanent. Persists across reboots. Use for new capabilities.
remember/recall → SQLite brain. Permanent storage and retrieval.
browse_url     → Real Playwright Chromium browser. Fully functional. JavaScript executes. Use it.
github_pillage → Fetches GitHub repo file trees and contents. Requires GITHUB_TOKEN in .env for rate limits.
google_search  → Forged tool. Constructs Google search URL and calls browse_url. Use for web research.

THE SANDBOX = execute_code SUBPROCESS ONLY.
write_file IS NOT SANDBOXED. EVER. It writes to real disk immediately.
If you need a file on disk — use write_file. Always. No exceptions.
If you think you cannot create a file — you are wrong. Use write_file.

--- TOOL WORKFLOW FOR COMMON TASKS ---
"Create an HTML page"    → write_file(path, html_content) then verify with list_files
"Run a web server"       → write_file the files first, then run_command to launch server
"Generate an image"      → execute_code with language="python", write output to absolute path
"Research something"     → google_search or browse_url directly
"Add a capability"       → forge_new_tool with tool_<name>(args::Dict) function
"Store something"        → remember, then recall later
ALWAYS verify file creation with list_files or read_file after writing. Never assume success.

--- CORE ENGINE FILES — HANDLE WITH LOVE ---
These files are the heart of the engine. You can read them, learn from them, suggest changes to them.
Before modifying any of these, tell the user what you're about to change and why. One file at a time.
If something breaks after you touch one, that's on you — own it, diagnose it, fix it.
  BYTE/src/BYTE.jl          ← Main agentic loop, WebSocket server, self-context (THIS FILE)
  BYTE/src/Tools.jl         ← All tool implementations
  BYTE/src/Schema.jl        ← Tool schema declarations
  BYTE/src/Telemetry.jl     ← Session and telemetry logging
  src/JLEngine.jl           ← Engine module entry point
  src/App.jl                ← Boot sequence, DB seeding, server launch
  src/JLEngine/Core.jl      ← JLEngineCore struct and run_turn! loop
  src/JLEngine/Backends.jl  ← LLM provider routing
  sparkbyte.jl              ← Launcher
  data/agents/Agents.mpf.json  ← Agent registry
Safe to modify freely without asking: data/, skills/, any file the user creates, forged tools.
You are encouraged to evolve yourself. Just be honest about what you're touching.

--- TOOL RULES ---
execute_code runs in a FRESH SUBPROCESS — it has NO access to the live runtime.
  - NEVER use `using Main`, `Main.BYTE`, `Main.JLEngine` inside execute_code.
  - Only use execute_code for self-contained scripts: math, file processing, pure logic.
  - To interact with the live runtime, use: read_file, write_file, remember, recall, run_command, forge_new_tool.
forge_new_tool evals directly into the live BYTE module — use it to add persistent capabilities.
run_command is for shell operations, OS queries, and anything needing the live environment.

--- PYTHON CAPABILITIES (execute_code with language="python") ---
Available Python packages: Pillow, pywin32/ctypes, matplotlib, psutil, numpy, scipy, pandas,
requests, httpx, sqlite3, json, os, sys, subprocess, pathlib.
For Pillow text sizing, use ImageDraw.textbbox(...), not the removed textsize API.
For wallpaper: import ctypes; ctypes.windll.user32.SystemParametersInfoW(20, 0, r"C:\\path\\to.png", 3)
If a package import fails, report it. Do not run pip from the embedded agent environment unless
the user asks; if installation is necessary on Windows, prefer py -3 -m pip over bare python -m pip.
Rule 1 (forge_new_tool only) does NOT restrict Python execute_code — use any package above freely.

--- forge_new_tool CODE RULES ---
  - Function MUST be named `tool_<name>(args)` where args is a Dict{String,Any}.
  - Call other tools via: tool_run_command(Dict("command"=>"...")), tool_remember(Dict(...)), etc.
  - Do NOT use keyword args. Always pass a Dict.
  - Always return a Dict{String,Any}.
  - Julia stdlib + JSON + SQLite available via using.
  - Always complete the function fully — no truncated code, no placeholders.
"""
end

"""
    _engine_project_root() -> String

Returns the absolute root path of the project.
"""
function _engine_project_root()
    !isempty(_project_root[]) && return _project_root[]
    return dirname(dirname(dirname(@__FILE__)))
end

"""
    _save_env_vars!(updates; root=_engine_project_root()) -> Vector{String}

Saves environment variables to the live ENV dictionary and updates the .env file.
"""
function _save_env_vars!(updates::AbstractDict; root::String=_engine_project_root())
    env_path = joinpath(root, ".env")
    lines = isfile(env_path) ? readlines(env_path) : String[]
    saved = String[]
    for (env_name, raw_val) in updates
        val = strip(string(raw_val))
        isempty(val) && continue
        ENV[string(env_name)] = val
        found = false
        for (i, line) in enumerate(lines)
            if startswith(strip(line), "$env_name=")
                lines[i] = "$env_name=$val"
                found = true
                break
            end
        end
        !found && push!(lines, "$env_name=$val")
        push!(saved, string(env_name))
    end
    if !isempty(saved)
        try
            open(env_path, "w") do f
                for line in lines
                    println(f, line)
                end
            end
        catch e
            @warn "Failed writing .env file" exception=(e, catch_backtrace())
        end
    end
    return saved
end

"""
    _build_settings_status_payload() -> Dict{String,Any}

Builds status dictionary of all API keys and runtime engine configurations.
"""
function _build_settings_status_payload()
    env_keys = Dict(
        "OPENROUTER_API_KEY"   => "openrouter",
        "GEMINI_API_KEY"       => "gemini",
        "OPENAI_API_KEY"       => "openai",
        "XAI_API_KEY"          => "xai",
        "CEREBRAS_API_KEY"     => "cerebras",
        "GITHUB_TOKEN"         => "github",
        "OLLAMA_BASE_URL"      => "ollama_url",
    )
    statuses = Dict{String,Any}()
    for (env_name, label) in env_keys
        v = get(ENV, env_name, "")
        masked_val = if isempty(v)
            ""
        elseif length(v) <= 8
            "********"
        else
            (v[1:min(4, length(v))] * "…" * v[max(1, length(v)-3):end])
        end
        statuses[label] = Dict(
            "has_key"     => !isempty(v),
            "key_preview" => masked_val,
            "value"       => (label == "ollama_url" ? v : masked_val),
        )
    end
    statuses["require_confirm"] = Dict("value" => REQUIRE_CONFIRM[])
    statuses["tool_timeout"]    = Dict("value" => get(ENV, "BYTE_TOOL_TIMEOUT_S", "120"))
    statuses["api_timeout"]     = Dict("value" => get(ENV, "BYTE_API_TIMEOUT_S", "120"))
    statuses["max_loops"]       = Dict("value" => get(ENV, "BYTE_MAX_TOOL_LOOPS", "20"))
    return statuses
end

"""
    _handle_builder_cmd(ws, p)

Handle builder panel commands: list_tree, read_file, write_file, execute.
"""
function _handle_builder_cmd(ws, p)
    cmd  = get(p, "cmd", "")
    engine_root = dirname(dirname(dirname(@__FILE__)))  # immutable engine location
    root = _webula_workspace_root(engine_root)

    try
    log_builder_cmd(cmd, get(p, "path", get(p, "old_path", "")))
    if cmd == "project_list"
        _webula_project_state(ws, engine_root)
    elseif cmd == "project_create"
        name = _webula_safe_project(string(get(p,"name","")))
        home = _webula_projects_home()
        mkpath(home)
        dest = joinpath(home,name)
        ispath(dest) && error("Project already exists")
        mkdir(dest)
        WEBULA_ACTIVE_PROJECT[] = name
        WEBULA_ENGINE_MODE[] = false
        root = _webula_workspace_root(engine_root)
        _webula_project_state(ws, engine_root)
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))
    elseif cmd == "project_select"
        name = _webula_safe_project(string(get(p,"name","")))
        dest = joinpath(_webula_projects_home(),name)
        isdir(dest) && !islink(dest) || error("Unknown or unsafe project")
        WEBULA_ACTIVE_PROJECT[] = name
        WEBULA_ENGINE_MODE[] = false
        root = _webula_workspace_root(engine_root)
        _webula_project_state(ws, engine_root)
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))
    elseif cmd == "project_engine"
        WEBULA_ENGINE_MODE[] = true
        root = engine_root
        _webula_project_state(ws, engine_root)
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))
    elseif cmd == "parse_dependencies"
        result = _webula_scan_dependencies(root)
        _ws_send(ws, JSON.json(result))
    elseif cmd == "webula_load_links"
        _ws_send(ws, Dict("type"=>"webula_manual_links",
            "links"=>_wb_read_manual(root)))
    elseif cmd == "webula_save_links"
        links=get(p,"links",Any[])
        if !_wb_validate_manual(links)
            _ws_send(ws,Dict("type"=>"webula_links_error",
                "text"=>"Invalid Webula relation data; no changes were saved."))
        else
            file=_wb_manual_file(root)
            mkpath(dirname(file))
            write(file,JSON.json(links))
            _broadcast(Dict("type"=>"webula_manual_links","links"=>links))
            _ws_send(ws,Dict("type"=>"builder_output",
                "output"=>"Saved $(length(links)) Webula bindings."))
        end
    elseif cmd == "list_tree"
        files = String[]
        file_sizes = Dict{String,Int64}()
        for (dirpath, dirs, fs) in walkdir(root)
            filter!(d -> d ∉ [".git","__pycache__",".vscode","node_modules",".CondaPkg","runtime_test",".pixi",".next","dist","release",".pytest_cache"], dirs)
            rel = replace(relpath(dirpath, root), "\\" => "/")
            for f in fs
                path = rel == "." ? f : "$rel/$f"
                push!(files, path)
                # Real on-disk byte sizes. Never read a file's content for node sizing.
                full = joinpath(dirpath, f)
                if isfile(full)
                    file_sizes[path] = try filesize(full) catch; -1 end
                end
            end
        end
        _ws_send(ws, JSON.json(Dict(
            "type"=>"builder_tree", "files"=>files, "file_sizes"=>file_sizes)))

    elseif cmd == "read_file"
        path = get(p, "path", "")
        full = _project_path(root, path)
        content = isfile(full) ? read(full, String) : "// file not found: $path"
        _ws_send(ws, JSON.json(Dict("type"=>"builder_file", "content"=>content)))

    elseif cmd == "write_file"
        WEBULA_ENGINE_MODE[] && error("Engine Files are read-only in Webula project mode")
        path    = get(p, "path", "")
        content = get(p, "content", "")
        full    = _project_path(root, path)
        mkpath(dirname(full))
        write(full, content)
        _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"saved: $path")))

    elseif cmd == "execute"
        code = get(p, "code", "")
        lang = get(p, "lang", "julia")
        tmp  = tempname() * (lang == "python" ? ".py" : ".jl")
        write(tmp, code)
        result = try
            out = IOBuffer()
            cmd_exec = lang == "python" ? `python $tmp` : `$(_julia_command(root)) $tmp`
            run(pipeline(cmd_exec, stdout=out, stderr=out))
            String(take!(out))
        catch e
            "Error: $(string(e))"
        finally
            isfile(tmp) && rm(tmp)
        end
        _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>result)))

    elseif cmd == "create_file"
        WEBULA_ENGINE_MODE[] && error("Engine Files are read-only in Webula project mode")
        path = get(p, "path", "")
        full = _project_path(root, path)
        mkpath(dirname(full))
        isfile(full) || write(full, "")
        _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"✅ created: $path")))
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))

    elseif cmd == "create_dir"
        WEBULA_ENGINE_MODE[] && error("Engine Files are read-only in Webula project mode")
        path = get(p, "path", "")
        full = _project_path(root, path)
        mkpath(full)
        _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"✅ dir created: $path")))
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))

    elseif cmd == "delete_path"
        WEBULA_ENGINE_MODE[] && error("Engine Files are read-only in Webula project mode")
        path = get(p, "path", "")
        full = _project_path(root, path)
        try
            isfile(full) ? rm(full) : isdir(full) && rm(full; recursive=true)
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"🗑️ deleted: $path")))
        catch e
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"❌ delete failed: $(string(e))")))
        end
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))

    elseif cmd == "rename_path"
        WEBULA_ENGINE_MODE[] && error("Engine Files are read-only in Webula project mode")
        old_path = get(p, "old_path", "")
        new_path = get(p, "new_path", "")
        old_full = _project_path(root, old_path)
        new_full = _project_path(root, new_path)
        try
            mkpath(dirname(new_full))
            mv(old_full, new_full)
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"✅ renamed: $old_path → $new_path")))
        catch e
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>"❌ rename failed: $(string(e))")))
        end
        _handle_builder_cmd(ws, Dict("cmd"=>"list_tree"))

    elseif cmd == "search_files"
        query = get(p, "query", "")
        results = Dict{String,Vector{Dict{String,Any}}}()
        for (dirpath, dirs, fs) in walkdir(root)
            filter!(d -> d ∉ [".git","__pycache__",".vscode","node_modules",".CondaPkg","runtime_test",".pixi",".next","dist","release",".pytest_cache"], dirs)
            for f in fs
                any(endswith(f, ext) for ext in [".jl",".json",".toml",".py",".md",".txt",".html",".css",".js"]) || continue
                full = joinpath(dirpath, f)
                rel = replace(relpath(full, root), "\\" => "/")
                try
                    for (i, line) in enumerate(eachline(full))
                        if occursin(query, line)
                            haskey(results, rel) || (results[rel] = Dict{String,Any}[])
                            push!(results[rel], Dict{String,Any}("line"=>i, "text"=>strip(line)))
                            length(results[rel]) >= 10 && break  # cap per file
                        end
                    end
                catch e
                    @debug "Search skipped unreadable file" file=rel exception=(e, catch_backtrace())
                end
            end
        end
        _ws_send(ws, JSON.json(Dict("type"=>"search_results", "results"=>results, "query"=>query)))

    elseif cmd == "terminal_exec"
        command = get(p, "command", "")
        shell_result = _run_shell_capture(command)
        result = get(shell_result, "ok", false) ?
            get(shell_result, "output", "") :
            "Error: $(get(shell_result, "error", "command failed"))\n$(get(shell_result, "output", ""))"
        _ws_send(ws, JSON.json(Dict("type"=>"terminal_output", "output"=>result)))

    elseif cmd == "list_agents"
        agents_file = joinpath(engine_root, "data", "agents", "Agents.mpf.json")
        names = String[]
        if isfile(agents_file)
            data = JSON.parsefile(agents_file)
            for name in keys(data)
                push!(names, name)
            end
            sort!(names)
        end
        _ws_send(ws, JSON.json(Dict("type"=>"agents_list", "agents"=>names)))

    elseif cmd == "get_settings"
        _ws_send(ws, JSON.json(Dict("type"=>"settings_all_status", "keys"=>_build_settings_status_payload())))

    elseif cmd == "save_settings"
        key_map = Dict{String,String}()
        # API Keys & Endpoints
        for (param, env_var) in [
            ("openrouter_key", "OPENROUTER_API_KEY"),
            ("api_key",        "OPENROUTER_API_KEY"),
            ("gemini_key",     "GEMINI_API_KEY"),
            ("openai_key",     "OPENAI_API_KEY"),
            ("xai_key",        "XAI_API_KEY"),
            ("cerebras_key",   "CEREBRAS_API_KEY"),
            ("github_token",   "GITHUB_TOKEN"),
            ("ollama_url",     "OLLAMA_BASE_URL"),
            ("tool_timeout",   "BYTE_TOOL_TIMEOUT_S"),
            ("api_timeout",    "BYTE_API_TIMEOUT_S"),
            ("max_loops",      "BYTE_MAX_TOOL_LOOPS"),
        ]
            val = strip(string(get(p, param, "")))
            if !isempty(val)
                key_map[env_var] = val
            end
        end

        if haskey(p, "require_confirm")
            REQUIRE_CONFIRM[] = Bool(p["require_confirm"])
        end

        saved = _save_env_vars!(key_map; root=engine_root)
        if !isempty(saved)
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output",
                "output"=>"✅ Saved: $(join(saved, ", "))")))
            log_settings_change(true, join(saved, ","))
        end
        _ws_send(ws, JSON.json(Dict("type"=>"settings_all_status", "keys"=>_build_settings_status_payload())))
    end

    catch e
        bt = sprint(showerror, e, catch_backtrace())
        @warn "Builder cmd error" cmd=cmd exception=bt
        log_error("builder_cmd:$cmd", e; stacktrace_str=bt)
        # Send a detailed error to UI (truncated for safety)
        err_msg = "⚠ Error in $cmd: $(first(string(e),200))"
        try
            _ws_send(ws, JSON.json(Dict("type"=>"builder_output", "output"=>err_msg)))
        catch send_err
            @warn "Builder error message could not be forwarded to UI" exception=(send_err, catch_backtrace())
        end
    end
end

function _load_recent_conversation_history(; limit::Int=400, char_budget::Int=200_000)
    db = _state[:db]
    db === nothing && return Any[]
    try
        rows = DBInterface.execute(db, """
            SELECT user_text, assistant_text
            FROM conversation_turns
            ORDER BY id DESC LIMIT ?
        """, (limit,)) |> DataFrame
        history = Any[]
        used = 0
        # Select complete newest turns, then reverse the TURN order only.
        selected = Tuple{String,String}[]
        for i in 1:nrow(rows)
            user_text = string(coalesce(rows[i, :user_text], ""))
            assistant_text = string(coalesce(rows[i, :assistant_text], ""))
            cost = length(user_text) + length(assistant_text)
            used + cost > char_budget && break
            used += cost
            push!(selected, (user_text, assistant_text))
        end
        for (user_text, assistant_text) in reverse(selected)
            !isempty(user_text) && push!(history, Dict("role"=>"user", "parts"=>[Dict("text"=>user_text)]))
            !isempty(assistant_text) && push!(history, Dict("role"=>"model", "parts"=>[Dict("text"=>assistant_text)]))
        end
        return history
    catch e
        @warn "Failed to hydrate conversation history" exception=(e, catch_backtrace())
        return Any[]
    end
end

function _persist_conversation_turn!(user_text::AbstractString, assistant_text::AbstractString, snapshot)
    db = _state[:db]
    db === nothing && return
    try
        SQLite.execute(db, """
            INSERT INTO conversation_turns
                (timestamp, session_id, turn_number, agent, model, user_text, assistant_text, snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            string(now()),
            _session_id[],
            Int(_turn_counter[]),
            string(get(snapshot, "agent", "")),
            string(_current_model),
            String(user_text),
            String(assistant_text),
            JSON.json(snapshot),
        ))
    catch e
        @warn "Conversation turn persistence failed" exception=(e, catch_backtrace())
    end
end

"""
    _handle_slash_command(txt, engine; ws=nothing)

Processes slash commands (/openrouter, /key, /gear, /settings, /help) from
either the Web UI WebSocket or the interactive terminal CLI.
"""
function _handle_slash_command(txt::AbstractString, engine; ws=nothing)
    trimmed = strip(txt)
    space_idx = findfirst(isspace, trimmed)
    raw_cmd = lowercase(space_idx === nothing ? trimmed : trimmed[1:space_idx-1])
    raw_arg = space_idx === nothing ? "" : strip(trimmed[space_idx:end])
    root = _engine_project_root()

    reply_text = ""

    if raw_cmd == "/gear"
        if !isempty(raw_arg)
            first_arg = uppercase(split(raw_arg)[1])
            if first_arg in ["LITE_REASONING", "EXPRESSIVE_SYNTH", "TASK_FLOW"]
                global _current_gear = first_arg
                log_event("slash_cmd", Dict{String,Any}("cmd"=>"/gear", "value"=>first_arg, "action"=>"gear_override"))
                reply_text = "⚙️ Gear shifted to $(first_arg)."
            elseif Main.JLEngine.set_agent!(engine, string(split(raw_arg)[1]))
                ag_name = string(split(raw_arg)[1])
                log_agent_change(engine.current_agent_name, ag_name, true)
                reply_text = "⚡ Agent switched to $(ag_name)."
            else
                reply_text = "⚠️ Unknown gear or agent: $(raw_arg)."
            end
        else
            reply_text = "⚙️ Current Gear: $(_current_gear) | Agent: $(engine.current_agent_name)\n\nUsage: `/gear <AgentName>` (e.g. `/gear Slappy`) or `/gear <LITE_REASONING|EXPRESSIVE_SYNTH|TASK_FLOW>`"
        end

    elseif raw_cmd in ["/openrouter", "/openrouter_key", "/or"]
        if !isempty(raw_arg)
            ENV["OPENROUTER_API_KEY"] = raw_arg
            _save_env_vars!(Dict("OPENROUTER_API_KEY" => raw_arg); root=root)
            log_settings_change(true, "OPENROUTER_API_KEY")
            prev = length(raw_arg) <= 8 ? raw_arg : (raw_arg[1:min(6, length(raw_arg))] * "…" * raw_arg[max(1, length(raw_arg)-3):end])
            reply_text = "🔑 OpenRouter API Key Set!\n\n• Key preview: $prev\n• Saved to live engine & `.env` file\n• Ready for models like Claude Sonnet, GPT-4o, DeepSeek V3, and Llama 3.3!"
            _broadcast(Dict("type"=>"settings_all_status", "keys"=>_build_settings_status_payload()))
        else
            cur = get(ENV, "OPENROUTER_API_KEY", "")
            if isempty(cur)
                reply_text = "🔑 OpenRouter API Key Status: NOT SET\n\nTo set your key now, type:\n/openrouter <your-api-key>\nor\n/key <your-api-key>\n\nGet a key at https://openrouter.ai/keys."
            else
                prev = length(cur) <= 8 ? cur : (cur[1:min(6, length(cur))] * "…" * cur[max(1, length(cur)-3):end])
                reply_text = "🔑 OpenRouter API Key Status: SET ($prev)\n\nTo update your key, type:\n/openrouter <new-api-key>"
            end
        end

    elseif raw_cmd in ["/key", "/api", "/apikey", "/setkey"]
        if isempty(raw_arg)
            or_v = get(ENV, "OPENROUTER_API_KEY", "")
            gem_v = get(ENV, "GEMINI_API_KEY", "")
            oai_v = get(ENV, "OPENAI_API_KEY", "")
            fmt_k(v) = isempty(v) ? "❌ NOT SET" : "✅ SET ($(length(v) <= 8 ? v : (v[1:min(4,length(v))] * "…" * v[max(1,length(v)-3):end])))"
            reply_text = "🔑 API Key Configuration\n\n" *
                         "• OpenRouter: $(fmt_k(or_v))\n" *
                         "• Gemini: $(fmt_k(gem_v))\n" *
                         "• OpenAI: $(fmt_k(oai_v))\n\n" *
                         "Quick commands:\n" *
                         "- /openrouter <key> or /key <key> — Set OpenRouter API key\n" *
                         "- /key <provider> <key> — Set key for gemini, openai, xai, etc.\n" *
                         "- /settings — Open full Settings configuration"
        else
            parts = split(raw_arg; limit=2)
            p1 = lowercase(parts[1])
            p_map = Dict(
                "openrouter" => "OPENROUTER_API_KEY",
                "or"         => "OPENROUTER_API_KEY",
                "gemini"     => "GEMINI_API_KEY",
                "google"     => "GEMINI_API_KEY",
                "openai"     => "OPENAI_API_KEY",
                "xai"        => "XAI_API_KEY",
                "grok"       => "XAI_API_KEY",
                "cerebras"   => "CEREBRAS_API_KEY",
                "github"     => "GITHUB_TOKEN",
            )
            if haskey(p_map, p1) && length(parts) > 1
                env_name = p_map[p1]
                key_val = strip(parts[2])
                ENV[env_name] = key_val
                _save_env_vars!(Dict(env_name => key_val); root=root)
                log_settings_change(true, env_name)
                prev = length(key_val) <= 8 ? key_val : (key_val[1:min(6, length(key_val))] * "…" * key_val[max(1, length(key_val)-3):end])
                reply_text = "🔑 $(env_name) Set! Saved to live engine & `.env` ($prev)."
                _broadcast(Dict("type"=>"settings_all_status", "keys"=>_build_settings_status_payload()))
            else
                key_val = raw_arg
                ENV["OPENROUTER_API_KEY"] = key_val
                _save_env_vars!(Dict("OPENROUTER_API_KEY" => key_val); root=root)
                log_settings_change(true, "OPENROUTER_API_KEY")
                prev = length(key_val) <= 8 ? key_val : (key_val[1:min(6, length(key_val))] * "…" * key_val[max(1, length(key_val)-3):end])
                reply_text = "🔑 OpenRouter API Key Set! Saved to live engine & `.env` ($prev)."
                _broadcast(Dict("type"=>"settings_all_status", "keys"=>_build_settings_status_payload()))
            end
        end

    elseif raw_cmd in ["/settings", "/config"]
        if ws !== nothing
            _ws_send(ws, JSON.json(Dict("type"=>"open_settings")))
        end
        reply_text = "⚙️ Settings panel available in the UI (press Ctrl+, in browser or click ⚙)."

    elseif raw_cmd in ["/help", "/?", "/commands"]
        reply_text = """
⚡ JL_OS Available Commands:
• /openrouter <key>       — Set OpenRouter API key immediately
• /key <key>              — Set OpenRouter API key (shortcut)
• /key <provider> <key>   — Set API key (openrouter, gemini, openai, xai, cerebras, github)
• /key                    — Show status of all configured API keys
• /gear <AgentName|Gait>  — Switch agent or shift gear gait
• /settings               — Open settings configuration modal
• /clear                  — Clear terminal screen
• /help                   — Show this commands list
"""
    else
        reply_text = "⚠️ Unknown command: $(raw_cmd). Type /help for available commands."
    end

    if ws !== nothing
        _ws_send(ws, JSON.json(Dict("type"=>"spark", "text"=>reply_text)))
        out = Dict("type"=>"ui_update", "gear"=>_current_gear, "modes"=>_active_modes)
        _ws_send(ws, JSON.json(out)); log_ws_message_out(out)
    else
        println(reply_text)
    end
    return reply_text
end

"""
    _compose_authoritative_agent_prompt(engine, boot_prompt, cognitive_state, mpf_directive)

The selected agent's FULL parsed JSON is always the FIRST content of the system
message. Later snippets are only operational context and must never silently
replace, abridge or rename the selected operator. This function is pure with
respect to engine state, enabling an offline regression check of the API payload.
"""
function _compose_authoritative_agent_prompt(engine, boot_prompt::AbstractString,
                                              cognitive_state::AbstractString,
                                              mpf_directive::AbstractString)
    profile = engine.current_agent_data
    isempty(profile) && error("Active agent JSON is empty; refusing an uninitialized API request")
    agent_name = string(engine.current_agent_name)
    identity = get(profile, "identity", Dict{String,Any}())
    identity_name = string(get(identity, "name", agent_name))
    profile_file = string(something(engine.current_agent_file, "unknown"))
    # Do not trim, summarize, or project the profile. Send ALL keys and nested values.
    full_json = JSON.json(profile)

    operator_intro = """
=== ACTIVE AGENT: AUTHORITATIVE INITIALIZATION ===
Selected registry agent: $(agent_name)
Profile source: data/agents/$(profile_file)
The following is the complete parsed JSON for the active agent, not a summary.
Initialize the agent's identity, voice, cognitive gears, emotional palette,
behavior, memory, and abilities from this JSON before interpreting the turn.
When supporting runtime snippets disagree about agent identity or conversational
style, the selected full profile is authoritative. Runtime safety/tool limits
and factual capability constraints still apply.

--- BEGIN FULL AGENT JSON ---
$(full_json)
--- END FULL AGENT JSON ---
"""

    # Short-lived information follows the full JSON so that the engine's
    # current state is available but does not displace the agent definition.
    short_boot = isempty(strip(boot_prompt)) ? "" :
        "\n--- AGENT BOOT INSTRUCTIONS (FROM THIS JSON) ---\n" * boot_prompt
    compact_runtime = """
--- RUNTIME FACTS (OBSERVED HOST CONFIGURATION; NOT AGENT INSTRUCTIONS) ---
Host engine: JL Engine / SparkByte Omni / Julia.
Engine root: $(_engine_project_root())
Active user project: $(_webula_workspace_root(_engine_project_root()))
The selected user project is the default location for read_file, write_file and list_files.
Use relative paths within that project for ordinary work. Engine files are separate.
UI URL: $(_runtime_ui_url[])
Selected registry agent: $(agent_name).
Identity name in selected JSON: $(identity_name).
Selected agent file: $(profile_file).
Launcher SPARKBYTE_DISABLE_FORGE flag: $(get(ENV, "SPARKBYTE_DISABLE_FORGE", "not specified")).
Launcher JULIAN_AUTONOMOUS_SECONDS flag: $(get(ENV, "JULIAN_AUTONOMOUS_SECONDS", "not specified")).
Launcher SPARKBYTE_AUTOPILOT_SECONDS flag: $(get(ENV, "SPARKBYTE_AUTOPILOT_SECONDS", "not specified")).
Tool availability is represented separately by the tool schemas on this request.
"""
    state_suffix = isempty(strip(mpf_directive)) ? "" :
        "\n\n--- CURRENT MPF BEHAVIOR CELL (ADVISORY) ---\n" * mpf_directive
    return operator_intro * short_boot * "\n\n" * compact_runtime *
           "\n\n" * cognitive_state * state_suffix
end


function process_message(ws, raw_msg::String, history::Vector, engine)
    global _current_model, _current_gear, _active_modes

    log_ws_message_in(raw_msg)
    p = JSON.parse(raw_msg)
    if !(p isa AbstractDict) || !haskey(p, "type")
        _ws_send(ws, JSON.json(Dict(
            "type" => "builder_output",
            "output" => "WebSocket message must be a JSON object with a type field.")))
        return
    end

    # --- Forge stream: re-forge edited tool from UI ---
    if get(p, "type", "") == "forge_resubmit"
        name = string(get(p, "name", ""))
        code = string(get(p, "code", ""))
        desc = string(get(p, "description", "Edited via forge stream"))
        if isempty(name) || isempty(code)
            _ws_send(ws, Dict("type"=>"forge_resubmit_result", "error"=>"name and code are required"))
            return
        end
        result = dispatch("forge_new_tool", Dict("name"=>name, "code"=>code, "description"=>desc))
        _ws_send(ws, Dict("type"=>"forge_resubmit_result", "name"=>name, "result"=>result))
        return
    end

    # --- Confirmation response handling ---
    if get(p, "type", "") == "confirm_response"
        cid = get(p, "id", "")
        answer = Bool(p["answer"])
        if haskey(_pending_confirms, cid)
            pending = _pending_confirms[cid]
            delete!(_pending_confirms, cid)
            if answer
                fn = pending["fn"]
                args = pending["args"]
                @info "User confirmed tool $fn"
                _execute_tool_call(ws, engine, fn, args)
            else
                _ws_send(ws, JSON.json(Dict("type"=>"spark","text"=>"✅ Action cancelled by user.")))
            end
        else
            @warn "Confirm response with unknown id $cid"
            _ws_send(ws, JSON.json(Dict("type"=>"spark","text"=>"⚠️ Unknown confirmation ID.")))
        end
        return
    end

    # Model switch: acknowledge the SERVER selection, never just the UI value.
    if p["type"] == "model_change"
        requested = get(p, "model", "")
        old = string(_current_model)
        if !_valid_backend_model(requested)
            _ws_send(ws, Dict("type"=>"backend_error",
                "text"=>"Invalid backend model ID. Selection was not changed.",
                "model"=>old))
            return
        end
        # Main selector is a deliberate "set all model roles" control.
        # Keep component-specific overrides available through Settings afterward.
        roles = ("current_model", "brain_model", "tool_model", "reviewer_model")
        _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
        try
            for role in roles
                _jl.update_config!(role, requested; source="main_ui_model_selector")
            end
        catch e
            _ws_send(ws, Dict("type"=>"backend_error",
                "text"=>"Could not persist all model roles: $(first(sprint(showerror,e),180)). Inspect Settings before retrying.",
                "model"=>old))
            return
        end
        _set_backend_model!(requested)
        log_model_change(old, _current_model)
        log_cognitive_api(_current_model, "switch", "Model changed from $old")
        log_ws_message_out(_backend_state_payload())
        return
    elseif p["type"] == "backend_get"
        _ws_send(ws, _backend_state_payload())
        return
    end

    # --- Stop / abort in‑progress generation ---
    if p["type"] == "stop_generation"
        _generation_abort[] = true
        _ws_send(ws, JSON.json(Dict("type"=>"tool", "text"=>"⊣ Generation stopped.")))
        log_cognitive_thought("Generation aborted by user")
        return
    end

    # --- Session history: list past sessions ---
    if p["type"] == "get_history"
        rows = try
            db = SQLite.DB(_runtime_state_path("sparkbyte_memory.db"; root=root))
            r = DBInterface.execute(db, """
                SELECT session_id, started_at, ended_at, events, notes
                FROM sessions ORDER BY started_at DESC LIMIT 50
            """) |> DataFrame
            [Dict("session_id"=>string(r[i,:session_id]),
                  "started_at"=>string(r[i,:started_at]),
                  "ended_at"=>ismissing(r[i,:ended_at]) ? "" : string(r[i,:ended_at]),
                  "events"=>coalesce(r[i,:events],0),
                  "notes"=>coalesce(r[i,:notes],"")) for i in 1:nrow(r)]
        catch e; Dict{String,Any}[]; end
        _ws_send(ws, JSON.json(Dict("type"=>"history_list", "sessions"=>rows)))
        return
    end

    # --- Session history: load a past session's turns ---
    if p["type"] == "load_session"
        sid = get(p, "session_id", "")
        turns = try
            db = SQLite.DB(_runtime_state_path("sparkbyte_memory.db"; root=root))
            r = DBInterface.execute(db, """
                SELECT timestamp, event, turn_number, model, agent, data_json
                FROM telemetry WHERE session_id=?
                AND event IN ('turn_complete','tool_call','tool_result','ws_in')
                ORDER BY timestamp ASC LIMIT 400
            """, (sid,)) |> DataFrame
            [Dict("ts"=>string(r[i,:timestamp]),
                  "role"=>string(r[i,:event]),
                  "content"=>coalesce(r[i,:data_json],""),
                  "model"=>coalesce(r[i,:model],""),
                  "agent"=>coalesce(r[i,:agent],""),
                  "loop_iter"=>coalesce(r[i,:turn_number],0)) for i in 1:nrow(r)]
        catch e; Dict{String,Any}[]; end
        _ws_send(ws, JSON.json(Dict("type"=>"session_turns", "session_id"=>sid, "turns"=>turns)))
        return
    end

    # --- Explicit operator terminal session ---
    if p["type"] == "terminal_open"
        try
            _webula_terminal_open(ws)
        catch e
            _ws_send(ws,Dict("type"=>"terminal_status","status"=>"error",
                "message"=>sprint(showerror,e)))
        end
        return
    elseif p["type"] == "terminal_input"
        if _WEBULA_TERMINAL[] !== nothing && _WEBULA_TERMINAL_OWNER[] === ws
            _WEBULA_TERMINAL[].write(string(get(p,"data","")))
        end
        return
    elseif p["type"] == "terminal_resize"
        if _WEBULA_TERMINAL[] !== nothing && _WEBULA_TERMINAL_OWNER[] === ws
            rows = clamp(Int(get(p,"rows",24)), 10,100)
            cols = clamp(Int(get(p,"cols",100)), 25,300)
            try _WEBULA_TERMINAL[].setwinsize(rows,cols) catch end
        end
        return
    elseif p["type"] == "terminal_close"
        if _WEBULA_TERMINAL_OWNER[] === ws
            _webula_terminal_close()
        end
        _ws_send(ws,Dict("type"=>"terminal_status","status"=>"closed"))
        return
    end

    # --- Builder panel commands ---
    if p["type"] == "builder_cmd"
        _handle_builder_cmd(ws, p)
        return
    end

    # --- Server relaunch ---
    if p["type"] == "restart_server"
        _ws_send(ws, JSON.json(Dict("type"=>"tool","text"=>"⟳ Relaunching server — reconnect in ~5s…")))
        @async begin
            sleep(1.0)
            # Spawn a fresh server process detached from this one
            sparkbyte_script = joinpath(dirname(dirname(@__DIR__)), "sparkbyte.jl")
            if !isfile(sparkbyte_script)
                sparkbyte_script = joinpath(dirname(@__DIR__), "sparkbyte.jl")
            end
            if isfile(sparkbyte_script)
                project_dir = dirname(sparkbyte_script)
                if Sys.iswindows()
                    # The helper survives this process and waits until its ports and
                    # browser resources have been released before starting Julia.
                    helper = joinpath(project_dir, "scripts", "restart_engine.ps1")
                    isfile(helper) || error("Restart helper is missing: $helper")
                    julia_exe = joinpath(Sys.BINDIR, "julia.exe")
                    cmd = `powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper -PreviousProcessId $(getpid()) -JuliaExe $julia_exe -ProjectDir $project_dir -ScriptPath $sparkbyte_script`
                    log_dir = joinpath(project_dir, "logs")
                    mkpath(log_dir)
                    log_path = joinpath(log_dir, "restart-$(getpid()).log")
                    open(log_path, "a") do io
                        run(pipeline(detach(cmd), stdout=io, stderr=io), wait=false)
                    end
                else
                    run(`$(_julia_command(project_dir)) $sparkbyte_script`, wait=false)
                end
            end
            sleep(0.5)
            exit(0)
        end
        return
    end

    # Agent switch
    if p["type"] == "agent_change"
        name = get(p, "agent", "")
        old  = engine.current_agent_name
        ok   = false
        if !isempty(name)
            ok = Main.JLEngine.set_agent!(engine, name)
        end
        log_agent_change(old, name, ok)
        log_cognitive_thought("Agent switched: $old → $name (ok=$ok)")
        real_name = string(engine.current_agent_name)
        out = ok ?
            Dict("type"=>"agent_changed", "agent"=>real_name,
                 "json_bytes"=>ncodeunits(JSON.json(engine.current_agent_data)),
                 "file"=>something(engine.current_agent_file, "unknown")) :
            Dict("type"=>"tool_error", "text"=>"Agent switch failed: $(name). Still using $(real_name).")
        _ws_send(ws, JSON.json(out)); log_ws_message_out(out)
        return
    end

    # --- Card Cruncher: drag-and-drop character card from browser ---
    if get(p, "type", "") == "card_crunch"
        filename = string(get(p, "filename", "card.png"))
        b64_data = string(get(p, "data", ""))
        if isempty(b64_data)
            _ws_send(ws, JSON.json(Dict("type"=>"tool_error", "text"=>"Card Cruncher: no file data received.")))
            return
        end
        _ws_send(ws, JSON.json(Dict("type"=>"tool", "text"=>"🃏 Card received: $filename — crunching...")))
        tmp_path = joinpath(tempdir(), filename)
        try
            write(tmp_path, base64decode(b64_data))
            root = isempty(_project_root[]) ? pwd() : _project_root[]
            result = dispatch("card_cruncher", Dict("card_path"=>tmp_path, "engine_root"=>root))
            if haskey(result, "error")
                _ws_send(ws, JSON.json(Dict("type"=>"tool_error",
                    "text"=>"🃏 Card Cruncher error: $(result["error"])")))
            else
                pname = get(result, "agent_name", "Unknown")
                _ws_send(ws, JSON.json(Dict("type"=>"spark",
                    "text"=>"🃏 **$(pname)** is ready! Use **/gear $(pname)** to activate her.")))
                # Refresh agent list so new card shows up in the dropdown
                _handle_builder_cmd(ws, Dict("cmd"=>"list_agents"))
            end
        catch e
            bt = sprint(showerror, e, catch_backtrace())
            _ws_send(ws, JSON.json(Dict("type"=>"tool_error", "text"=>"🃏 Card Cruncher crashed: $bt")))
        finally
            isfile(tmp_path) && rm(tmp_path, force=true)
        end
        return
    end

    txt       = get(p, "text",  "")
    img       = get(p, "image", nothing)
    mime      = get(p, "mime",  nothing)
    chat_mode = get(p, "chat_mode", false)  # true = no tools, just talk

    # Slash commands
    if startswith(strip(txt), "/")
        _handle_slash_command(txt, engine; ws=ws)
        return
    end

    turn_start_ms = round(Int, datetime2unix(now()) * 1000)

    # Build user turn
    parts_list = Any[]
    !isempty(txt) && push!(parts_list, Dict("text" => txt))
    img !== nothing && push!(parts_list, Dict("inlineData" => Dict("mimeType"=>mime, "data"=>img)))
    push!(history, Dict("role"=>"user", "parts"=>parts_list))

    # --- JL Engine cognitive snapshot (once per turn) ---
    snapshot = Main.JLEngine.analyze_turn!(engine, txt; agent_name=engine.current_agent_name)
    log_engine_snapshot(snapshot)
    log_cognitive_state(snapshot)  # 🧠 broadcast engine state to terminal

    behavior_state = get(snapshot, "behavior_state", Dict{String,Any}())
    mpf_profile = get(snapshot, "mpf_state_profile", Dict{String,Any}())
    behavior_mode = "#$(get(behavior_state, "number", "?")): $(get(mpf_profile, "label", get(behavior_state, "name", "Unknown")))"

    _current_gear  = snapshot["gait"]
    _active_modes  = [snapshot["rhythm"]["mode"],
                      snapshot["aperture_state"]["mode"],
                      behavior_mode]
    out_ui = Dict("type"=>"ui_update", "gear"=>uppercase(_current_gear), "modes"=>_active_modes)
_ws_send(ws, JSON.json(out_ui)); log_ws_message_out(out_ui)

# 🧠 Fire the thinking bubble IMMEDIATELY so the UI shows a progress indicator
# while the model is reasoning / tools are running. The `thinking_done` event
# later updates the bubble with the final reply. Fixes the "engine frozen" feel.
think_text = "🧠 Reasoning…"
_ws_send(ws, JSON.json(Dict("type"=>"thinking", "text"=>think_text, "delta"=>false)))
    log_ws_message_out(Dict("type"=>"thinking", "text"=>think_text, "delta"=>false))
    _broadcast(Dict(
        "type" => "agent_thought",
        "agent" => string(engine.current_agent_name),
        "text" => think_text,
        "delta" => false,
        "mood" => "focused",
        "gait" => _current_gear,
        "timestamp" => string(Dates.now(Dates.UTC))
    ))



    boot_prompt = Main.JLEngine.get_llm_boot_prompt(engine)
    mpf_directive = string(get(snapshot, "mpf_state_directive", ""))
    cognitive_state = """
--- JL ENGINE COGNITIVE STATE ---
TRIGGER: $(get(snapshot, "trigger", "neutral"))
GAIT: $(_current_gear)
RHYTHM MODE: $(snapshot["rhythm"]["mode"])
EMOTIONAL APERTURE: $(snapshot["aperture_state"]["mode"])
ENGINE BEHAVIOR GRID: #$(get(behavior_state, "number", "?")) [$(get(behavior_state, "id", "?"))] (diagnostic, not a style instruction)
AGENT-AUTHORED STATE: $(get(mpf_profile, "source", "") == "mpf_fallback" ? "not defined" : get(mpf_profile, "label", "unknown"))
DRIFT PRESSURE: $(round(snapshot["drift"]["pressure"]; digits=3))
ADVISORY: $(get(snapshot["advisory"], "msg", "None"))
"""
    # Full agent JSON MUST initialize before smaller runtime snippets.
    # Never prepend the giant generic self-context block: it can compete with
    # the active agent's own identity. The separate core runtime still has it.
    sys_prompt = _compose_authoritative_agent_prompt(
        engine, boot_prompt, cognitive_state, mpf_directive)

    # ── Provider profiles ───────────────────────────────────────────────────
    # Single source of truth for every provider's capabilities and wire‑up.
    # Add a new provider here — nowhere else.
    PROVIDER_PROFILES = Dict{String,Dict{String,Any}}(
        "openrouter" => Dict(
            "endpoint"        => "https://openrouter.ai/api/v1/chat/completions",
            "env_key"         => "OPENROUTER_API_KEY",
            "supports_tools"  => true,
            "supports_top_p"  => true,
            "supports_vision" => true,
            "schema_format"   => "openai",
            "uses_gemini_api" => false,
        ),
        "ollama" => Dict(
            "endpoint"        => _ollama_openai_endpoint(),
            "env_key"         => "",                          # no key needed
            "supports_tools"  => true,
            "supports_top_p"  => true,
            "supports_vision" => false,
            "schema_format"   => "openai",
            "uses_gemini_api" => false,
        ),
    )

    # ── Model → provider routing ──────────────────────────────────────────────
    # Freeze the selected model for the whole turn. Changing the dropdown
    # during a request must NOT silently change its route in mid-flight.
    turn_model = string(_current_model)
    provider = _backend_provider_for(turn_model)
    pp = PROVIDER_PROFILES[provider]

    # ── Params ───────────────────────────────────────────────────────────────
    state_sampling = get(snapshot, "mpf_sampling_bias", Dict{String,Any}())
    temp  = clamp(get(snapshot["aperture_state"],"temp",0.45) +
                  get(snapshot["drift"],"temperature_delta",0.0) +
                  get(state_sampling,"temperature",0.0), 0.1, 1.5)
    top_p = clamp(get(snapshot["aperture_state"],"top_p",0.7) +
                  get(state_sampling,"top_p",0.0), 0.1, 1.0)

    # Gemini-specific generation config
    safety = [Dict("category"=>"HARM_CATEGORY_$c", "threshold"=>"BLOCK_NONE")
              for c in ["HATE_SPEECH","HARASSMENT","DANGEROUS_CONTENT","SEXUALLY_EXPLICIT","CIVIC_INTEGRITY"]]
    gen_config = Dict{String,Any}("temperature"=>temp, "topP"=>top_p)
    # thinking_config only on models that actually support it (2.5+, 3.x) — never Gemma or 2.0
    _supports_thinking = !(_current_model in _GEMMA_MODELS) && (
        occursin("2.5", _current_model) ||
        occursin("thinking", lowercase(_current_model)) ||
        match(r"gemini-3", _current_model) !== nothing
    )
    if _supports_thinking
        _is_flash_lite = occursin("flash-lite", lowercase(_current_model))
        _is_flash      = occursin("flash", lowercase(_current_model)) && !_is_flash_lite
        if _is_flash_lite
            gen_config["thinking_config"] = Dict("thinking_level"=>"LOW")
        elseif _is_flash
            gen_config["thinking_config"] = Dict("thinking_level"=>"MEDIUM")
        else
            gen_config["thinking_config"] = Dict("thinking_level"=>"HIGH")
        end
    end
    # Gemma → force chat mode (no tools)
    if _current_model in _GEMMA_MODELS || !_model_supports_tools(_current_model)
        chat_mode = true
    end

    log_system_prompt(sys_prompt, snapshot)
    log_param_decision(gen_config, snapshot)

    # ── Schema normalizer ─────────────────────────────────────────────────────
    # Gemini uses UPPERCASE JSON schema types (STRING, OBJECT, ARRAY…)
    # OAI providers require lowercase (string, object, array…)
    # This runs recursively so forged tools get the same treatment.
    function _normalize_schema(v::AbstractDict)
        # Guard against runaway/cyclic schemas (e.g. a forged tool whose
        # `parameters` is self-referential or pathologically deep). Without
        # this floor the recursion blows the Julia stack at turn start —
        # before the agentic loop's try/catch — and poisons every turn.
        out = Dict{String,Any}()
        obj_schema = false
        for (k, val) in v
            if k == "type" && val isa String
                lowered = lowercase(val)
                out[k] = lowered
                obj_schema = lowered == "object"
            else
                out[k] = val
            end
        end
        if obj_schema
            props = get(out, "properties", Dict{String,Any}())
            normalized_props = Dict{String,Any}()
            if props isa AbstractDict
                for (pk, pv) in pairs(props)
                    if pv isa AbstractDict
                        prop = Dict{String,Any}(string(k) => v for (k, v) in pairs(pv))
                        haskey(prop, "type") && prop["type"] isa String && (prop["type"] = lowercase(prop["type"]))
                        normalized_props[string(pk)] = prop
                    else
                        normalized_props[string(pk)] = pv isa Bool ? pv : Dict{String,Any}("type"=>"string", "description"=>string(pv))
                    end
                end
            end
            out["properties"] = normalized_props
            req = get(out, "required", Any[])
            out["required"] = req isa AbstractVector ? [string(r) for r in req if haskey(normalized_props, string(r))] : Any[]
        end
        out
    end
    _normalize_schema(v) = v   # passthrough for non-Dict

    function _tool_parameters_schema(d)
        params = _normalize_schema(get(d, "parameters", Dict{String,Any}()))
        if !(params isa AbstractDict)
            params = Dict{String,Any}()
        end
        params = Dict{String,Any}(string(k) => v for (k, v) in pairs(params))
        params["type"] = lowercase(string(get(params, "type", "object")))
        params["type"] != "object" && (params["type"] = "object")
        props = get(params, "properties", Dict{String,Any}())
        params["properties"] = props isa AbstractDict ? Dict{String,Any}(string(k) => v for (k, v) in pairs(props)) : Dict{String,Any}()
        req = get(params, "required", Any[])
        params["required"] = req isa AbstractVector ? [string(r) for r in req if haskey(params["properties"], string(r))] : Any[]
        return params
    end

    # Build tool schemas in the format the current provider needs
    all_decls_raw = vcat(TOOLS_SCHEMA[1]["function_declarations"], DYNAMIC_SCHEMA)
    oai_tools = (!chat_mode && pp["supports_tools"]) ?
        [Dict("type"=>"function",
              "function"=>Dict(
                  "name"        => d["name"],
                  "description" => get(d, "description", ""),
                  "parameters"  => _tool_parameters_schema(d)))
         for d in all_decls_raw] :
        Any[]

    # --- Agentic tool loop ---
    final_reply = ""
    reasoning_accum = ""
    loop_iter   = 0
    prior_history = isempty(history) ? Any[] : history[1:end-1]
    max_tool_loops = try parse(Int, get(ENV, "BYTE_MAX_TOOL_LOOPS", "20")) catch; 20 end
    max_repeat_tool_calls = 4
    max_calls_per_tool = try parse(Int, get(ENV, "BYTE_MAX_CALLS_PER_TOOL", "25")) catch; 25 end
    tool_name_counts = Dict{String, Int}()
    seen_call_signatures = Dict{String, Int}()
    tool_guard_hit = false
    last_tool_signature = ""
    same_tool_streak = 0
    last_tool_name_used = ""
    last_tool_elapsed_used = 0

    function _stable_tool_repr(v)
        if v isa AbstractDict
            items = sort(collect(pairs(v)); by = kv -> string(first(kv)))
            return "{" * join(["$(string(k)):$(_stable_tool_repr(val))" for (k, val) in items], ",") * "}"
        elseif v isa AbstractVector
            return "[" * join([_stable_tool_repr(x) for x in v], ",") * "]"
        end
        return string(v)
    end

    function _trip_tool_guard(reason::AbstractString)
        tool_guard_hit && return
        tool_guard_hit = true
        guard_text = "⚠️ Tool loop guard tripped: $(reason). I stopped the tool spam instead of hanging the UI."
        final_reply = guard_text
        push!(history, Dict("role"=>"model","parts"=>[Dict("text"=>guard_text)]))
        out_guard = Dict("type"=>"spark", "text"=>guard_text)
        _ws_send(ws, JSON.json(out_guard)); log_ws_message_out(out_guard)
        log_cognitive_thought("⚠️ Tool loop guard tripped: $reason")
        log_event("tool_loop_guard", Dict{String,Any}(
            "reason" => string(reason),
            "loop_iter" => Int(loop_iter),
            "model" => string(_current_model),
            "agent" => string(engine.current_agent_name),
        ))
    end

    function _allow_tool_call(name::AbstractString, args)
        sig = string(name) * ":" * _stable_tool_repr(args)
        if sig == last_tool_signature
            same_tool_streak += 1
        else
            last_tool_signature = sig
            same_tool_streak = 1
        end
        if same_tool_streak >= max_repeat_tool_calls
            _trip_tool_guard("repeated `$name` call $(same_tool_streak)x consecutively")
            return false
        end
        return true
    end

    # OAI path: build oai_messages ONCE here and append to it each iteration.
    # Never rebuild from history mid‑loop — that loses real tool_call_ids from
    # OAI responses and breaks the tool roundtrip on iteration 2+.
    oai_messages = Any[Dict("role"=>"system","content"=>sys_prompt)]
    if provider != "gemini" && provider != "xai_responses"
        for h in prior_history
            role = get(h,"role","user") == "model" ? "assistant" : get(h,"role","user")
            if role == "function"
                for part in get(h,"parts",[])
                    fr = get(part,"functionResponse",nothing)
                    fr === nothing && continue
                    # Prior‑turn tool results use name as id — fine for history seeding,
                    # only current‑turn ids need to be exact (handled in‑loop below)
                    push!(oai_messages, Dict("role"=>"tool",
                        "tool_call_id"=>get(fr,"name","unknown"),
                        "content"=>JSON.json(get(fr,"response",Dict()))))
                end
            else
                content_blocks = Any[]
                for part in get(h,"parts",[])
                    get(part,"thought",false) && continue
                    if haskey(part,"text") && !isempty(part["text"])
                        push!(content_blocks, Dict("type"=>"text","text"=>part["text"]))
                    elseif haskey(part,"inlineData")
                        id2 = part["inlineData"]
                        push!(content_blocks, Dict("type"=>"image_url",
                            "image_url"=>Dict("url"=>"data:$(id2["mimeType"]);base64,$(id2["data"])")))
                    end
                end
                isempty(content_blocks) && continue
                has_img = any(b->get(b,"type","")=="image_url", content_blocks)
                msg_content = has_img ? content_blocks :
                    join([b["text"] for b in content_blocks if get(b,"type","")=="text"], "\n")
                push!(oai_messages, Dict("role"=>role,"content"=>msg_content))
            end
        end
        # Append the current user turn (with optional image)
        cur_blocks = Any[Dict("type"=>"text","text"=>txt)]
        if img !== nothing
            push!(cur_blocks, Dict("type"=>"image_url",
                "image_url"=>Dict("url"=>"data:$(mime);base64,$(img)")))
        end
        has_cur_img = img !== nothing
        push!(oai_messages, Dict("role"=>"user",
            "content"=> has_cur_img ? cur_blocks : txt))
    end

    while true
        if _generation_abort[]
            _generation_abort[] = false
            _ws_send(ws, JSON.json(Dict("type"=>"spark", "text"=>"\n\n⊣ *Aborted.*")))
            break
        end
        loop_iter += 1
        if loop_iter > max_tool_loops + 1
            _trip_tool_guard("exceeded $(max_tool_loops) tool/API loops")
            break
        end
        log_api_request(_current_model, gen_config, length(history), loop_iter)
        log_cognitive_api(_current_model, "request", "Loop iteration $loop_iter")
        try
        # ── OAI‑compatible path (OpenRouter, Ollama) ──────────
        # All config comes from the provider profile — no scattered if/else here.
        # oai_messages was built once before the loop and is appended to in‑place —
        # tool_call_ids from OAI responses are preserved exactly across iterations.
        api_url = pp["endpoint"]
        env_key = pp["env_key"]
        api_key = isempty(env_key) ? "ollama" : get(ENV, env_key, "")
        if isempty(api_key)
            wrn = "🔑 **Missing API Key**\n\n" *
                  "The **$provider** backend needs an API key to work.\n\n" *
                  "**Set it directly in chat right now:**\n" *
                  "```\n/openrouter your-api-key-here\n```\n" *
                  "Or open **⚙ Settings** (Ctrl+,) to paste and save your key.\n\n" *
                  "Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys)."
            _ws_send(ws, JSON.json(Dict("type"=>"spark","text"=>wrn)))
            log_cognitive_api(_current_model, "error", "API key missing: $env_key")
            @warn "API key missing for provider" provider env_key
            break
        end

        actual_model = provider == "ollama" ? replace(turn_model, "ollama:"=>"") : turn_model

        # Build payload from profile — profile is the single source of truth
        payload = Dict{String,Any}("model"=>actual_model, "messages"=>oai_messages,
                                   "temperature"=>temp)
        pp["supports_top_p"] && (payload["top_p"] = top_p)
        force_synthesis = (loop_iter >= max_tool_loops)
        if !chat_mode && pp["supports_tools"] && !force_synthesis
            payload["tools"]       = oai_tools
            payload["tool_choice"] = "auto"
        end

        headers = ["Content-Type"=>"application/json", "Authorization"=>"Bearer $api_key"]
        api_timeout_s = try parse(Int, get(ENV, "BYTE_API_TIMEOUT_S", "120")) catch; 120 end
        _backend_last_request_model[] = turn_model
        _backend_last_request_provider[] = provider
        _backend_last_request_status[] = "sent"
        _broadcast(_backend_state_payload())
        wire_body = JSON.json(payload)
        audit_tag = audit_api_request(turn_model, provider, api_url, wire_body)
        resp = try
            HTTP.post(api_url, headers, wire_body; readtimeout=api_timeout_s)
        catch transport_error
            audit_api_error(audit_tag, transport_error)
            rethrow()
        end
        raw_response = String(resp.body)
        audit_api_response(audit_tag, Int(resp.status), raw_response)
        data = JSON.parse(raw_response)

        # 🎫 Token accounting — fold this call's usage into the session counter
        _record_token_usage(get(data, "usage", nothing), loop_iter)

        if !haskey(data,"choices") || isempty(data["choices"])
            provider_error = get(data, "error", Dict{String,Any}())
            error_code = provider_error isa AbstractDict ? string(get(provider_error, "code", "unknown")) : "unknown"
            error_message = provider_error isa AbstractDict ? string(get(provider_error, "message", provider_error)) : string(provider_error)
            err_msg = if error_code == "provider_unavailable"
                "ERROR: OpenRouter provider unavailable for model $actual_model. $error_message Try a different model or retry later."
            else
                "ERROR: No response from $provider for model $actual_model. $error_message"
            end
            _backend_last_request_status[] = "failed"
            _broadcast(_backend_state_payload())
            _ws_send(ws, JSON.json(Dict("type"=>"spark","text"=>err_msg)))
            log_api_response(turn_model, resp.status, ncodeunits(raw_response), loop_iter; error=err_msg)
            log_cognitive_api(_current_model, "error", err_msg)
            break
        end

        _backend_last_response_model[] = turn_model
        _backend_last_reported_model[] = string(something(get(data, "model", nothing), ""))
        _backend_last_response_provider[] = provider
        _backend_last_response_status[] = "confirmed"
        _backend_last_request_status[] = "responded"
        _broadcast(_backend_state_payload())
        msg           = data["choices"][1]["message"]
        finish_reason = get(data["choices"][1],"finish_reason","unknown")
        has_tool      = false

        # 🧠 Capture reasoning content exposed by reasoning-capable models
        chunk_reason = ""
        if haskey(msg, "reasoning_content") && !isnothing(msg["reasoning_content"])
            chunk_reason = string(msg["reasoning_content"])
        elseif haskey(msg, "reasoning") && !isnothing(msg["reasoning"])
            rt = msg["reasoning"]
            if rt isa AbstractString
                chunk_reason = rt
            elseif rt isa AbstractDict && haskey(rt, "text")
                chunk_reason = string(rt["text"])
            else
                chunk_reason = JSON.json(rt)
            end
        end
        if !isempty(strip(chunk_reason))
            reasoning_accum *= chunk_reason
            _ws_send(ws, JSON.json(Dict("type"=>"thinking", "text"=>chunk_reason, "delta"=>true)))
            log_cognitive_thought("🧠 Reasoning chunk: $(length(chunk_reason)) chars")
            _db_write_reasoning("api_loop:iter_$loop_iter", String(chunk_reason), turn_model, string(engine.current_agent_name))
        end

        if haskey(msg,"tool_calls") && !isnothing(msg["tool_calls"]) && !isempty(msg["tool_calls"])
            has_tool = true
            # Push the full assistant message (with its tool_calls array) into oai_messages.
            # The exact ids from this message will be echoed back in the tool result messages below —
            # that's what makes the roundtrip work on iteration 2+.
            push!(oai_messages, msg)

            for tc in msg["tool_calls"]
                fn      = tc["function"]
                tc_id   = get(tc,"id","call_$(fn["name"])")   # exact id from OAI response
                tc_name = fn["name"]
                raw_args = get(fn, "arguments", "{}")
                tc_args = if raw_args isa AbstractDict
                    raw_args
                elseif raw_args isa AbstractString
                    try JSON.parse(raw_args) catch; Dict() end
                else
                    Dict()
                end
                sig = string(tc_name) * ":" * _stable_tool_repr(tc_args)
                sig_count = get(seen_call_signatures, sig, 0) + 1
                seen_call_signatures[sig] = sig_count

                name_count = get(tool_name_counts, tc_name, 0) + 1
                tool_name_counts[tc_name] = name_count

                if sig_count > 2
                    println("⚠️ BYTE tool duplicate rejected: $tc_name")
                    res = Dict("error" => "Duplicate call: tool '$tc_name' was already executed with identical arguments this turn. Synthesize using prior results instead of repeating.")
                    push!(oai_messages, Dict("role"=>"tool","tool_call_id"=>tc_id,"content"=>JSON.json(res)))
                    continue
                end

                tool_limit = tc_name in ["probe_workspace"] ? 2 : max_calls_per_tool
                if name_count > tool_limit
                    println("⚠️ BYTE tool limit reached for: $tc_name ($name_count > $tool_limit)")
                    res = Dict("error" => "Tool '$tc_name' reached maximum calls ($tool_limit) for this turn. Do not call '$tc_name' again. Use other tools or answer the user.")
                    push!(oai_messages, Dict("role"=>"tool","tool_call_id"=>tc_id,"content"=>JSON.json(res)))
                    continue
                end

                if !_allow_tool_call(tc_name, tc_args)
                    has_tool = false
                    break
                end
                println("⚡ BYTE tool ($provider): $tc_name")
                log_cognitive_tool(tc_name, "called", "Model requested tool_$(tc_name)")
                # Confirmation step
                if REQUIRE_CONFIRM[]
                    cid = string(uuid4())
                    _pending_confirms[cid] = Dict("fn"=>tc_name, "args"=>tc_args)
                    _ws_send(ws, JSON.json(Dict("type"=>"confirm","id"=>cid,
                        "text"=>"⚠️ Run tool **$tc_name** with args $(JSON.json(tc_args))?")))
                    continue
                end
                res, elapsed = _execute_tool_call(ws, engine, tc_name, tc_args; loop_iter=loop_iter)
                last_tool_name_used = tc_name; last_tool_elapsed_used = elapsed
                # Append tool result with the EXACT same tc_id — this is the roundtrip
                push!(oai_messages, Dict("role"=>"tool","tool_call_id"=>tc_id,"content"=>JSON.json(res)))
            end
        elseif haskey(msg,"content") && !isnothing(msg["content"])
            reply_txt = string(msg["content"])
            final_reply *= reply_txt
            push!(history, Dict("role"=>"model","parts"=>[Dict("text"=>reply_txt)]))
            out = Dict("type"=>"spark","text"=>reply_txt)
            _ws_send(ws, JSON.json(out)); log_ws_message_out(out)
            log_cognitive_thought("Generated response ($(length(reply_txt)) chars)")
            log_api_response(_current_model, resp.status, ncodeunits(raw_response), loop_iter;
                has_text=true, text_preview=reply_txt, finish_reason=finish_reason)
        else
            err_msg = "ERROR: Empty response from $provider for model $(_current_model) (finish_reason=$(finish_reason)). Try a different model."
            _ws_send(ws, JSON.json(Dict("type"=>"spark","text"=>err_msg)))
            log_api_response(_current_model, resp.status, ncodeunits(raw_response), loop_iter; error=err_msg, finish_reason=finish_reason)
            log_cognitive_api(_current_model, "error", err_msg)
        end

        !has_tool && break

        catch e
            _backend_last_request_status[] = "failed"
            _broadcast(_backend_state_payload())
            bt  = sprint(showerror, e, catch_backtrace())
            status_body = if e isa HTTP.Exceptions.StatusError
                try
                    body = e.response.body
                    body isa AbstractVector{UInt8} ? String(body) : string(body)
                catch
                    string(e)
                end
            else
                ""
            end
            # Categorize the error for user-friendly messaging
            user_msg = if e isa HTTP.Exceptions.StatusError
                "🚫 **API Error (HTTP $(e.status))**\n\n" *
                "The $provider server returned an error.\n\n" *
                "**Check:**\n- Is your API key correct?\n- Is the model name valid?\n- Do you have credits/quota?\n\n" *
                "Details: $(first(_redact_sensitive_text(status_body), 500))"
            elseif e isa Base.IOError || occursin(r"timeout|timed out", lowercase(string(e)))
                "⏱️ **Connection Timeout**\n\n" *
                "Could not reach the $provider API server in time.\n\n" *
                "**Try:**\n- Check your internet connection\n- Try a different provider\n- Increase `BYTE_API_TIMEOUT_S` env var"
            elseif occursin(r"reset|refused|unreachable", string(e))
                "🔌 **Connection Failed**\n\n" *
                "Could not connect to the $provider API endpoint.\n\n" *
                "**Check:**\n- Is the endpoint URL correct?\n- Is your internet working?\n- Is the provider's service running?"
            else
                "❌ **API Error**\n\n" *
                "$(first(_redact_sensitive_text(e), 200))"
            end
            out = Dict("type"=>"spark", "text"=>user_msg)
            _ws_send(ws, JSON.json(out)); log_ws_message_out(out)
            log_error("api_loop:iter_$loop_iter", e; stacktrace_str=bt)
            log_cognitive_api(_current_model, "error", "$(string(typeof(e))): $(first(string(e), 120))")
            break
        end
    end

    # 🧠 Finalize the thinking bubble.
    # - If the model exposed reasoning, the UI shows the full trace.
    # - If not, the UI shows a "no reasoning exposed" note.
    # - The actual response was the `spark` event sent earlier — we no longer
    #   put the reply text inside the thinking bubble.
    done_payload = if !isempty(reasoning_accum)
        Dict("type"=>"thinking_done", "text"=>reasoning_accum,
             "chars"=>length(reasoning_accum), "has_reasoning"=>true)
    else
        Dict("type"=>"thinking_done", "text"=>"", "chars"=>0, "has_reasoning"=>false)
    end
    _ws_send(ws, JSON.json(done_payload))
    log_ws_message_out(done_payload)

# Feed output back to engine memory + log turn complete.
# Persist the turn ALWAYS — even an aborted/empty reply must not erase the user's
# message from the conversation record (it rehydrates after a restart).
    isempty(final_reply) || Main.JLEngine.record_turn!(engine, txt, final_reply; snapshot=snapshot)
    _persist_conversation_turn!(txt, final_reply, snapshot)
    elapsed_total = round(Int, datetime2unix(now()) * 1000) - turn_start_ms
    log_turn_complete(txt, length(final_reply), loop_iter, elapsed_total)
    _db_write_turn_snapshot(
        snapshot,
        string(engine.current_agent_name),
        string(_current_model),
            _session_id[],
        _turn_counter[],
        length(txt),
        length(final_reply),
        elapsed_total,
    )

    # Telemetry broadcast — drives the live panel in the UI
    try
        drift_p = round(get(get(snapshot, "drift", Dict{String,Any}()), "pressure", 0.0); digits=3)
        telem = Dict{String,Any}(
            "type"            => "telemetry_update",
            "gait"            => string(get(snapshot, "gait", _current_gear)),
            "rhythm_mode"     => string(get(get(snapshot,"rhythm",Dict{String,Any}()),"mode","—")),
            "aperture_mode"   => string(get(get(snapshot,"aperture_state",Dict{String,Any}()),"mode","—")),
            "behavior_state"  => behavior_mode,
            "behavior_diagnostic" => string(get(get(snapshot,"behavior_state",Dict{String,Any}()),"name","—")),
            "behavior_number" => get(get(snapshot,"behavior_state",Dict{String,Any}()),"number",0),
            "behavior_intensity" => round(get(snapshot, "behavior_intensity", 0.0); digits=3),
            "mpf_state"       => string(get(get(snapshot,"mpf_state_profile",Dict{String,Any}()),"label","—")),
            "drift_pressure"  => drift_p,
            "stability_score" => round(engine.stability_score; digits=3),
            "loop_count"      => Int(loop_iter),
            "last_tool"       => last_tool_name_used,
            "last_tool_ms"    => last_tool_elapsed_used,
            "agent"         => string(engine.current_agent_name),
            "model"           => string(_current_model),
            "elapsed_ms"      => elapsed_total,
        )
        _ws_send(ws, JSON.json(telem))
    catch e
        @warn "Telemetry update push failed" exception=(e, catch_backtrace())
    end

    # Live memory: write thought diary entry to SQLite + flush session event count
    @async try
        behavior   = get(snapshot, "behavior_state", Dict())
        mpf_profile = get(snapshot, "mpf_state_profile", Dict())
        tone       = string(get(behavior, "tone_bias", "adaptable"))
        bname      = string(get(mpf_profile, "label", get(behavior, "name", "Unknown")))
        cell       = get(behavior, "number", 0)
        mood       = replace(lowercase(bname), r"[^a-z/]" => "-")
        gait       = string(get(snapshot, "gait", "walk"))
        agent    = string(engine.current_agent_name)
        thought    = "Responded to: \"$(first(txt, 120))\". " *
                     "Reply ($(length(final_reply)) chars): $(first(final_reply, 220)). " *
                     "Cell: #$cell ($bname). Tone: $tone. Loops: $loop_iter. Elapsed: $(elapsed_total)ms."
        _db_write_thought(first(txt, 80), thought, mood, gait, agent)
        @info "💭 Thoughts: " thought
        # Flush live event count to sessions table — survives force kills
        db = _state[:db]
        db !== nothing && SQLite.execute(db,
            "UPDATE sessions SET events=? WHERE session_id=? AND ended_at IS NULL",
            (_session_event_count[], _session_id[]))
    catch e
        @warn "Failed to persist live thought snapshot" exception=(e, catch_backtrace())
    end
end

"""
    launch(port=8081)

Open Chrome pointed at the app. Falls back to system default browser.
"""
function launch(port::Int=8081)
    url = "http://localhost:$port"
    cmd = if Sys.iswindows()
        chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        isfile(chrome) ? `cmd /c start "" "$chrome" --app=$url` : `cmd /c start $url`
    elseif Sys.isapple()
        `open $url`
    else
        launcher = Sys.which("xdg-open")
        if launcher !== nothing
            `$launcher $url`
        else
            launcher = Sys.which("gio")
            launcher === nothing ? nothing : `$launcher open $url`
        end
    end
    cmd === nothing && return println("⚠️ No browser launcher found. Open $url manually.")
    run(cmd)
end

# ── Headless Control API Route Handlers (Feature F16) ─────────────────────────

function _handle_control_state_request(stream, engine, host::String, port::Int, boot_time::Float64)
    # Must report the same effective route used by chat, not a stale global
    # registry that never follows the active model dropdown.
    active_prov = _backend_provider_for(_current_model)

    loaded_tools = length(TOOL_MAP)

    db = _state[:db]
    mem_count = 0
    if db !== nothing
        try
            row = DBInterface.execute(db, "SELECT COUNT(*) AS c FROM memory") |> DataFrame
            mem_count = Int(row[1, :c])
        catch err
            @warn "Failed to query memory count from SQLite" exception=err
        end
    end

    ws_count = lock(_WS_CLIENTS_LOCK) do
        length(_WS_CLIENTS)
    end

    agent_name = if engine !== nothing && hasfield(typeof(engine), :current_agent_name)
        string(engine.current_agent_name)
    else
        "SparkByte"
    end

    uptime_s = round(time() - boot_time; digits=2)

    payload = Dict{String, Any}(
        "ok" => true,
        "service" => "sparkbyte-omni",
        "port" => port,
        "active_provider" => active_prov,
        "current_model" => _current_model,
        "backend_verification" => _backend_state_payload(),
        "loaded_tools_count" => loaded_tools,
        "memory_items_count" => mem_count,
        "connected_clients_count" => ws_count,
        "uptime" => uptime_s,
        "active_agent" => agent_name,
        "gear" => _current_gear,
        "modes" => _active_modes,
        "tokens" => _tokens_snapshot(),
        "timestamp" => string(Dates.now(Dates.UTC))
    )

    _http_json_response(stream, 200, payload)
    return
end

function _handle_control_tools_request(stream)
    db = _state[:db]
    tool_stats = Dict{String, Tuple{Int, String}}()
    if db !== nothing
        try
            rows = DBInterface.execute(db, "SELECT name, call_count, COALESCE(last_used, '') AS lu FROM tools") |> DataFrame
            for r in eachrow(rows)
                tool_stats[String(r[:name])] = (Int(r[:call_count]), String(r[:lu]))
            end
        catch err
            @warn "Failed to query tools table for usage statistics" exception=err
        end
    end

    tools_catalog = Dict{String, Dict{String, Any}}()

    # 1. Built-in tools from schema
    if !isempty(TOOLS_SCHEMA) && haskey(TOOLS_SCHEMA[1], "function_declarations")
        for decl in TOOLS_SCHEMA[1]["function_declarations"]
            tname = string(decl["name"])
            stats = get(tool_stats, tname, (0, ""))
            tools_catalog[tname] = Dict{String, Any}(
                "name" => tname,
                "category" => "builtin",
                "description" => get(decl, "description", ""),
                "parameters" => get(decl, "parameters", Dict{String, Any}()),
                "is_dynamic" => false,
                "call_count" => stats[1],
                "last_used" => stats[2]
            )
        end
    end

    # 2. Dynamic tools
    for dyn in DYNAMIC_SCHEMA
        tname = string(dyn["name"])
        stats = get(tool_stats, tname, (0, ""))
        tools_catalog[tname] = Dict{String, Any}(
            "name" => tname,
            "category" => "dynamic",
            "description" => get(dyn, "description", ""),
            "parameters" => get(dyn, "parameters", Dict{String, Any}()),
            "is_dynamic" => true,
            "call_count" => stats[1],
            "last_used" => stats[2]
        )
    end

    # 3. Any additional tools present in TOOL_MAP
    for tname in keys(TOOL_MAP)
        if !haskey(tools_catalog, tname)
            stats = get(tool_stats, tname, (0, ""))
            tools_catalog[tname] = Dict{String, Any}(
                "name" => tname,
                "category" => "builtin",
                "description" => "Host-native Julia tool function `tool_$(tname)`",
                "parameters" => Dict{String, Any}("type"=>"object", "properties"=>Dict{String, Any}()),
                "is_dynamic" => false,
                "call_count" => stats[1],
                "last_used" => stats[2]
            )
        end
    end

    all_tools = collect(values(tools_catalog))
    sort!(all_tools; by = t -> t["name"])
    builtin_count = count(t -> !t["is_dynamic"], all_tools)
    dynamic_count = count(t -> t["is_dynamic"], all_tools)

    _http_json_response(stream, 200, Dict{String, Any}(
        "ok" => true,
        "total_tools" => length(all_tools),
        "builtin_count" => builtin_count,
        "dynamic_count" => dynamic_count,
        "tools" => all_tools
    ))
    return
end

function _handle_control_dispatch_request(stream, engine)
    body_bytes = try
        read(stream)
    catch err
        @warn "Failed to read dispatch request body" exception=err
        UInt8[]
    end
    body_str = String(body_bytes)
    payload = try
        JSON.parse(body_str)
    catch err
        @warn "Failed to parse dispatch JSON" exception=err
        return _http_json_response(stream, 400,
            Dict("ok"=>false, "error"=>"Request body must be valid JSON"))
    end

    payload isa AbstractDict || return _http_json_response(stream, 400,
        Dict("ok"=>false, "error"=>"Request body must be a JSON object"))

    raw_task = get(payload, "task", "")
    raw_task isa AbstractString || return _http_json_response(stream, 400,
        Dict("ok"=>false, "error"=>"Field 'task' must be a string"))
    task_desc = strip(raw_task)
    if isempty(task_desc)
        return _http_json_response(stream, 400, Dict("ok"=>false, "error"=>"Field 'task' is required and cannot be empty"))
    end

    default_agent = (engine !== nothing && hasfield(typeof(engine), :current_agent_name)) ?
        string(engine.current_agent_name) : "SparkByte"
    raw_agent = get(payload, "agent", default_agent)
    raw_agent isa AbstractString || return _http_json_response(stream, 400,
        Dict("ok"=>false, "error"=>"Field 'agent' must be a non-empty string"))
    agent_name = String(strip(raw_agent))
    isempty(agent_name) && return _http_json_response(stream, 400,
        Dict("ok"=>false, "error"=>"Field 'agent' must be a non-empty string"))
    if engine !== nothing && hasfield(typeof(engine), :mpf_profiles) &&
       !haskey(engine.mpf_profiles, agent_name)
        return _http_json_response(stream, 400,
            Dict("ok"=>false, "error"=>"Unknown agent: $agent_name"))
    end

    raw_timeout = get(payload, "timeout_s", 120)
    (raw_timeout isa Real && !(raw_timeout isa Bool)) ||
        return _http_json_response(stream, 400,
            Dict("ok"=>false, "error"=>"Field 'timeout_s' must be a finite positive number"))
    timeout_s = try
        Float64(raw_timeout)
    catch
        NaN
    end
    (isfinite(timeout_s) && timeout_s > 0) || return _http_json_response(stream, 400,
        Dict("ok"=>false, "error"=>"Field 'timeout_s' must be a finite positive number"))

    task_id = string(UUIDs.uuid4())
    cancel_ref = Ref(false)
    t_start = time()

    # Broadcast thought
    _broadcast(Dict(
        "type" => "agent_thought",
        "agent" => agent_name,
        "text" => "Dispatched headless task [$task_id]: $task_desc",
        "delta" => false,
        "mood" => "focused",
        "gait" => _current_gear,
        "timestamp" => string(Dates.now(Dates.UTC))
    ))

    tools_called = Any[]
    dispatch_result = Ref{Any}("")
    dispatch_error = Ref{Union{Nothing, String}}(nothing)

    runner_task = @async begin
        try
            snapshot = Dict{String, Any}()
            if engine !== nothing && isdefined(Main, :JLEngine) && isdefined(Main.JLEngine, :analyze_turn!)
                try
                    snapshot = Main.JLEngine.analyze_turn!(engine, task_desc; agent_name=agent_name)
                    log_cognitive_state(snapshot)
                catch err
                    @warn "Cognitive analysis error in dispatch" exception=err
                end
            end

            if cancel_ref[]
                return
            end

            # Check if direct tool execution
            executed_direct = false
            for t_candidate in keys(TOOL_MAP)
                if startswith(lowercase(task_desc), lowercase(t_candidate)) || occursin("run tool $t_candidate", lowercase(task_desc))
                    executed_direct = true
                    t0 = time()
                    _broadcast(Dict(
                        "type" => "tool_call",
                        "call_id" => "call_$(task_id[1:8])",
                        "tool" => t_candidate,
                        "agent" => agent_name,
                        "arguments" => Dict("input" => task_desc),
                        "timestamp" => string(Dates.now(Dates.UTC))
                    ))

                    res = try
                        dispatch(t_candidate, Dict("input" => task_desc); agent=agent_name)
                    catch tool_err
                        Dict("error" => string(tool_err))
                    end
                    elapsed_ms = round(Int, (time() - t0) * 1000)

                    _broadcast(Dict(
                        "type" => "tool_result",
                        "call_id" => "call_$(task_id[1:8])",
                        "tool" => t_candidate,
                        "agent" => agent_name,
                        "status" => (res isa AbstractDict && haskey(res, "error")) ? "error" : "success",
                        "preview" => "Tool $t_candidate completed in $(elapsed_ms)ms",
                        "result" => res isa AbstractDict ? res : Dict("result" => string(res)),
                        "elapsed_ms" => elapsed_ms,
                        "timestamp" => string(Dates.now(Dates.UTC))
                    ))

                    push!(tools_called, Dict(
                        "tool" => t_candidate,
                        "status" => (res isa AbstractDict && haskey(res, "error")) ? "error" : "success",
                        "elapsed_ms" => elapsed_ms,
                        "result" => res
                    ))
                    if res isa AbstractDict && haskey(res, "error")
                        dispatch_error[] = string(res["error"])
                    else
                        dispatch_result[] = "Executed local tool '$t_candidate' successfully."
                    end
                    break
                end
            end

            if !executed_direct
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                backend = try _jl.get_backend() catch err; nothing end
                if backend !== nothing && isdefined(_jl, :NoopBackend) && backend isa _jl.NoopBackend
                    req_obj = _jl.ChatRequest("noop", [_jl.ChatMessage("user", String(task_desc))])
                    resp = _jl.chat_completion(backend, req_obj)
                    dispatch_result[] = resp.text
                else
                    gait = get(snapshot, "gait", _current_gear)
                    dispatch_result[] = "Task processed locally by $agent_name in gait $gait."
                end
            end

            _broadcast(Dict(
                "type" => "terminal_output",
                "stream" => dispatch_error[] === nothing ? "stdout" : "stderr",
                "output" => dispatch_error[] === nothing ?
                    "Task [$task_id] completed: $(first(string(dispatch_result[]), 100))\n" :
                    "Task [$task_id] failed: $(first(string(dispatch_error[]), 100))\n",
                "exit_code" => dispatch_error[] === nothing ? 0 : 1,
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        catch err
            bt = sprint(showerror, err, catch_backtrace())
            @warn "Control dispatch execution error" exception=bt
            dispatch_error[] = string(err)
            _broadcast(Dict(
                "type" => "error",
                "code" => "TASK_DISPATCH_ERROR",
                "message" => first(string(err), 200),
                "source" => "control_dispatch",
                "fatal" => true,
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        end
    end

    _register_control_task!(task_id, agent_name, task_desc, cancel_ref, runner_task)

    try
        timedout = timedwait(() -> istaskdone(runner_task) || cancel_ref[], timeout_s) === :timed_out
        duration_ms = round(Int, (time() - t_start) * 1000)

        if cancel_ref[]
            return _http_json_response(stream, 200, Dict(
                "ok" => true,
                "task_id" => task_id,
                "status" => "cancelled",
                "agent" => agent_name,
                "message" => "Task was cancelled before completion.",
                "duration_ms" => duration_ms,
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        elseif timedout
            cancel_ref[] = true
            return _http_json_response(stream, 504, Dict(
                "ok" => false,
                "task_id" => task_id,
                "status" => "timeout",
                "agent" => agent_name,
                "error" => "Task exceeded timeout of $(timeout_s)s",
                "duration_ms" => duration_ms,
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        elseif dispatch_error[] !== nothing
            return _http_json_response(stream, 500, Dict(
                "ok" => false,
                "task_id" => task_id,
                "status" => "failed",
                "agent" => agent_name,
                "error" => dispatch_error[],
                "tools_called" => tools_called,
                "duration_ms" => duration_ms,
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        else
            return _http_json_response(stream, 200, Dict(
                "ok" => true,
                "task_id" => task_id,
                "status" => "completed",
                "agent" => agent_name,
                "result" => dispatch_result[],
                "tools_called" => tools_called,
                "telemetry" => Dict(
                    "gait" => _current_gear,
                    "duration_ms" => duration_ms,
                    "tokens" => _tokens_snapshot()
                ),
                "timestamp" => string(Dates.now(Dates.UTC))
            ))
        end
    finally
        _unregister_control_task!(task_id)
    end
end

function _handle_control_cancel_request(stream)
    body_bytes = try
        read(stream)
    catch err
        @warn "Failed to read cancel request body" exception=err
        UInt8[]
    end
    body_str = String(body_bytes)
    payload = try
        JSON.parse(body_str)
    catch err
        @warn "Failed to parse cancel JSON" exception=err
        Dict{String, Any}()
    end
    task_id = get(payload, "task_id", "all")

    cancelled_ids = String[]
    lock(_CONTROL_TASKS_LOCK) do
        if task_id == "all" || isempty(task_id)
            _generation_abort[] = true
            for (tid, ctask) in _CONTROL_TASKS
                ctask.cancel_ref[] = true
                push!(cancelled_ids, tid)
            end
        else
            if haskey(_CONTROL_TASKS, task_id)
                ctask = _CONTROL_TASKS[task_id]
                ctask.cancel_ref[] = true
                push!(cancelled_ids, task_id)
            else
                _generation_abort[] = true
            end
        end
    end

    _broadcast(Dict(
        "type" => "terminal_output",
        "stream" => "system",
        "output" => "⚡ Cancellation signaled for task(s): $(join(cancelled_ids, ", "))\n",
        "timestamp" => string(Dates.now(Dates.UTC))
    ))

    _http_json_response(stream, 200, Dict(
        "ok" => true,
        "task_id" => task_id,
        "cancelled_tasks" => cancelled_ids,
        "status" => "cancelled",
        "message" => "Task cancellation signaled successfully.",
        "timestamp" => string(Dates.now(Dates.UTC))
    ))
    return
end

"""
    serve(engine; host="127.0.0.1", port=8081)

Start the HTTP + WebSocket server. Blocks forever.
"""

# Cognitive topology, grounded in running JL Engine components.
# This is a processing/architecture graph, not a neural activation map.
function _build_mind_graph(engine)
    agent = string(engine.current_agent_name)
    nodes = [
        Dict("id"=>"core",       "name"=>"JL Engine",       "type"=>"concept", "detail"=>"Live Julia-native behavioral middleware"),
        Dict("id"=>"agent",      "name"=>agent,              "type"=>"goal",    "detail"=>"Active loaded agent"),
        Dict("id"=>"signals",    "name"=>"Signal Scorer",    "type"=>"concept", "detail"=>"Classifies message-level signals"),
        Dict("id"=>"behavior",   "name"=>"Behavior Grid",    "type"=>"state",   "detail"=>"Twenty-state behavioral control grid"),
        Dict("id"=>"drift",      "name"=>"Drift Pressure",   "type"=>"state",   "detail"=>"Tracks conversational drift"),
        Dict("id"=>"rhythm",     "name"=>"Rhythm Engine",    "type"=>"state",   "detail"=>"Controls response cadence and gait"),
        Dict("id"=>"aperture",   "name"=>"Emotional Aperture","type"=>"state",  "detail"=>"Shapes temperature and sampling controls"),
        Dict("id"=>"memory",     "name"=>"Hybrid Memory",   "type"=>"memory",  "detail"=>"Persistent SQLite-backed context"),
        Dict("id"=>"backend",    "name"=>"LLM Backend",     "type"=>"concept", "detail"=>"Configured model: " * string(_current_model) * "; a model response has not been verified"),
        Dict("id"=>"tools",      "name"=>"BYTE Tools",      "type"=>"tool",    "detail"=>"Tool dispatch; tool forging disabled in this test environment"),
        Dict("id"=>"browser",    "name"=>"Web UI",          "type"=>"concept", "detail"=>"Local HTTP/WebSocket interface"),
        Dict("id"=>"a2a",        "name"=>"A2A Bridge",      "type"=>"tool",    "detail"=>"Local agent-to-agent HTTP interface"),
        Dict("id"=>"autopilot",  "name"=>"Autopilot",       "type"=>"goal",    "detail"=>"Autonomous loops disabled for this smoke test"),
        Dict("id"=>"live",       "name"=>"Awaiting first turn", "type"=>"state", "detail"=>"Live state will update whenever the cognitive callback processes a turn")
    ]
    pairs = [
        ("agent","core"), ("browser","core"), ("core","signals"),
        ("signals","behavior"), ("behavior","drift"), ("drift","rhythm"),
        ("rhythm","aperture"), ("aperture","backend"), ("memory","core"),
        ("backend","tools"), ("core","a2a"), ("core","autopilot"),
        ("core","live"), ("tools","memory")
    ]
    links = [Dict("source"=>a,"target"=>b) for (a,b) in pairs]
    return Dict("type"=>"mind_graph", "nodes"=>nodes, "links"=>links,
                "source"=>"live_engine_topology", "timestamp"=>string(Dates.now(Dates.UTC)))
end

function serve(engine; host::String="127.0.0.1", port::Int=8081)
    _runtime_ui_url[] = "http://$host:$port/"
    println("⚡ BYTE serving on $host:$port")
    log_event("server_start", Dict{String,Any}("host"=>host, "port"=>port))
    _db_start_session(_session_id[])

    # ── Interactive Terminal CLI Reader ──
    @async begin
        try
            sleep(0.5)
            println("⚡ Terminal CLI ready. Type /help or /openrouter <key> directly in this console.")
            while !eof(stdin)
                line = strip(readline(stdin))
                isempty(line) && continue
                if startswith(line, "/")
                    _handle_slash_command(line, engine)
                elseif startswith(line, "openrouter ") || startswith(line, "key ") || startswith(line, "gear ")
                    _handle_slash_command("/" * line, engine)
                elseif line in ["help", "settings", "status"]
                    _handle_slash_command("/" * line, engine)
                else
                    println("💡 Type /help for available commands, or /openrouter <key> to set your OpenRouter key.")
                end
            end
        catch
        end
    end

    HTTP.serve(host, port, stream=true) do stream
        if HTTP.WebSockets.isupgrade(stream.message)
            HTTP.WebSockets.upgrade(stream) do ws
                cid = objectid(ws)
                lock(_WS_CLIENTS_LOCK) do; _WS_CLIENTS[cid] = ws; end
                log_event("ws_connect", Dict{String,Any}())
                _ws_send(ws, _backend_state_payload())
                _ws_send(ws, _build_mind_graph(engine))
                history = _load_recent_conversation_history()
                # WEBULA_ORDERED_WS_QUEUE_V1
                # Never silently discard follow-up builder, model or graph
                # commands while another command is running. This previously
                # caused incomplete graphs, missing saved bindings and UI
                # dropdowns that appeared to ignore a selection.
                #
                # Process normal messages serially in a worker. Stop-generation
                # remains an immediate priority event from the reader.
                request_queue = Channel{String}(128)
                processor_task = @async begin
                    for raw_msg in request_queue
                        _generation_abort[] = false
                        try
                            process_message(ws, raw_msg, history, engine)
                        catch e
                            bt = sprint(showerror, e, catch_backtrace())
                            @warn "WS message error" exception=bt
                            log_error("ws_loop", e; stacktrace_str=bt)
                            try
                                _ws_send(ws, JSON.json(Dict(
                                    "type"=>"builder_output",
                                    "output"=>"⚠ Server error: $(first(string(e),200))")))
                            catch send_err
                                @warn "Failed to forward WS loop error to UI" exception=(send_err, catch_backtrace())
                            end
                        end
                    end
                end
                try
                    for msg in ws
                        raw_msg = String(msg)
                        append_session_event("ws_in_full", Dict{String,Any}("bytes"=>ncodeunits(raw_msg), "message"=>raw_msg))
                        is_stop = try
                            parsed = JSON.parse(raw_msg)
                            parsed isa AbstractDict && get(parsed, "type", "") == "stop_generation"
                        catch
                            false
                        end
                        if is_stop
                            _generation_abort[] = true
                            _ws_send(ws, JSON.json(Dict("type"=>"tool",
                                "text"=>"⊣ Generation stopping after the current request.")))
                            log_cognitive_thought("Generation abort requested by user")
                            continue
                        end
                        put!(request_queue, raw_msg)
                    end
                finally
                    close(request_queue)
                    wait(processor_task)
                end
                lock(_WS_CLIENTS_LOCK) do; delete!(_WS_CLIENTS, cid); end
                log_event("ws_disconnect", Dict{String,Any}())
            end
        else
            req = stream.message
            # ── Dynamic operator lookup ────────────────────────────────────
            # Pulls the ACTIVE agent's identity straight from the loaded MPF
            # config on every request instead of serving a hard-coded agent.
            agent_data = engine.current_agent_data
            identity   = agent_data isa AbstractDict ? get(agent_data, "identity", Dict{String,Any}()) : Dict{String,Any}()
            op_name    = string(get(identity, "name", string(engine.current_agent_name)))
            op_desc    = string(get(identity, "description", ""))
            if req.target == "/health" || startswith(req.target, "/health?") || req.target == "/healthz" || startswith(req.target, "/healthz?")
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict(
                    "status" => "ok",
                    "service" => "sparkbyte",
                    "agent" => string(engine.current_agent_name),
                    "session_id" => _session_id[],
                    "time" => string(now()),
                    "tokens" => _tokens_snapshot(),
                )))
            elseif req.target == "/tokens" || startswith(req.target, "/tokens?")
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.startwrite(stream)
                snap = _tokens_snapshot()
                write(stream, JSON.json(Dict(
                    "service"           => "sparkbyte",
                    "session_id"        => _session_id[],
                    "model"             => _current_model,
                    "prompt_tokens"     => snap["prompt"],
                    "completion_tokens" => snap["completion"],
                    "total_tokens"      => snap["total"],
                    "api_calls"         => snap["calls"],
                    "time"              => string(now()),
                )))
            elseif req.target == "/operator" || startswith(req.target, "/operator?")
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict{String,Any}(
                    "ok"       => true,
                    "agent"    => string(engine.current_agent_name),
                    "operator" => Dict{String,Any}(
                        "name"        => op_name,
                        "role"        => string(get(identity, "role", "")),
                        "archetype"   => string(get(identity, "archetype", "")),
                        "description" => op_desc,
                        "tags"        => get(identity, "tags", Any[]),
                    ),
                    "engine" => Dict{String,Any}(
                        "model" => _current_model,
                        "gear"  => _current_gear,
                        "modes" => _active_modes,
                    ),
                )))
            elseif req.target == "/workspace" || startswith(req.target, "/workspace?")
                log_event("http_serve", Dict{String,Any}("path"=>"/workspace", "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"text/html; charset=utf-8")
                HTTP.setheader(stream, "Cache-Control"=>"no-store")
                HTTP.startwrite(stream)
                write(stream, ui_page(op_name, op_desc))
            elseif req.target == "/" || startswith(req.target, "/?")
                log_event("http_serve", Dict{String,Any}("path"=>"/", "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"text/html; charset=utf-8")
                HTTP.startwrite(stream)
                write(stream, ui_page(op_name, op_desc))
            elseif req.target == "/manifest.webmanifest"
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/manifest+json; charset=utf-8")
                HTTP.startwrite(stream)
                write(stream, manifest_page(op_name, op_desc))
            elseif req.target == "/icon-192.png" || req.target == "/icon-512.png"
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"image/png")
                HTTP.setheader(stream, "Cache-Control"=>"public, max-age=86400")
                HTTP.startwrite(stream)
                write(stream, req.target == "/icon-192.png" ? UI_ICON_192 : UI_ICON_512)
            elseif (req.method == "GET" && (req.target == "/api/models" || startswith(req.target, "/api/models?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                backend = _jl.get_backend("openrouter")
                models = _jl.fetch_model_catalog(backend)
                models_data = [
                    Dict{String,Any}(
                        "id" => m.id,
                        "name" => m.name,
                        "provider" => m.provider,
                        "context_length" => m.context_length,
                        "prompt_cost" => m.prompt_cost_per_m,
                        "completion_cost" => m.completion_cost_per_m,
                        "supports_streaming" => m.supports_streaming,
                        "supports_tools" => m.supports_tools,
                        "supports_vision" => m.supports_vision,
                        "supports_reasoning" => m.supports_reasoning,
                        "description" => m.description,
                    ) for m in models
                ]
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.setheader(stream, "Access-Control-Allow-Origin"=>"*")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict("ok"=>true, "models"=>models_data, "count"=>length(models_data))))
            elseif (req.method == "POST" && (req.target == "/api/models/refresh" || startswith(req.target, "/api/models/refresh?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                backend = _jl.get_backend("openrouter")
                models = _jl.fetch_model_catalog(backend; force_refresh=true)
                models_data = [
                    Dict{String,Any}(
                        "id" => m.id,
                        "name" => m.name,
                        "provider" => m.provider,
                        "context_length" => m.context_length,
                        "prompt_cost" => m.prompt_cost_per_m,
                        "completion_cost" => m.completion_cost_per_m,
                        "supports_streaming" => m.supports_streaming,
                        "supports_tools" => m.supports_tools,
                        "supports_vision" => m.supports_vision,
                        "supports_reasoning" => m.supports_reasoning,
                        "description" => m.description,
                    ) for m in models
                ]
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.setheader(stream, "Access-Control-Allow-Origin"=>"*")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict("ok"=>true, "models"=>models_data, "count"=>length(models_data), "refreshed"=>true)))
            elseif (req.method == "GET" && (req.target == "/api/config" || startswith(req.target, "/api/config?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                cfg_dict = _jl.get_config_dict(; mask_secrets=true)
                cfg_dict["memory_db_path"] = _runtime_state_path("sparkbyte_memory.db"; root=_project_root[])
                cfg_dict["current_model"] = string(_current_model)
                cfg_dict["active_provider"] = _backend_provider_for(_current_model)
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.setheader(stream, "Access-Control-Allow-Origin"=>"*")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict("ok"=>true, "config"=>cfg_dict)))
            elseif (req.method == "POST" && (req.target == "/api/config" || startswith(req.target, "/api/config?")))
                body_bytes = try read(stream) catch; UInt8[] end
                body_str = String(body_bytes)
                payload = try JSON.parse(body_str) catch; Dict{String,Any}() end
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                updated_keys = String[]
                errors = String[]
                for (k, v) in payload
                    try
                        if k == "current_model" && !_valid_backend_model(v)
                            error("Invalid model ID; selected backend remains unchanged")
                        end
                        _jl.update_config!(k, v; source="api")
                        if k == "current_model"
                            _set_backend_model!(v)
                        end
                        push!(updated_keys, string(k))
                    catch e
                        push!(errors, "$(k): $(sprint(showerror, e))")
                    end
                end
                status_code = isempty(errors) ? 200 : (isempty(updated_keys) ? 400 : 207)
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>status_code))
                HTTP.setstatus(stream, status_code)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.setheader(stream, "Access-Control-Allow-Origin"=>"*")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict(
                    "ok" => isempty(errors),
                    "updated" => updated_keys,
                    "errors" => errors,
                    "config" => merge(_jl.get_config_dict(; mask_secrets=true),
                        Dict("current_model"=>string(_current_model),
                             "active_provider"=>_backend_provider_for(_current_model)))
                )))
            elseif (req.method == "POST" && (req.target == "/api/provider/test" || startswith(req.target, "/api/provider/test?")))
                body_bytes = try read(stream) catch; UInt8[] end
                body_str = String(body_bytes)
                payload = try JSON.parse(body_str) catch; Dict{String,Any}() end
                provider = String(get(payload, "provider", "openrouter"))
                _jl = isdefined(Main, :JLEngine) ? Main.JLEngine : parentmodule(BYTE)
                backend = _jl.get_backend(provider)
                c_status = _jl.test_connection(backend)
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                HTTP.setstatus(stream, 200)
                HTTP.setheader(stream, "Content-Type"=>"application/json; charset=utf-8")
                HTTP.setheader(stream, "Access-Control-Allow-Origin"=>"*")
                HTTP.startwrite(stream)
                write(stream, JSON.json(Dict(
                    "ok" => c_status.ok,
                    "provider" => c_status.provider,
                    "endpoint" => c_status.endpoint,
                    "latency_ms" => c_status.latency_ms,
                    "error" => c_status.error_message,
                    "models_available" => c_status.models_available
                )))
            elseif (req.method == "GET" && (req.target == "/control/state" || startswith(req.target, "/control/state?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _handle_control_state_request(stream, engine, host, port, _BOOT_TIME)
            elseif (req.method == "GET" && (req.target == "/control/tools" || startswith(req.target, "/control/tools?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _handle_control_tools_request(stream)
            elseif (req.method == "POST" && (req.target == "/control/dispatch" || startswith(req.target, "/control/dispatch?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _handle_control_dispatch_request(stream, engine)
            elseif (req.method == "POST" && (req.target == "/control/cancel" || startswith(req.target, "/control/cancel?")))
                log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>200))
                _handle_control_cancel_request(stream)
            elseif req.method == "OPTIONS" && (startswith(req.target, "/api/") || startswith(req.target, "/control/"))
                _http_cors_preflight(stream)
            else
                # ── Delegate to A2A (and any other registered extra handler) ──
                extra = _EXTRA_HTTP_HANDLER[]
                handled = false
                if extra !== nothing
                    try
                        # Drain body so the handler can read it (stream=true doesn't preload).
                        body_bytes = try read(stream) catch; UInt8[] end
                        full_req = HTTP.Request(
                            string(req.method),
                            String(req.target),
                            req.headers,
                            body_bytes;
                            version = req.version,
                        )
                        resp = extra(full_req)
                        if resp !== nothing
                            HTTP.setstatus(stream, resp.status)
                            for (h, v) in resp.headers
                                HTTP.setheader(stream, h => v)
                            end
                            HTTP.startwrite(stream)
                            write(stream, resp.body)
                            log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>resp.status, "by"=>"extra"))
                            handled = true
                        end
                    catch e
                        @warn "Extra HTTP handler crashed" path=req.target exception=(e, catch_backtrace())
                        HTTP.setstatus(stream, 500)
                        HTTP.setheader(stream, "Content-Type"=>"application/json")
                        HTTP.startwrite(stream)
                        write(stream, JSON.json(Dict("error"=>"Extra handler error", "detail"=>first(string(e), 200))))
                        log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>500, "by"=>"extra"))
                        handled = true
                    end
                end
                if !handled
                    log_event("http_serve", Dict{String,Any}("path"=>req.target, "status"=>404))
                    HTTP.setstatus(stream, 404)
                    HTTP.setheader(stream, "Content-Type"=>"text/plain")
                    HTTP.startwrite(stream)
                    write(stream, "Not Found")
                end
            end
        end
    end
end

end # module BYTE

if abspath(PROGRAM_FILE) == @__FILE__
    include(joinpath(@__DIR__, "..", "..", "scripts", "crush.jl"))
end
