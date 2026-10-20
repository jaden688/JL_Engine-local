"""
    Telemetry.jl — Full event logging for SparkByte.

Writes newline-delimited JSON (JSONL) to full_telemetry.jsonl in the runtime state directory.
Every event is a self-contained JSON object with at minimum:
  - timestamp   (ISO8601)
  - event       (string category)
  - session_id  (shared across the process lifetime)

Append-only. Never truncates. Safe for concurrent WS connections (file-level lock via ReentrantLock).
"""

using JSON, Dates

# ── State ───────────────────────────────────────────────────────────────────
const _telem_lock    = ReentrantLock()
const _telem_path    = Ref{String}("")
const _telem_db      = Ref{Any}(nothing)   # SQLite.DB handle — set by init_telemetry
const _session_id    = Ref{String}("") # initialized per runtime boot, not at precompile time
const _turn_counter  = Ref{Int}(0)

# ── Cognitive broadcast hook ────────────────────────────────────────────────
# Set by BYTE.jl's init() — points to _broadcast_cognitive
const _COGNITIVE_HOOK = Ref{Any}(nothing)

function _telemetry_root(project_root::String)
    configured = strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))
    root = isempty(configured) ? project_root : abspath(configured)
    mkpath(root)
    return root
end

function _redact_sensitive_text(value)
    text = string(value)
    isempty(text) && return text
    text = replace(text, r"(?i)([?&](?:key|api[_-]?key|x-goog-api-key)=)([^&\s\"']+)" => s"\1[REDACTED]")
    text = replace(text, r"(?i)(Authorization:\s*Bearer\s+)([A-Za-z0-9._-]+)" => s"\1[REDACTED]")
    text = replace(text, r"(?i)(Bearer\s+)([A-Za-z0-9._-]+)" => s"\1[REDACTED]")
    text = replace(text, r"\b(sk-or-v1-[A-Za-z0-9_-]+)\b" => "sk-or-v1-[REDACTED]")
    text = replace(text, r"\b(csk|sk|xai)-[A-Za-z0-9_-]+\b" => s"\1-[REDACTED]")
    text = replace(text, r"\bAIza[0-9A-Za-z\-_]{20,}\b" => "[REDACTED]")
    text = replace(text, r"(?i)(\"(?:api[_-]?key|openrouter_api_key|gemini_api_key|openai_api_key|xai_api_key|token|secret)\"\s*:\s*\")([^\"]+)(\")" => s"\1[REDACTED]\3")
    return text
end

function init_telemetry(project_root::String; db=nothing)
    _session_id[] = string(round(Int, datetime2unix(now())))
    telem_root = _telemetry_root(project_root)
    _telem_path[] = joinpath(telem_root, "full_telemetry.jsonl")
    _telem_db[]   = db
    init_session_audit(telem_root)
    log_event("session_start", Dict{String,Any}(
        "session_id" => _session_id[],
        "session_audit_directory" => _audit_session_root[],
        "project_root" => project_root,
        "state_root" => telem_root,
        "julia_version" => string(VERSION),
        "os" => string(Sys.KERNEL),
        "arch" => string(Sys.ARCH),
    ))
end

function _print_telemetry_console(event::String, data::Dict{String,Any})
    try
        if event == "session_start"
            println("📊 [TELEMETRY] 🚀 Session Started | ID: $(get(data, "session_id", "")) | OS: $(get(data, "os", "")) | CPU Arch: $(get(data, "arch", "")) | Julia: $(get(data, "julia_version", ""))")
        elseif event == "api_request"
            println("📊 [TELEMETRY] 📤 API Request | Model: $(get(data, "model", "unknown")) | Loop Iter: $(get(data, "loop_iter", 0)) | Temp: $(get(data, "temperature", "N/A")) | Top_P: $(get(data, "top_p", "N/A"))")
        elseif event == "api_response"
            err = get(data, "error", "")
            err_str = isempty(err) ? "" : " | ❌ Error: $err"
            println("📊 [TELEMETRY] 📥 API Response | Model: $(get(data, "model", "unknown")) | Status: $(get(data, "status", 0)) | Bytes: $(get(data, "body_len", 0)) | Has Text: $(get(data, "has_text", false)) | Has Tool: $(get(data, "has_tool", false))$err_str")
        elseif event == "tool_call"
            println("📊 [TELEMETRY] 🔧 Tool Call | Tool: $(get(data, "tool_name", "unknown")) | Args: $(_redact_sensitive_text(JSON.json(get(data, "args", Dict()))))")
        elseif event == "tool_result"
            is_err = get(data, "is_error", false)
            status_symbol = is_err ? "❌ Failed" : "✅ Success"
            println("📊 [TELEMETRY] 📦 Tool Result | Tool: $(get(data, "tool_name", "unknown")) | Elapsed: $(get(data, "elapsed_ms", 0))ms | Status: $status_symbol")
        elseif event == "engine_snapshot"
            println("📊 [TELEMETRY] 🧠 Engine Snapshot | Agent: $(get(data, "agent", "")) | State: $(get(data, "behavior_state", "")) | Gait: $(get(data, "gait", "")) | Rhythm: $(get(data, "rhythm_mode", "")) | Temp: $(get(data, "aperture_temp", 0.0))")
        elseif event == "ws_in"
            msg_type = get(data, "msg_type", "unknown")
            if msg_type == "user_msg"
                println("📊 [TELEMETRY] 💬 WS Message In | Type: user_msg | Preview: \"$(get(data, "text_preview", ""))\"")
            else
                println("📊 [TELEMETRY] 📥 WS Message In | Type: $msg_type")
            end
        elseif event == "ws_out"
            println("📊 [TELEMETRY] 📤 WS Message Out | Type: $(get(data, "msg_type", "unknown"))")
        elseif event == "model_thinking"
            println("📊 [TELEMETRY] 💭 Thoughts: ", get(data, "thought_head", ""))
        elseif event in ("model_change", "settings_change", "agent_change")
            println("📊 [TELEMETRY] ⚙️ Settings Change | Event: $event | Details: $(_redact_sensitive_text(JSON.json(data)))")
        end
    catch e
    end
end

# ── Core writer ─────────────────────────────────────────────────────────────
function log_event(event::String, data::Dict{String,Any} = Dict{String,Any}())
    _telem_path[] == "" && return  # not yet initialized
    ts = string(now())
    entry = merge(Dict{String,Any}(
        "timestamp"  => ts,
        "session_id" => _session_id[],
        "event"      => event,
    ), data)
    line = JSON.json(entry)
    clean_line = _redact_sensitive_text(line)

    # ① Always write to JSONL (scrubbed debug log)
    lock(_telem_lock) do
        open(_telem_path[], "a") do f
            println(f, clean_line)
        end
    end

    append_session_event(event, data)

    # ③ Print formatted telemetry summary to console
    _print_telemetry_console(event, data)
    println("[Telemetry] ", clean_line)

    # ② Dual-write to SQLite telemetry table so SparkByte can query her own history
    if _telem_db[] !== nothing
        try
            model = string(get(data, "model", ""))
            agent = string(get(data, "agent", ""))
            SQLite.execute(_telem_db[],
                "INSERT INTO telemetry (timestamp, session_id, event, turn_number, model, agent, data_json) VALUES (?,?,?,?,?,?,?)",
                (ts, _session_id[], event, Int(_turn_counter[]), model, agent, clean_line))
        catch e
            @warn "Telemetry SQLite write failed" event=event exception=(e, catch_backtrace())
        end
    end
end

# ── Convenience wrappers ─────────────────────────────────────────────────────

function log_ws_message_in(raw::String)
    try
        p = JSON.parse(raw)
        t = get(p, "type", "unknown")
        d = Dict{String,Any}("msg_type" => t)
        if t == "user_msg"
            d["text_len"] = length(get(p, "text", ""))
            d["text_preview"] = first(get(p, "text", ""), 200)
            d["has_image"] = get(p, "image", nothing) !== nothing
        elseif t == "builder_cmd"
            d["cmd"] = get(p, "cmd", "")
        elseif t == "model_change"
            d["model"] = get(p, "model", "")
        elseif t == "agent_change"
            d["agent"] = get(p, "agent", "")
        end
        log_event("ws_in", d)
    catch
        log_event("ws_in", Dict{String,Any}("raw_preview" => first(raw, 200), "parse_error" => true))
    end
end

function log_ws_message_out(obj::Dict)
    t = get(obj, "type", "unknown")
    d = Dict{String,Any}("msg_type" => t)
    if t == "spark"
        spark_text = _redact_sensitive_text(get(obj, "text", ""))
        d["text_len"]     = length(spark_text)
        d["text_preview"] = first(spark_text, 200)
    elseif t == "tool"
        d["text"] = get(obj, "text", "")
    elseif t == "ui_update"
        d["gear"]  = get(obj, "gear", "")
        d["modes"] = get(obj, "modes", [])
    elseif t == "builder_tree"
        d["file_count"] = length(get(obj, "files", []))
    end
    log_event("ws_out", d)
end

function log_engine_snapshot(snapshot::Dict)
    log_event("engine_snapshot", Dict{String,Any}(
        "gait"            => get(snapshot, "gait", ""),
        "rhythm_mode"     => get(get(snapshot, "rhythm", Dict()), "mode", ""),
        "aperture_mode"   => get(get(snapshot, "aperture_state", Dict()), "mode", ""),
        "aperture_temp"   => get(get(snapshot, "aperture_state", Dict()), "temp", 0.0),
        "aperture_top_p"  => get(get(snapshot, "aperture_state", Dict()), "top_p", 0.0),
        "behavior_state"  => get(get(snapshot, "behavior_state", Dict()), "name", ""),
        "behavior_number" => get(get(snapshot, "behavior_state", Dict()), "number", 0),
        "behavior_intensity" => get(snapshot, "behavior_intensity", 0.0),
        "behavior_expr"   => get(get(snapshot, "behavior_state", Dict()), "expressiveness", 0.0),
        "mpf_state"       => get(get(snapshot, "mpf_state_profile", Dict()), "label", ""),
        "mpf_profile_source" => get(get(snapshot, "mpf_state_profile", Dict()), "source", ""),
        "mpf_temp_delta"  => get(get(snapshot, "mpf_sampling_bias", Dict()), "temperature", 0.0),
        "mpf_top_p_delta" => get(get(snapshot, "mpf_sampling_bias", Dict()), "top_p", 0.0),
        "drift_pressure"  => get(get(snapshot, "drift", Dict()), "pressure", 0.0),
        "drift_temp_delta"=> get(get(snapshot, "drift", Dict()), "temperature_delta", 0.0),
        "advisory_msg"    => get(get(snapshot, "advisory", Dict()), "msg", ""),
        "agent"         => get(snapshot, "agent", ""),
        "trigger"         => get(snapshot, "trigger", ""),
    ))
end

function log_api_request(model, gen_config, history_len, loop_iter)
    log_event("api_request", Dict{String,Any}(
        "model"        => string(model),
        "loop_iter"    => Int(loop_iter),
        "history_len"  => Int(history_len),
        "temperature"  => get(gen_config, "temperature", nothing),
        "top_p"        => get(gen_config, "topP", nothing),
        "thinking"     => get(get(gen_config, "thinking_config", Dict()), "thinking_level", "none"),
    ))
end

function log_api_response(model, status, body_len, loop_iter;
                          has_text=false, has_tool=false,
                          text_preview="", tool_name="",
                          finish_reason="", error="")
    log_event("api_response", Dict{String,Any}(
        "model"        => string(model),
        "loop_iter"    => Int(loop_iter),
        "status"       => Int(status),
        "body_len"     => Int(body_len),
        "has_text"     => has_text,
        "has_tool"     => has_tool,
        "text_preview" => first(_redact_sensitive_text(text_preview), 300),
        "tool_name"    => string(tool_name),
        "finish_reason"=> string(finish_reason),
        "error"        => _redact_sensitive_text(error),
    ))
end

function log_tool_call(name, args, loop_iter)
    append_session_event("tool_call_full", Dict{String,Any}(
        "tool_name"=>string(name), "loop_iter"=>Int(loop_iter), "arguments"=>args))
    safe_args = try JSON.parse(JSON.json(args)) catch; Dict("_raw" => string(args)) end
    # Redact large fields like code blobs
    if haskey(safe_args, "content") && length(string(get(safe_args, "content", ""))) > 200
        safe_args["content"] = first(string(safe_args["content"]), 200) * "...[truncated]"
    end
    log_event("tool_call", Dict{String,Any}(
        "tool_name" => name,
        "loop_iter" => loop_iter,
        "args"      => safe_args,
    ))
end

function log_tool_result(name, result, loop_iter; elapsed_ms=0)
    append_session_event("tool_result_full", Dict{String,Any}(
        "tool_name"=>string(name),"loop_iter"=>Int(loop_iter),
        "elapsed_ms"=>elapsed_ms,"result"=>result))
    safe_result = try JSON.parse(JSON.json(result)) catch; Dict("_raw" => string(result)) end
    result_str = JSON.json(safe_result)
    if length(result_str) > 500
        safe_result = Dict("_truncated" => first(result_str, 500) * "...")
    end
    log_event("tool_result", Dict{String,Any}(
        "tool_name"  => string(name),
        "loop_iter"  => Int(loop_iter),
        "elapsed_ms" => Int(elapsed_ms),
        "result"     => safe_result,
        "is_error"   => haskey(safe_result, "error"),
    ))
end

function log_turn_complete(user_text, reply_len, loop_iters, elapsed_ms)
    _turn_counter[] += 1
    log_event("turn_complete", Dict{String,Any}(
        "turn_number"   => _turn_counter[],
        "user_preview"  => first(string(user_text), 200),
        "reply_len"     => Int(reply_len),
        "tool_loops"    => Int(loop_iters),
        "elapsed_ms"    => Int(elapsed_ms),
    ))
end

function log_error(event_context, err; stacktrace_str="")
    log_event("error", Dict{String,Any}(
        "context"    => string(event_context),
        "error_type" => string(typeof(err)),
        "error_msg"  => first(_redact_sensitive_text(err), 500),
        "stacktrace" => first(_redact_sensitive_text(stacktrace_str), 1000),
    ))
end

function log_builder_cmd(cmd, path="", extra=Dict{String,Any}())
    d = merge(Dict{String,Any}("cmd" => string(cmd), "path" => string(path)), extra)
    log_event("builder_cmd", d)
end

function log_agent_change(from, to, success)
    log_event("agent_change", Dict{String,Any}("from"=>string(from), "to"=>string(to), "success"=>success==true))
end

function log_model_change(from, to)
    log_event("model_change", Dict{String,Any}("from"=>string(from), "to"=>string(to)))
end

function log_settings_change(key_set, field)
    log_event("settings_change", Dict{String,Any}("field"=>string(field), "key_set"=>key_set==true))
end

# ── COGNITIVE BROADCAST ──────────────────────────────────────────────────────
# These fire live to the terminal panel via the _COGNITIVE_HOOK

function log_cognitive_thought(text::AbstractString)
    hook = _COGNITIVE_HOOK[]
    if hook !== nothing
        try
            hook("thought", text)
        catch
        end
    end
end

function log_cognitive_tool(name::AbstractString, status::AbstractString, detail::AbstractString="")
    hook = _COGNITIVE_HOOK[]
    if hook !== nothing
        try
            hook("tool", name, status, detail)
        catch
        end
    end
end

function log_cognitive_state(snapshot::Dict)
    hook = _COGNITIVE_HOOK[]
    if hook !== nothing
        try
            gait   = string(get(snapshot, "gait", ""))
            rhythm = string(get(get(snapshot, "rhythm", Dict()), "mode", ""))
            aper   = string(get(get(snapshot, "aperture_state", Dict()), "mode", ""))
            behav  = string(get(get(snapshot, "behavior_state", Dict()), "name", ""))
            drift  = round(get(get(snapshot, "drift", Dict()), "pressure", 0.0); digits=3)
            hook("state", gait, rhythm, aper, behav, drift)
        catch
        end
    end
end

function log_cognitive_forge(name::AbstractString, status::AbstractString, detail::AbstractString="")
    hook = _COGNITIVE_HOOK[]
    if hook !== nothing
        try
            hook("forge", name, status, detail)
        catch
        end
    end
end

function log_cognitive_api(model::AbstractString, status::AbstractString, detail::AbstractString="")
    hook = _COGNITIVE_HOOK[]
    if hook !== nothing
        try
            hook("api", model, status, detail)
        catch
        end
    end
end

# ── Deep "why" telemetry ─────────────────────────────────────────────────────

"""Log the full system prompt + the engine state that produced it."""
function log_system_prompt(prompt, snapshot)
    aperture   = get(snapshot, "aperture_state", Dict())
    drift      = get(snapshot, "drift",          Dict())
    behavior   = get(snapshot, "behavior_state", Dict())
    rhythm     = get(snapshot, "rhythm",         Dict())
    advisory   = get(snapshot, "advisory",       Dict())
    log_event("system_prompt", Dict{String,Any}(
        "prompt_len"        => length(prompt),
        "prompt_hash"       => string(hash(prompt)),
        "prompt_head"       => first(prompt, 600),
        # WHY these params were set
        "engine_gait"       => string(get(snapshot, "gait", "")),
        "engine_agent"    => string(get(snapshot, "agent", "")),
        "engine_trigger"    => string(get(snapshot, "trigger", "")),
        "behavior_intensity"=> get(snapshot, "behavior_intensity", 0.0),
        "behavior_number"   => get(behavior, "number", 0),
        "behavior_name"     => string(get(behavior, "name", "")),
        "behavior_expr"     => get(behavior, "expressiveness", 0.0),
        "behavior_pacing"   => string(get(behavior, "pacing", "")),
        "behavior_tone"     => string(get(behavior, "tone_bias", "")),
        "mpf_state"         => string(get(get(snapshot, "mpf_state_profile", Dict()), "label", "")),
        "mpf_profile_source"=> string(get(get(snapshot, "mpf_state_profile", Dict()), "source", "")),
        "rhythm_mode"       => string(get(rhythm,   "mode", "")),
        "rhythm_momentum"   => get(rhythm,   "momentum",    0.0),
        "aperture_mode"     => string(get(aperture, "mode", "")),
        "aperture_temp"     => get(aperture, "temp",    0.0),
        "aperture_top_p"    => get(aperture, "top_p",   0.0),
        "drift_pressure"    => get(drift, "pressure",         0.0),
        "drift_temp_delta"  => get(drift, "temperature_delta",0.0),
        "drift_action"      => string(get(drift, "action_level", "")),
        "advisory_msg"      => string(get(advisory, "msg", "")),
        "advisory_gating"   => string(get(advisory, "gating_bias", "")),
        "advisory_emotion"  => string(get(advisory, "emotional_drift", "")),
    ))
end

"""Log the causal chain: engine snapshot → temperature/topP decision."""
function log_param_decision(gen_config, snapshot)
    aperture = get(snapshot, "aperture_state", Dict())
    drift    = get(snapshot, "drift",          Dict())
    state_bias = get(snapshot, "mpf_sampling_bias", Dict())
    base_temp  = get(aperture, "temp",              0.45)
    delta_temp = get(drift,    "temperature_delta", 0.0)
    mpf_temp = get(state_bias, "temperature", 0.0)
    mpf_top_p = get(state_bias, "top_p", 0.0)
    final_temp = get(gen_config, "temperature",     0.0)
    log_event("param_decision", Dict{String,Any}(
        "base_temp"       => base_temp,
        "drift_delta"     => delta_temp,
        "mpf_temp_delta"  => mpf_temp,
        "mpf_top_p_delta" => mpf_top_p,
        "final_temp"      => final_temp,
        "final_top_p"     => get(gen_config, "topP", 0.0),
        "thinking_level"  => get(get(gen_config, "thinking_config", Dict()), "thinking_level", "none"),
        "aperture_mode"   => string(get(aperture, "mode", "")),
        "drift_pressure"  => get(drift, "pressure", 0.0),
        "why_temp"        => "aperture_base=$(round(base_temp,digits=3)) + drift_delta=$(round(delta_temp,digits=3)) + mpf_cell=$(round(mpf_temp,digits=3)) = $(round(final_temp,digits=3))",
        "why_top_p"       => "aperture_top_p=$(get(aperture,"top_p",0.7)) + mpf_cell=$(round(mpf_top_p,digits=3)) → $(get(gen_config,"topP",0.0))",
    ))
end

"""Log Gemini token usage from usageMetadata."""
function log_token_usage(usage_meta, loop_iter)
    isnothing(usage_meta) && return
    log_event("token_usage", Dict{String,Any}(
        "loop_iter"          => Int(loop_iter),
        "prompt_tokens"      => get(usage_meta, "promptTokenCount",     0),
        "candidate_tokens"   => get(usage_meta, "candidatesTokenCount", 0),
        "total_tokens"       => get(usage_meta, "totalTokenCount",       0),
        "thinking_tokens"    => get(usage_meta, "thoughtsTokenCount",   0),
    ))
end

"""Log safety ratings from a Gemini candidate."""
function log_safety_ratings(ratings, loop_iter)
    isempty(ratings) && return
    safe_list = [Dict{String,Any}(
        "category"    => string(get(r, "category",    "")),
        "probability" => string(get(r, "probability", "")),
        "blocked"     => get(r, "blocked", false) == true,
    ) for r in ratings]
    blocked_any = any(get(r, "blocked", false) == true for r in ratings)
    log_event("safety_ratings", Dict{String,Any}(
        "loop_iter"   => Int(loop_iter),
        "ratings"     => safe_list,
        "blocked_any" => blocked_any,
    ))
end

"""Log reasoning/thinking text from thinking models."""
function log_thinking(thought_text, loop_iter)
    isempty(thought_text) && return
    log_event("model_thinking", Dict{String,Any}(
        "loop_iter"    => Int(loop_iter),
        "thought_len"  => length(thought_text),
        "thought_head" => first(thought_text, 800),
    ))
end
