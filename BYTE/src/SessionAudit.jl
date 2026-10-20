# Local append-only diagnostic stream for each SparkByte engine run.
const _audit_session_root = Ref{String}("")
const _audit_session_file = Ref{String}("")
const _audit_counter = Ref{Int}(0)

function init_session_audit(state_root::String)
    dir = joinpath(state_root, "sessions",
        "session_" * _session_id[] * "_pid_" * string(getpid()))
    mkpath(joinpath(dir, "transactions"))
    _audit_session_root[] = dir
    _audit_session_file[] = joinpath(dir, "events.jsonl")
    _audit_counter[] = 0
    return dir
end

function append_session_event(event::String, info::Dict{String,Any})
    isempty(_audit_session_file[]) && return
    try
        line = _redact_sensitive_text(JSON.json(merge(Dict{String,Any}(
           "timestamp"=>string(now()),"session_id"=>_session_id[],
           "event"=>event), info)))
        lock(_telem_lock) do
            open(_audit_session_file[], "a") do f
                println(f, line)
            end
        end
    catch e
        @warn "Session diagnostic write failed" exception=(e, catch_backtrace())
    end
end

function audit_api_request(model::String, provider::String, endpoint::String, body::String)
    isempty(_audit_session_root[]) && return ""
    try
        _audit_counter[] += 1
        tag = "api_" * lpad(string(_audit_counter[]), 6, '0')
        dir = joinpath(_audit_session_root[], "transactions", tag)
        mkpath(dir)
        write(joinpath(dir, "request.json"), body)
        append_session_event("http_request_full", Dict{String,Any}(
            "transaction"=>tag, "model"=>model, "provider"=>provider,
            "endpoint"=>endpoint, "bytes"=>ncodeunits(body),
            "body"=>body))
        return tag
    catch e
        @warn "Request recording failed" exception=(e, catch_backtrace())
        return ""
    end
end

function audit_api_response(tag::String, status::Int, body::String)
    isempty(tag) && return
    try
        dir = joinpath(_audit_session_root[], "transactions", tag)
        write(joinpath(dir, "response.json"), body)
        append_session_event("http_response_full", Dict{String,Any}(
            "transaction"=>tag, "status"=>status,
            "bytes"=>ncodeunits(body), "body"=>body))
    catch e
        @warn "Response recording failed" exception=(e, catch_backtrace())
    end
end

function audit_api_error(tag::String, err)
    isempty(tag) && return
    text = _redact_sensitive_text(sprint(showerror,err))
    try
        dir = joinpath(_audit_session_root[], "transactions", tag)
        write(joinpath(dir, "error.json"), JSON.json(Dict("error"=>text)))
        append_session_event("http_error", Dict{String,Any}(
            "transaction"=>tag, "error"=>text))
    catch e
        @warn "HTTP error recording failed" exception=(e, catch_backtrace())
    end
end
