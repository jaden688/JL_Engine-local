using HTTP
using JSON
using JSON3
using SQLite
using Dates

export ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    TokenUsage,
    ModelInfo,
    ConnectionStatus,
    ProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderServerError,
    ProviderConnectionError,
    ProviderCancelledException,
    ProviderStreamInterruptedError,
    AbstractBackend,
    NoopBackend,
    OpenRouterBackend,
    OllamaBackend,
    GoogleGeminiBackend,
    CustomHTTPBackend,
    FallbackChain,
    ProviderTarget,
    CircuitBreaker,
    CircuitState,
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    CIRCUIT_HALF_OPEN,
    chat_completion,
    stream_chat_completion,
    fetch_model_catalog,
    test_connection,
    init_model_catalog_table!,
    set_backend_model!,
    configure_backends!,
    set_brain_backend_id!,
    set_tool_backend_id!,
    get_backend,
    get_brain_backend,
    get_tool_backend,
    BACKEND_REGISTRY,
    ACTIVE_BACKENDS,
    generate

# ── 1. Unified Typed Taxonomy ────────────────────────────────────────────────

struct ChatMessage
    role::String          # "system", "user", "assistant", "tool"
    content::String       # Text content
    name::Union{Nothing, String}
    tool_calls::Union{Nothing, Vector{Dict{String, Any}}}
    tool_call_id::Union{Nothing, String}

    ChatMessage(role::String, content::String; name=nothing, tool_calls=nothing, tool_call_id=nothing) =
        new(role, content, name, tool_calls, tool_call_id)
end

struct ChatRequest
    model::String
    messages::Vector{ChatMessage}
    temperature::Float64
    top_p::Float64
    max_tokens::Union{Nothing, Int}
    reasoning_effort::Union{Nothing, String} # "none", "low", "medium", "high"
    tools::Union{Nothing, Vector{Dict{String, Any}}}
    timeout::Int
    stream::Bool
    stream_options::Dict{String, Any}

    function ChatRequest(
        model::String,
        messages::Vector{ChatMessage};
        temperature::Float64=0.7,
        top_p::Float64=0.95,
        max_tokens::Union{Nothing, Int}=nothing,
        reasoning_effort::Union{Nothing, String}=nothing,
        tools::Union{Nothing, Vector{Dict{String, Any}}}=nothing,
        timeout::Int=120,
        stream::Bool=false,
        stream_options::Dict{String, Any}=Dict{String, Any}()
    )
        new(model, messages, temperature, top_p, max_tokens, reasoning_effort, tools, timeout, stream, stream_options)
    end
end

struct TokenUsage
    prompt_tokens::Int
    completion_tokens::Int
    total_tokens::Int
    cost_estimate::Float64
end

struct StreamChunk
    delta_text::String
    reasoning_delta::String
    finish_reason::Union{Nothing, String}
    usage::Union{Nothing, TokenUsage}
    tool_calls::Union{Nothing, Vector{Dict{String, Any}}}
end

struct ChatResponse
    text::String
    reasoning::String
    model::String
    provider::String
    finish_reason::String
    usage::TokenUsage
    tool_calls::Vector{Dict{String, Any}}
    raw::Dict{String, Any}
end

struct ModelInfo
    id::String
    name::String
    provider::String
    context_length::Int
    prompt_cost_per_m::Float64
    completion_cost_per_m::Float64
    supports_streaming::Bool
    supports_tools::Bool
    supports_vision::Bool
    supports_reasoning::Bool
    description::String
end

struct ConnectionStatus
    ok::Bool
    provider::String
    endpoint::String
    latency_ms::Float64
    error_message::Union{Nothing, String}
    models_available::Int
end

# ── 2. Typed Exception Taxonomy ───────────────────────────────────────────────

abstract type ProviderError <: Exception end

struct ProviderAuthError <: ProviderError
    provider::String
    status::Int
    message::String
end

struct ProviderRateLimitError <: ProviderError
    provider::String
    status::Int
    retry_after_s::Float64
    message::String
end

struct ProviderTimeoutError <: ProviderError
    provider::String
    timeout_s::Float64
    message::String
end

struct ProviderServerError <: ProviderError
    provider::String
    status::Int
    message::String
end

struct ProviderConnectionError <: ProviderError
    provider::String
    message::String
end

struct ProviderCancelledException <: ProviderError
    message::String
end

struct ProviderStreamInterruptedError <: ProviderError
    provider::String
    message::String
    partial_text::String
end

function _throw_typed_http_error(provider::String, status::Integer, body::String)
    status_int = Int(status)
    # Attempt to extract error message from body JSON
    msg = body
    try
        parsed = JSON3.read(body)
        if haskey(parsed, :error)
            err_obj = parsed.error
            if err_obj isa AbstractDict || err_obj isa JSON3.Object
                msg = string(get(err_obj, :message, string(err_obj)))
            else
                msg = string(err_obj)
            end
        end
    catch
    end

    if status_int == 401 || status_int == 403
        throw(ProviderAuthError(provider, status_int, msg))
    elseif status_int == 429
        throw(ProviderRateLimitError(provider, status_int, 2.0, msg))
    elseif status_int >= 500
        throw(ProviderServerError(provider, status_int, msg))
    else
        throw(ProviderServerError(provider, status_int, "HTTP $status_int: $msg"))
    end
end

# ── 3. Model Catalog Cache & SQLite Store ────────────────────────────────────

mutable struct ModelCatalogCache
    models::Vector{ModelInfo}
    last_fetched::Float64
    ttl_seconds::Float64
    is_valid::Bool

    ModelCatalogCache() = new(ModelInfo[], 0.0, 3600.0, false)
end

function init_model_catalog_table!(db::SQLite.DB)
    SQLite.execute(db, """
        CREATE TABLE IF NOT EXISTS model_catalog (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            context_length INTEGER DEFAULT 4096,
            prompt_cost REAL DEFAULT 0.0,
            completion_cost REAL DEFAULT 0.0,
            supports_streaming INTEGER DEFAULT 1,
            supports_tools INTEGER DEFAULT 1,
            supports_vision INTEGER DEFAULT 0,
            supports_reasoning INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
    """)
    SQLite.execute(db, "CREATE INDEX IF NOT EXISTS idx_model_catalog_provider ON model_catalog(provider);")
end

function _persist_model_catalog_sqlite(models::Vector{ModelInfo}, db::Union{Nothing, SQLite.DB}=nothing)
    target_db = db
    if target_db === nothing
        # Try finding DB from global config manager or BYTE
        mgr = isdefined(@__MODULE__, :GLOBAL_CONFIG_MANAGER) ? GLOBAL_CONFIG_MANAGER[] : nothing
        target_db = mgr !== nothing ? mgr.db : nothing
    end
    target_db === nothing && return

    now_utc = string(Dates.now(Dates.UTC))
    try
        SQLite.transaction(target_db) do
            for m in models
                SQLite.execute(target_db, """
                    INSERT INTO model_catalog (
                        id, name, provider, context_length, prompt_cost, completion_cost,
                        supports_streaming, supports_tools, supports_vision, supports_reasoning,
                        description, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        provider = excluded.provider,
                        context_length = excluded.context_length,
                        prompt_cost = excluded.prompt_cost,
                        completion_cost = excluded.completion_cost,
                        supports_streaming = excluded.supports_streaming,
                        supports_tools = excluded.supports_tools,
                        supports_vision = excluded.supports_vision,
                        supports_reasoning = excluded.supports_reasoning,
                        description = excluded.description,
                        updated_at = excluded.updated_at
                """, (
                    m.id, m.name, m.provider, m.context_length,
                    m.prompt_cost_per_m, m.completion_cost_per_m,
                    m.supports_streaming ? 1 : 0, m.supports_tools ? 1 : 0,
                    m.supports_vision ? 1 : 0, m.supports_reasoning ? 1 : 0,
                    m.description, now_utc
                ))
            end
        end
    catch e
        @warn "Failed to persist model catalog to SQLite" exception=e
    end
end

function _load_model_catalog_sqlite(db::Union{Nothing, SQLite.DB}=nothing)::Vector{ModelInfo}
    target_db = db
    if target_db === nothing
        mgr = isdefined(@__MODULE__, :GLOBAL_CONFIG_MANAGER) ? GLOBAL_CONFIG_MANAGER[] : nothing
        target_db = mgr !== nothing ? mgr.db : nothing
    end
    target_db === nothing && return ModelInfo[]

    models = ModelInfo[]
    try
        for row in SQLite.DBInterface.execute(target_db, "SELECT * FROM model_catalog")
            push!(models, ModelInfo(
                String(row.id),
                String(row.name),
                String(row.provider),
                Int(row.context_length),
                Float64(row.prompt_cost),
                Float64(row.completion_cost),
                row.supports_streaming == 1,
                row.supports_tools == 1,
                row.supports_vision == 1,
                row.supports_reasoning == 1,
                String(row.description)
            ))
        end
    catch e
        @warn "Failed to read model catalog from SQLite" exception=e
    end
    return models
end

# ── 4. AbstractBackend Hierarchy ──────────────────────────────────────────────

abstract type AbstractBackend end

# ── 4.1 NoopBackend ──────────────────────────────────────────────────────────

struct NoopBackend <: AbstractBackend
    config::Dict{String, Any}
end

function chat_completion(backend::NoopBackend, req::ChatRequest)::ChatResponse
    last_user = ""
    for m in Iterators.reverse(req.messages)
        if m.role == "user"
            last_user = m.content
            break
        end
    end
    reply = isempty(last_user) ? "[NOOP BACKEND] Stub response. No model called." : last_user
    usage = TokenUsage(10, 10, 20, 0.0)
    return ChatResponse(reply, "", "noop-stub", "noop", "stop", usage, Dict{String, Any}[], Dict{String, Any}())
end

function stream_chat_completion(
    backend::NoopBackend,
    req::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    resp = chat_completion(backend, req)
    words = split(resp.text, " ")
    for (i, word) in enumerate(words)
        if cancel_ref[]
            throw(ProviderCancelledException("Noop stream cancelled"))
        end
        token = i == length(words) ? word : word * " "
        on_chunk(StreamChunk(token, "", i == length(words) ? "stop" : nothing, nothing, nothing))
        sleep(0.01)
    end
    return resp
end

function fetch_model_catalog(backend::NoopBackend; force_refresh::Bool=false)::Vector{ModelInfo}
    return [ModelInfo("noop-stub", "Stub (No backend)", "noop", 4096, 0.0, 0.0, true, true, false, false, "Offline stub")]
end

function test_connection(backend::NoopBackend)::ConnectionStatus
    return ConnectionStatus(true, "noop", "local", 0.1, nothing, 1)
end

# ── 4.2 OpenRouterBackend ────────────────────────────────────────────────────

const DEFAULT_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
const DEFAULT_OPENROUTER_MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"
const DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"

struct OpenRouterBackend <: AbstractBackend
    config::Dict{String, Any}
    cache::ModelCatalogCache

    OpenRouterBackend(config::Dict{String, Any}=Dict{String, Any}()) = new(config, ModelCatalogCache())
end

function _resolve_api_key(backend::OpenRouterBackend)::String
    k = get(backend.config, "api_key", nothing)
    if k !== nothing && !isempty(String(k))
        return String(k)
    end
    return get(ENV, "OPENROUTER_API_KEY", "")
end

function _build_openrouter_payload(req::ChatRequest; stream::Bool=false)::Dict{String, Any}
    msgs = Any[]
    for m in req.messages
        msg_d = Dict{String, Any}("role" => m.role, "content" => m.content)
        m.name !== nothing && (msg_d["name"] = m.name)
        m.tool_calls !== nothing && (msg_d["tool_calls"] = m.tool_calls)
        m.tool_call_id !== nothing && (msg_d["tool_call_id"] = m.tool_call_id)
        push!(msgs, msg_d)
    end

    payload = Dict{String, Any}(
        "model" => req.model,
        "messages" => msgs,
        "temperature" => req.temperature,
        "top_p" => req.top_p,
    )
    req.max_tokens !== nothing && (payload["max_tokens"] = req.max_tokens)
    if req.reasoning_effort !== nothing && req.reasoning_effort != "none"
        payload["reasoning_effort"] = req.reasoning_effort
    end
    if req.tools !== nothing && !isempty(req.tools)
        payload["tools"] = req.tools
    end
    if stream
        payload["stream"] = true
        payload["stream_options"] = Dict{String, Any}("include_usage" => true)
    end
    return payload
end

function _notify_byte_tokens(usage::TokenUsage)
    _byte = isdefined(Main, :JLEngine) && isdefined(Main.JLEngine, :BYTE) ? Main.JLEngine.BYTE :
            (isdefined(Main, :BYTE) ? Main.BYTE : nothing)
    if _byte !== nothing && isdefined(_byte, :_record_token_usage)
        try
            usage_dict = Dict(
                "prompt_tokens" => usage.prompt_tokens,
                "completion_tokens" => usage.completion_tokens,
                "total_tokens" => usage.total_tokens
            )
            _byte._record_token_usage(usage_dict, 0)
        catch
        end
    end
end

function chat_completion(backend::OpenRouterBackend, req::ChatRequest)::ChatResponse
    api_key = _resolve_api_key(backend)
    isempty(api_key) && throw(ProviderAuthError("openrouter", 401, "OpenRouter API key is not set."))

    endpoint = String(get(backend.config, "endpoint", DEFAULT_OPENROUTER_ENDPOINT))
    headers = [
        "Content-Type"  => "application/json",
        "Authorization" => "Bearer $(api_key)",
        "HTTP-Referer"  => "http://localhost:8081",
        "X-Title"       => "JL Engine"
    ]

    payload = _build_openrouter_payload(req; stream=false)
    timeout = req.timeout > 0 ? req.timeout : get(backend.config, "timeout", 120)

    resp = try
        HTTP.post(endpoint, headers, JSON3.write(payload); readtimeout=timeout)
    catch e
        if e isa HTTP.Exceptions.StatusError
            body = String(e.response.body)
            _throw_typed_http_error("openrouter", e.status, body)
        elseif e isa HTTP.Exceptions.TimeoutError
            throw(ProviderTimeoutError("openrouter", Float64(timeout), "OpenRouter request timed out after $(timeout)s"))
        elseif e isa Base.IOError || occursin("ConnectError", string(typeof(e)))
            throw(ProviderConnectionError("openrouter", "Network error: $(e)"))
        else
            rethrow(e)
        end
    end

    data = _materialize_json(JSON3.read(String(resp.body)))

    usage = TokenUsage(0, 0, 0, 0.0)
    if haskey(data, "usage")
        u = data["usage"]
        pt = get(u, "prompt_tokens", 0)
        ct = get(u, "completion_tokens", 0)
        tt = get(u, "total_tokens", pt + ct)
        usage = TokenUsage(pt, ct, tt, 0.0)
        _notify_byte_tokens(usage)
    end

    if haskey(data, "choices") && !isempty(data["choices"])
        choice = data["choices"][1]
        msg = get(choice, "message", Dict{String, Any}())
        text = String(get(msg, "content", ""))
        reasoning = String(get(msg, "reasoning", get(msg, "reasoning_content", "")))
        finish_reason = String(get(choice, "finish_reason", "stop"))
        tool_calls = Vector{Dict{String, Any}}(get(msg, "tool_calls", Dict{String, Any}[]))
        return ChatResponse(text, reasoning, req.model, "openrouter", finish_reason, usage, tool_calls, data)
    end

    throw(ProviderServerError("openrouter", 500, "Unexpected empty choices from OpenRouter"))
end

function stream_chat_completion(
    backend::OpenRouterBackend,
    request::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    api_key = _resolve_api_key(backend)
    isempty(api_key) && throw(ProviderAuthError("openrouter", 401, "OpenRouter API key is not set."))

    endpoint = String(get(backend.config, "endpoint", DEFAULT_OPENROUTER_ENDPOINT))
    headers = [
        "Content-Type"  => "application/json",
        "Authorization" => "Bearer $(api_key)",
        "Accept"        => "text/event-stream",
        "HTTP-Referer"  => "http://localhost:8081",
        "X-Title"       => "JL Engine"
    ]

    payload = _build_openrouter_payload(request; stream=true)
    json_bytes = JSON3.write(payload)
    timeout = request.timeout > 0 ? request.timeout : get(backend.config, "timeout", 120)

    accumulated_text = IOBuffer()
    accumulated_reasoning = IOBuffer()
    finish_reason = "stop"
    usage_result = TokenUsage(0, 0, 0, 0.0)
    tool_calls = Dict{String, Any}[]

    try
        HTTP.open("POST", endpoint, headers; readtimeout=timeout) do http
            write(http, json_bytes)
            HTTP.closewrite(http)
            HTTP.startread(http)

            status = http.message.status
            if status != 200
                err_body = read(http, String)
                _throw_typed_http_error("openrouter", status, err_body)
            end

            while !eof(http)
                if cancel_ref[]
                    close(http)
                    throw(ProviderCancelledException("OpenRouter stream cancelled by caller"))
                end

                line = readline(http)
                stripped = strip(line)
                isempty(stripped) && continue
                startswith(stripped, ":") && continue # Comment/keepalive

                if startswith(stripped, "data: ")
                    data_str = strip(stripped[7:end])
                    data_str == "[DONE]" && break

                    chunk_obj = try
                        JSON3.read(data_str)
                    catch
                        continue
                    end

                    # Parse token metrics
                    if haskey(chunk_obj, :usage) && chunk_obj.usage !== nothing
                        u = chunk_obj.usage
                        pt = get(u, :prompt_tokens, 0)
                        ct = get(u, :completion_tokens, 0)
                        tt = get(u, :total_tokens, pt + ct)
                        usage_result = TokenUsage(pt, ct, tt, 0.0)
                        _notify_byte_tokens(usage_result)
                    end

                    # Parse choices delta
                    if haskey(chunk_obj, :choices) && !isempty(chunk_obj.choices)
                        choice = chunk_obj.choices[1]
                        delta = get(choice, :delta, nothing)
                        delta === nothing && continue

                        c_text = ""
                        r_text = ""

                        if haskey(delta, :content) && delta.content !== nothing
                            c_text = String(delta.content)
                            write(accumulated_text, c_text)
                        end

                        if haskey(delta, :reasoning) && delta.reasoning !== nothing
                            r_text = String(delta.reasoning)
                            write(accumulated_reasoning, r_text)
                        elseif haskey(delta, :reasoning_content) && delta.reasoning_content !== nothing
                            r_text = String(delta.reasoning_content)
                            write(accumulated_reasoning, r_text)
                        end

                        f_reason = get(choice, :finish_reason, nothing)
                        f_reason !== nothing && (finish_reason = String(f_reason))

                        # Capture tool calls delta if present
                        if haskey(delta, :tool_calls) && delta.tool_calls !== nothing
                            for tc in delta.tool_calls
                                push!(tool_calls, _materialize_json(tc))
                            end
                        end

                        if !isempty(c_text) || !isempty(r_text) || f_reason !== nothing
                            chunk = StreamChunk(c_text, r_text, f_reason, nothing, nothing)
                            on_chunk(chunk)
                        end
                    end
                end
            end
        end
    catch e
        real_e = e isa HTTP.Exceptions.RequestError ? e.error : e
        if real_e isa ProviderCancelledException || real_e isa ProviderError
            rethrow(real_e)
        elseif real_e isa HTTP.Exceptions.TimeoutError
            throw(ProviderTimeoutError("openrouter", Float64(timeout), "OpenRouter stream timed out"))
        elseif real_e isa Base.IOError || occursin("ConnectError", string(typeof(real_e)))
            throw(ProviderConnectionError("openrouter", "Connection error: $(real_e)"))
        else
            rethrow(real_e)
        end
    end

    full_text = String(take!(accumulated_text))
    full_reasoning = String(take!(accumulated_reasoning))

    # If stream didn't include usage, compute heuristic estimate
    if usage_result.total_tokens == 0
        est_ct = max(1, round(Int, length(full_text) / 3.8))
        est_pt = max(1, round(Int, sum(length(m.content) for m in request.messages) / 3.8))
        usage_result = TokenUsage(est_pt, est_ct, est_pt + est_ct, 0.0)
        _notify_byte_tokens(usage_result)
    end

    return ChatResponse(
        full_text,
        full_reasoning,
        request.model,
        "openrouter",
        finish_reason,
        usage_result,
        tool_calls,
        Dict{String, Any}()
    )
end

function fetch_model_catalog(backend::OpenRouterBackend; force_refresh::Bool=false)::Vector{ModelInfo}
    if !force_refresh && backend.cache.is_valid && (time() - backend.cache.last_fetched < backend.cache.ttl_seconds)
        return backend.cache.models
    end

    url = String(get(backend.config, "models_endpoint", DEFAULT_OPENROUTER_MODELS_ENDPOINT))
    api_key = _resolve_api_key(backend)
    headers = [
        "HTTP-Referer" => "http://localhost:8081",
        "X-Title"      => "JL Engine"
    ]
    !isempty(api_key) && push!(headers, "Authorization" => "Bearer $(api_key)")

    models = ModelInfo[]

    try
        resp = HTTP.get(url, headers; readtimeout=25)
        if resp.status == 200
            data = JSON3.read(String(resp.body))
            if haskey(data, :data) && data.data isa AbstractVector
                for item in data.data
                    id = String(get(item, :id, ""))
                    isempty(id) && continue
                    name = String(get(item, :name, id))
                    ctx = Int(get(item, :context_length, 4096))

                    pricing = get(item, :pricing, nothing)
                    prompt_cost = 0.0
                    comp_cost = 0.0
                    if pricing !== nothing
                        p_str = string(get(pricing, :prompt, "0.0"))
                        c_str = string(get(pricing, :completion, "0.0"))
                        prompt_cost = something(tryparse(Float64, p_str), 0.0) * 1_000_000
                        comp_cost = something(tryparse(Float64, c_str), 0.0) * 1_000_000
                    end

                    arch = get(item, :architecture, nothing)
                    modality = arch !== nothing ? string(get(arch, :modality, "")) : ""
                    supports_vis = occursin("image", modality)
                    desc = String(get(item, :description, ""))
                    supp_params = get(item, :supported_parameters, String[])
                    supp_tools = "tools" in supp_params || "functions" in supp_params

                    push!(models, ModelInfo(
                        id,
                        name,
                        "openrouter",
                        ctx,
                        prompt_cost,
                        comp_cost,
                        true,
                        supp_tools,
                        supports_vis,
                        occursin("deepseek-r1", id) || occursin("thinking", id) || occursin("claude-3.7", id),
                        desc
                    ))
                end
            end
        end
    catch e
        @warn "OpenRouter live catalog query failed, falling back to cache" exception=e
    end

    # If live fetch succeeded, cache in memory and SQLite
    if !isempty(models)
        backend.cache.models = models
        backend.cache.last_fetched = time()
        backend.cache.is_valid = true
        _persist_model_catalog_sqlite(models)
        return models
    end

    # Fallback to SQLite cache
    cached_db_models = _load_model_catalog_sqlite()
    if !isempty(cached_db_models)
        backend.cache.models = cached_db_models
        backend.cache.is_valid = true
        return cached_db_models
    end

    # Fallback to baseline default models
    return [
        ModelInfo("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "openrouter", 64000, 0.14, 0.28, true, true, false, false, "Default OpenRouter model"),
        ModelInfo("anthropic/claude-3.7-sonnet", "Claude 3.7 Sonnet", "openrouter", 200000, 3.0, 15.0, true, true, true, true, "State of the art reasoning model"),
        ModelInfo("openai/gpt-4o", "GPT-4o", "openrouter", 128000, 2.5, 10.0, true, true, true, false, "Omni general-purpose intelligence"),
        ModelInfo("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B Instruct", "openrouter", 131072, 0.12, 0.30, true, true, false, false, "Leading open-weight model"),
    ]
end

function test_connection(backend::OpenRouterBackend)::ConnectionStatus
    api_key = _resolve_api_key(backend)
    endpoint = String(get(backend.config, "endpoint", DEFAULT_OPENROUTER_ENDPOINT))

    if isempty(api_key)
        return ConnectionStatus(false, "openrouter", endpoint, 0.0, "OpenRouter API key is not set", 0)
    end

    auth_url = "https://openrouter.ai/api/v1/auth/key"
    headers = [
        "Authorization" => "Bearer $(api_key)",
        "HTTP-Referer"  => "http://localhost:8081",
        "X-Title"       => "JL Engine"
    ]

    t0 = time_ns()
    try
        resp = HTTP.get(auth_url, headers; readtimeout=10)
        latency = round((time_ns() - t0) / 1e6; digits=2)
        if resp.status == 200
            models = fetch_model_catalog(backend)
            return ConnectionStatus(true, "openrouter", endpoint, latency, nothing, length(models))
        else
            return ConnectionStatus(false, "openrouter", endpoint, latency, "HTTP $(resp.status)", 0)
        end
    catch e
        latency = round((time_ns() - t0) / 1e6; digits=2)
        if e isa HTTP.Exceptions.StatusError
            msg = e.status == 401 ? "Unauthorized: Invalid API key" : "HTTP $(e.status)"
            return ConnectionStatus(false, "openrouter", endpoint, latency, msg, 0)
        else
            return ConnectionStatus(false, "openrouter", endpoint, latency, sprint(showerror, e), 0)
        end
    end
end

# ── 4.3 OllamaBackend ────────────────────────────────────────────────────────

struct OllamaBackend <: AbstractBackend
    config::Dict{String, Any}
end

function chat_completion(backend::OllamaBackend, req::ChatRequest)::ChatResponse
    base_url = String(get(backend.config, "base_url", get(backend.config, "ollama_endpoint", "http://127.0.0.1:11434")))
    endpoint = "$(base_url)/api/chat"
    headers = ["Content-Type" => "application/json"]

    msgs = [Dict{String, Any}("role" => m.role, "content" => m.content) for m in req.messages]
    payload = Dict{String, Any}(
        "model" => req.model,
        "messages" => msgs,
        "stream" => false,
        "options" => Dict{String, Any}(
            "temperature" => req.temperature,
            "top_p" => req.top_p
        )
    )
    req.tools !== nothing && (payload["tools"] = req.tools)

    timeout = req.timeout > 0 ? req.timeout : 60
    resp = try
        HTTP.post(endpoint, headers, JSON.json(payload); readtimeout=timeout)
    catch e
        if e isa Base.IOError || occursin("ConnectError", string(typeof(e)))
            throw(ProviderConnectionError("ollama", "Could not connect to Ollama at $(base_url): $(e)"))
        else
            rethrow(e)
        end
    end

    data = JSON.parse(String(resp.body))
    msg = get(data, "message", Dict{String, Any}())
    content = String(get(msg, "content", ""))
    pt = get(data, "prompt_eval_count", 0)
    ct = get(data, "eval_count", 0)
    usage = TokenUsage(pt, ct, pt + ct, 0.0)
    _notify_byte_tokens(usage)

    return ChatResponse(content, "", req.model, "ollama", "stop", usage, Dict{String, Any}[], data)
end

function stream_chat_completion(
    backend::OllamaBackend,
    req::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    base_url = String(get(backend.config, "base_url", get(backend.config, "ollama_endpoint", "http://127.0.0.1:11434")))
    endpoint = "$(base_url)/api/chat"
    headers = ["Content-Type" => "application/json"]

    msgs = [Dict{String, Any}("role" => m.role, "content" => m.content) for m in req.messages]
    payload = Dict{String, Any}(
        "model" => req.model,
        "messages" => msgs,
        "stream" => true,
        "options" => Dict{String, Any}(
            "temperature" => req.temperature,
            "top_p" => req.top_p
        )
    )

    accumulated = IOBuffer()
    timeout = req.timeout > 0 ? req.timeout : 60
    usage = TokenUsage(0, 0, 0, 0.0)

    try
        HTTP.open("POST", endpoint, headers; readtimeout=timeout) do http
            write(http, JSON.json(payload))
            HTTP.closewrite(http)
            HTTP.startread(http)

            while !eof(http)
                if cancel_ref[]
                    close(http)
                    throw(ProviderCancelledException("Ollama stream cancelled"))
                end

                line = readline(http)
                isempty(strip(line)) && continue
                parsed = try JSON.parse(line) catch; continue end

                msg = get(parsed, "message", Dict())
                c = get(msg, "content", "")
                if !isempty(c)
                    write(accumulated, c)
                    on_chunk(StreamChunk(c, "", nothing, nothing, nothing))
                end

                if get(parsed, "done", false)
                    pt = get(parsed, "prompt_eval_count", 0)
                    ct = get(parsed, "eval_count", 0)
                    usage = TokenUsage(pt, ct, pt + ct, 0.0)
                    _notify_byte_tokens(usage)
                    break
                end
            end
        end
    catch e
        real_e = e isa HTTP.Exceptions.RequestError ? e.error : e
        if real_e isa ProviderCancelledException || real_e isa ProviderError
            rethrow(real_e)
        elseif real_e isa HTTP.Exceptions.TimeoutError
            throw(ProviderTimeoutError("ollama", 30.0, "Ollama stream timed out"))
        elseif real_e isa Base.IOError || occursin("ConnectError", string(typeof(real_e)))
            throw(ProviderConnectionError("ollama", "Could not connect to Ollama at $(base_url): $(real_e)"))
        else
            rethrow(real_e)
        end
    end

    full_text = String(take!(accumulated))
    return ChatResponse(full_text, "", req.model, "ollama", "stop", usage, Dict{String, Any}[], Dict{String, Any}())
end

function fetch_model_catalog(backend::OllamaBackend; force_refresh::Bool=false)::Vector{ModelInfo}
    base_url = String(get(backend.config, "base_url", get(backend.config, "ollama_endpoint", "http://127.0.0.1:11434")))
    url = "$(base_url)/api/tags"

    try
        resp = HTTP.get(url; readtimeout=5)
        if resp.status == 200
            data = JSON.parse(String(resp.body))
            models = ModelInfo[]
            for m in get(data, "models", [])
                name = String(get(m, "name", ""))
                isempty(name) && continue
                push!(models, ModelInfo(name, name, "ollama", 8192, 0.0, 0.0, true, true, false, false, "Local Ollama model"))
            end
            return models
        end
    catch
    end
    return [ModelInfo("llama3", "Llama 3", "ollama", 8192, 0.0, 0.0, true, true, false, false, "Local Ollama model")]
end

function test_connection(backend::OllamaBackend)::ConnectionStatus
    base_url = String(get(backend.config, "base_url", get(backend.config, "ollama_endpoint", "http://127.0.0.1:11434")))
    t0 = time_ns()
    try
        resp = HTTP.get("$(base_url)/api/tags"; readtimeout=5)
        lat = round((time_ns() - t0) / 1e6; digits=2)
        if resp.status == 200
            models = fetch_model_catalog(backend)
            return ConnectionStatus(true, "ollama", base_url, lat, nothing, length(models))
        end
        return ConnectionStatus(false, "ollama", base_url, lat, "HTTP $(resp.status)", 0)
    catch e
        lat = round((time_ns() - t0) / 1e6; digits=2)
        return ConnectionStatus(false, "ollama", base_url, lat, sprint(showerror, e), 0)
    end
end

# ── 4.4 GoogleGeminiBackend ──────────────────────────────────────────────────

struct GoogleGeminiBackend <: AbstractBackend
    config::Dict{String, Any}
end

function _gemini_api_key(backend::GoogleGeminiBackend)::String
    k = get(backend.config, "api_key", nothing)
    k !== nothing && !isempty(String(k)) && return String(k)
    return get(ENV, "GEMINI_API_KEY", get(ENV, "GOOGLE_API_KEY", ""))
end

function chat_completion(backend::GoogleGeminiBackend, req::ChatRequest)::ChatResponse
    key = _gemini_api_key(backend)
    isempty(key) && throw(ProviderAuthError("gemini", 401, "Google Gemini API key is not set."))

    endpoint_base = String(get(backend.config, "endpoint", "https://generativelanguage.googleapis.com/v1beta"))
    model_id = req.model
    !startswith(model_id, "models/") && (model_id = "models/" * model_id)
    url = "$(endpoint_base)/$(model_id):generateContent?key=$(key)"

    # Format Gemini alternating turns and extract system instructions
    contents = Any[]
    system_text = ""
    for m in req.messages
        if m.role == "system"
            system_text = isempty(system_text) ? m.content : system_text * "\n" * m.content
        else
            role = m.role == "assistant" ? "model" : "user"
            push!(contents, Dict("role" => role, "parts" => [Dict("text" => m.content)]))
        end
    end

    payload = Dict{String, Any}("contents" => contents)
    if !isempty(system_text)
        payload["systemInstruction"] = Dict("parts" => [Dict("text" => system_text)])
    end
    payload["generationConfig"] = Dict{String, Any}(
        "temperature" => req.temperature,
        "topP" => req.top_p
    )

    resp = try
        HTTP.post(url, ["Content-Type" => "application/json"], JSON.json(payload); readtimeout=req.timeout)
    catch e
        if e isa HTTP.Exceptions.StatusError
            _throw_typed_http_error("gemini", e.status, String(e.response.body))
        else
            rethrow(e)
        end
    end

    data = JSON.parse(String(resp.body))
    candidates = get(data, "candidates", [])
    text = ""
    reasoning = ""
    if !isempty(candidates)
        content_obj = get(candidates[1], "content", Dict())
        for part in get(content_obj, "parts", [])
            if get(part, "thought", false) == true
                reasoning *= get(part, "text", "")
            else
                text *= get(part, "text", "")
            end
        end
    end

    usage_meta = get(data, "usageMetadata", Dict())
    pt = get(usage_meta, "promptTokenCount", 0)
    ct = get(usage_meta, "candidatesTokenCount", 0)
    usage = TokenUsage(pt, ct, pt + ct, 0.0)
    _notify_byte_tokens(usage)

    return ChatResponse(text, reasoning, req.model, "gemini", "stop", usage, Dict{String, Any}[], data)
end

function stream_chat_completion(
    backend::GoogleGeminiBackend,
    req::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    # Fallback to chat_completion with simulated chunking for Gemini if SSE endpoint isn't wired
    resp = chat_completion(backend, req)
    words = split(resp.text, " ")
    for (i, w) in enumerate(words)
        if cancel_ref[]
            throw(ProviderCancelledException("Gemini stream cancelled"))
        end
        token = i == length(words) ? w : w * " "
        on_chunk(StreamChunk(token, "", i == length(words) ? "stop" : nothing, nothing, nothing))
    end
    return resp
end

function fetch_model_catalog(backend::GoogleGeminiBackend; force_refresh::Bool=false)::Vector{ModelInfo}
    return [
        ModelInfo("gemini-2.0-flash", "Gemini 2.0 Flash", "gemini", 1048576, 0.10, 0.40, true, true, true, true, "Next gen multimodal fast model"),
        ModelInfo("gemini-1.5-pro", "Gemini 1.5 Pro", "gemini", 2097152, 1.25, 5.00, true, true, true, true, "Complex multimodal reasoning"),
    ]
end

function test_connection(backend::GoogleGeminiBackend)::ConnectionStatus
    key = _gemini_api_key(backend)
    endpoint = String(get(backend.config, "endpoint", "https://generativelanguage.googleapis.com/v1beta"))
    if isempty(key)
        return ConnectionStatus(false, "gemini", endpoint, 0.0, "Gemini API key is not set", 0)
    end
    t0 = time_ns()
    try
        url = "$(endpoint)/models?key=$(key)"
        resp = HTTP.get(url; readtimeout=10)
        lat = round((time_ns() - t0) / 1e6; digits=2)
        if resp.status == 200
            return ConnectionStatus(true, "gemini", endpoint, lat, nothing, 2)
        end
        return ConnectionStatus(false, "gemini", endpoint, lat, "HTTP $(resp.status)", 0)
    catch e
        lat = round((time_ns() - t0) / 1e6; digits=2)
        return ConnectionStatus(false, "gemini", endpoint, lat, sprint(showerror, e), 0)
    end
end

# ── 4.5 CustomHTTPBackend ────────────────────────────────────────────────────

struct CustomHTTPBackend <: AbstractBackend
    config::Dict{String, Any}
end

function chat_completion(backend::CustomHTTPBackend, req::ChatRequest)::ChatResponse
    endpoint = String(get(backend.config, "endpoint", get(backend.config, "base_url", "")))
    isempty(endpoint) && throw(ProviderConnectionError("custom", "Endpoint URL is required for CustomHTTPBackend"))

    api_key = String(get(backend.config, "api_key", ""))
    headers = ["Content-Type" => "application/json"]
    !isempty(api_key) && push!(headers, "Authorization" => "Bearer $(api_key)")

    payload = _build_openrouter_payload(req; stream=false)
    resp = HTTP.post(endpoint, headers, JSON.json(payload); readtimeout=req.timeout)
    data = JSON.parse(String(resp.body))

    text = ""
    if haskey(data, "choices") && !isempty(data["choices"])
        msg = get(data["choices"][1], "message", Dict())
        text = String(get(msg, "content", ""))
    end
    usage = TokenUsage(10, 10, 20, 0.0)
    return ChatResponse(text, "", req.model, "custom", "stop", usage, Dict{String, Any}[], data)
end

function stream_chat_completion(
    backend::CustomHTTPBackend,
    req::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    resp = chat_completion(backend, req)
    words = split(resp.text, " ")
    for (i, w) in enumerate(words)
        if cancel_ref[]
            throw(ProviderCancelledException("CustomHTTP stream cancelled"))
        end
        token = i == length(words) ? w : w * " "
        on_chunk(StreamChunk(token, "", i == length(words) ? "stop" : nothing, nothing, nothing))
    end
    return resp
end

function fetch_model_catalog(backend::CustomHTTPBackend; force_refresh::Bool=false)::Vector{ModelInfo}
    m = String(get(backend.config, "model", "custom-model"))
    return [ModelInfo(m, m, "custom", 8192, 0.0, 0.0, true, true, false, false, "Custom HTTP endpoint")]
end

function test_connection(backend::CustomHTTPBackend)::ConnectionStatus
    endpoint = String(get(backend.config, "endpoint", get(backend.config, "base_url", "")))
    return ConnectionStatus(!isempty(endpoint), "custom", endpoint, 1.0, isempty(endpoint) ? "Missing endpoint" : nothing, 1)
end

# ── 5. FallbackChain & Circuit Breaker Architecture ──────────────────────────

@enum CircuitState CIRCUIT_CLOSED CIRCUIT_OPEN CIRCUIT_HALF_OPEN

mutable struct CircuitBreaker
    state::CircuitState
    consecutive_failures::Int
    failure_threshold::Int          # Default: 3
    cooldown_s::Float64             # Default: 60.0
    last_failure_time::Float64
    last_state_change::Float64

    CircuitBreaker(; threshold=3, cooldown=60.0) =
        new(CIRCUIT_CLOSED, 0, threshold, cooldown, 0.0, time())
end

struct ProviderTarget
    backend_id::String
    model_override::Union{Nothing, String}
    timeout_s::Float64
    max_retries::Int

    ProviderTarget(id::String; model_override=nothing, timeout_s=120.0, max_retries=1) =
        new(id, model_override, timeout_s, max_retries)
end

struct FallbackChain <: AbstractBackend
    id::String
    targets::Vector{ProviderTarget}
    breakers::Dict{String, CircuitBreaker}
    history::Vector{Dict{String, Any}}
    lock::ReentrantLock

    FallbackChain(id::String, targets::Vector{ProviderTarget}) =
        new(id, targets, Dict{String, CircuitBreaker}(), Dict{String, Any}[], ReentrantLock())
end

function _get_breaker!(chain::FallbackChain, backend_id::String)::CircuitBreaker
    lock(chain.lock) do
        if !haskey(chain.breakers, backend_id)
            chain.breakers[backend_id] = CircuitBreaker()
        end
        return chain.breakers[backend_id]
    end
end

function chat_completion(chain::FallbackChain, req::ChatRequest)::ChatResponse
    last_err = nothing
    for target in chain.targets
        breaker = _get_breaker!(chain, target.backend_id)
        now_t = time()

        # Check circuit state
        if breaker.state == CIRCUIT_OPEN
            if now_t - breaker.last_failure_time > breaker.cooldown_s
                breaker.state = CIRCUIT_HALF_OPEN
            else
                @warn "FallbackChain: Provider $(target.backend_id) circuit is OPEN; skipping."
                continue
            end
        end

        backend = get_backend(target.backend_id)
        effective_model = target.model_override !== nothing ? target.model_override : req.model
        target_req = ChatRequest(
            effective_model,
            req.messages;
            temperature=req.temperature,
            top_p=req.top_p,
            max_tokens=req.max_tokens,
            reasoning_effort=req.reasoning_effort,
            tools=req.tools,
            timeout=round(Int, target.timeout_s),
            stream=false
        )

        try
            resp = chat_completion(backend, target_req)
            # Success: reset circuit breaker
            breaker.state = CIRCUIT_CLOSED
            breaker.consecutive_failures = 0
            return resp
        catch e
            last_err = e
            breaker.consecutive_failures += 1
            breaker.last_failure_time = time()
            if breaker.consecutive_failures >= breaker.failure_threshold || e isa ProviderAuthError
                breaker.state = CIRCUIT_OPEN
            end
            @warn "FallbackChain target $(target.backend_id) failed" error=e
            push!(chain.history, Dict(
                "timestamp" => string(now()),
                "target" => target.backend_id,
                "error" => sprint(showerror, e)
            ))
        end
    end

    last_err !== nothing && throw(last_err)
    throw(ProviderServerError(chain.id, 500, "All providers in FallbackChain $(chain.id) exhausted."))
end

function stream_chat_completion(
    chain::FallbackChain,
    req::ChatRequest,
    on_chunk::Function;
    cancel_ref::Ref{Bool}=Ref(false)
)::ChatResponse
    tokens_emitted = Ref(0)
    last_err = nothing

    for target in chain.targets
        breaker = _get_breaker!(chain, target.backend_id)
        now_t = time()

        if breaker.state == CIRCUIT_OPEN
            if now_t - breaker.last_failure_time > breaker.cooldown_s
                breaker.state = CIRCUIT_HALF_OPEN
            else
                continue
            end
        end

        backend = get_backend(target.backend_id)
        effective_model = target.model_override !== nothing ? target.model_override : req.model
        target_req = ChatRequest(
            effective_model,
            req.messages;
            temperature=req.temperature,
            top_p=req.top_p,
            max_tokens=req.max_tokens,
            reasoning_effort=req.reasoning_effort,
            tools=req.tools,
            timeout=round(Int, target.timeout_s),
            stream=true
        )

        wrapped_on_chunk = (chunk::StreamChunk) -> begin
            tokens_emitted[] += 1
            on_chunk(chunk)
        end

        try
            resp = stream_chat_completion(backend, target_req, wrapped_on_chunk; cancel_ref=cancel_ref)
            breaker.state = CIRCUIT_CLOSED
            breaker.consecutive_failures = 0
            return resp
        catch e
            inner_err = e isa HTTP.Exceptions.RequestError ? e.error : e
            if inner_err isa ProviderCancelledException
                rethrow(inner_err)
            end

            last_err = e
            breaker.consecutive_failures += 1
            breaker.last_failure_time = time()
            if breaker.consecutive_failures >= breaker.failure_threshold || e isa ProviderAuthError || inner_err isa ProviderAuthError
                breaker.state = CIRCUIT_OPEN
            end

            # If tokens were already sent to client, failover mid-sentence is unsafe
            if tokens_emitted[] > 0
                throw(ProviderStreamInterruptedError(target.backend_id, "Stream interrupted after emitting $(tokens_emitted[]) tokens: $(e)", ""))
            end

            @warn "FallbackChain streaming target $(target.backend_id) failed before token emission; falling over." error=e
        end
    end

    last_err !== nothing && throw(last_err)
    throw(ProviderServerError(chain.id, 500, "All streaming targets exhausted"))
end

function fetch_model_catalog(chain::FallbackChain; force_refresh::Bool=false)::Vector{ModelInfo}
    if !isempty(chain.targets)
        primary = get_backend(chain.targets[1].backend_id)
        return fetch_model_catalog(primary; force_refresh=force_refresh)
    end
    return ModelInfo[]
end

function test_connection(chain::FallbackChain)::ConnectionStatus
    if !isempty(chain.targets)
        primary = get_backend(chain.targets[1].backend_id)
        return test_connection(primary)
    end
    return ConnectionStatus(false, chain.id, "none", 0.0, "Empty FallbackChain", 0)
end

# ── 6. Global Backend Registry & Backward Compatibility ──────────────────────

const BACKEND_REGISTRY = Dict{String, Dict{String, Any}}(
    "noop-stub" => Dict{String, Any}(
        "id" => "noop-stub",
        "label" => "Stub (No backend)",
        "provider" => "noop",
    ),
    "openrouter" => Dict{String, Any}(
        "id" => "openrouter",
        "label" => "OpenRouter",
        "provider" => "openrouter",
        "endpoint" => DEFAULT_OPENROUTER_ENDPOINT,
        "models_endpoint" => DEFAULT_OPENROUTER_MODELS_ENDPOINT,
        "model" => DEFAULT_OPENROUTER_MODEL,
        "api_key" => nothing,
        "timeout" => 120,
    ),
    "ollama" => Dict{String, Any}(
        "id" => "ollama",
        "label" => "Ollama (Local)",
        "provider" => "ollama",
        "base_url" => "http://127.0.0.1:11434",
        "model" => "llama3",
        "timeout" => 60,
    ),
    "gemini" => Dict{String, Any}(
        "id" => "gemini",
        "label" => "Google Gemini",
        "provider" => "gemini",
        "model" => "gemini-2.0-flash",
        "endpoint" => "https://generativelanguage.googleapis.com/v1beta",
    ),
)

const ACTIVE_BACKENDS = Dict{String, String}(
    "current" => "openrouter",
    "brain" => "openrouter",
    "tool" => "openrouter",
)

function set_backend_model!(backend_id::AbstractString, model_name::AbstractString)
    haskey(BACKEND_REGISTRY, backend_id) || return
    BACKEND_REGISTRY[String(backend_id)]["modelName"] = String(model_name)
    BACKEND_REGISTRY[String(backend_id)]["model_name"] = String(model_name)
    BACKEND_REGISTRY[String(backend_id)]["model"] = String(model_name)
end

function configure_backends!(; brain_id=nothing, tool_id=nothing)
    brain_id !== nothing && set_brain_backend_id!(String(brain_id))
    tool_id !== nothing && set_tool_backend_id!(String(tool_id))
    return ACTIVE_BACKENDS
end

function set_brain_backend_id!(backend_id::AbstractString)
    haskey(BACKEND_REGISTRY, backend_id) || return ACTIVE_BACKENDS
    ACTIVE_BACKENDS["brain"] = String(backend_id)
    ACTIVE_BACKENDS["current"] = String(backend_id)
    return ACTIVE_BACKENDS
end

function set_tool_backend_id!(backend_id::AbstractString)
    haskey(BACKEND_REGISTRY, backend_id) || return ACTIVE_BACKENDS
    ACTIVE_BACKENDS["tool"] = String(backend_id)
    return ACTIVE_BACKENDS
end

function get_backend(backend_id::Union{Nothing, AbstractString}=nothing; overrides=nothing)::AbstractBackend
    target_id = backend_id === nothing ? ACTIVE_BACKENDS["current"] : String(backend_id)
    config = deepcopy(get(BACKEND_REGISTRY, target_id, BACKEND_REGISTRY["noop-stub"]))
    if overrides isa AbstractDict
        merge!(config, Dict{String, Any}(string(key) => value for (key, value) in pairs(overrides)))
    end
    provider = String(get(config, "provider", "noop"))
    if provider == "openrouter"
        return OpenRouterBackend(config)
    elseif provider == "ollama"
        return OllamaBackend(config)
    elseif provider == "gemini"
        return GoogleGeminiBackend(config)
    elseif provider == "custom"
        return CustomHTTPBackend(config)
    end
    return NoopBackend(config)
end

get_brain_backend() = get_backend(ACTIVE_BACKENDS["brain"])
get_tool_backend() = get_backend(ACTIVE_BACKENDS["tool"])

function _message_content(messages)
    for message in Iterators.reverse(messages)
        if message isa AbstractDict && get(message, "role", nothing) == "user"
            return String(get(message, "content", ""))
        end
    end
    return ""
end

"""
    generate(backend::AbstractBackend, messages; options=Dict{String, Any}(), timeout=nothing)

Legacy wrapper delegating to modern typed `chat_completion` while maintaining exact
return format `(reply_text, meta_dict)` for Core.jl and historical callers.
"""
function generate(backend::AbstractBackend, messages; options=Dict{String, Any}(), timeout=nothing)
    req_messages = ChatMessage[]
    for m in messages
        if m isa AbstractDict
            r = String(get(m, "role", "user"))
            c = String(get(m, "content", ""))
            push!(req_messages, ChatMessage(r, c))
        elseif m isa ChatMessage
            push!(req_messages, m)
        end
    end

    model_name = String(get(backend.config, "model", get(backend.config, "model_name", DEFAULT_OPENROUTER_MODEL)))
    temp = Float64(get(options, "temperature", 0.7))
    top_p = Float64(get(options, "top_p", 0.95))
    max_toks = haskey(options, "max_tokens") ? Int(options["max_tokens"]) : nothing
    req_timeout = timeout !== nothing ? Int(timeout) : get(backend.config, "timeout", 120)

    req = ChatRequest(
        model_name,
        req_messages;
        temperature=temp,
        top_p=top_p,
        max_tokens=max_toks,
        timeout=req_timeout,
        stream=false
    )

    try
        resp = chat_completion(backend, req)
        meta = Dict{String, Any}(
            "provider" => resp.provider,
            "status" => "ok",
            "model" => resp.model,
            "finish_reason" => resp.finish_reason,
            "usage" => Dict(
                "prompt_tokens" => resp.usage.prompt_tokens,
                "completion_tokens" => resp.usage.completion_tokens,
                "total_tokens" => resp.usage.total_tokens
            )
        )
        return resp.text, meta
    catch exc
        err_msg = exc isa ProviderError ? exc.message : sprint(showerror, exc)
        return "[ERROR: Backend returned an error. Details: $(err_msg)]", Dict{String, Any}("error" => err_msg)
    end
end
