using JSON3
using JSON
using SQLite
using Dates

export validate_config_field,
    sync_env_file!,
    init_config_table!,
    db_set_config!,
    db_get_config,
    db_get_all_config,
    load_config,
    update_config!,
    get_current_config,
    get_config_dict,
    ConfigManager,
    copy_with

# ── JSON & Path Helper Utilities (Backward Compatibility) ────────────────────

function _materialize_json(value)
    if value isa JSON3.Object
        return Dict{String, Any}(String(key) => _materialize_json(item) for (key, item) in pairs(value))
    elseif value isa JSON3.Array
        return [_materialize_json(item) for item in value]
    elseif value isa AbstractDict
        return Dict{String, Any}(string(key) => _materialize_json(item) for (key, item) in pairs(value))
    elseif value isa AbstractVector
        return [_materialize_json(item) for item in value]
    end
    return value
end

function load_json_safely(path::AbstractString)
    if !isfile(path)
        return Dict{String, Any}()
    end

    text = read(path, String)
    text = replace(text, "\ufeff" => "")
    if isempty(strip(text))
        return Dict{String, Any}()
    end

    try
        return _materialize_json(JSON3.read(text))
    catch
        return Dict{String, Any}()
    end
end

function resolve_path(root_dir::AbstractString, path::AbstractString)
    return isabspath(path) ? path : normpath(joinpath(root_dir, path))
end

function load_engine_config(path::AbstractString)
    blob = load_json_safely(path)
    jl_blob = get(blob, "jl_engine", Dict{String, Any}())
    if jl_blob isa AbstractDict
        return Dict{String, Any}(string(key) => value for (key, value) in pairs(jl_blob))
    end
    return Dict{String, Any}()
end

# ── Field Mapping & Metadata ──────────────────────────────────────────────────

const ENV_FIELD_MAP = Dict{Symbol, String}(
    :current_model       => "DEFAULT_OPENROUTER_MODEL",
    :brain_model         => "BRAIN_MODEL",
    :tool_model          => "TOOL_MODEL",
    :reviewer_model      => "REVIEWER_MODEL",
    :fallback_models     => "FALLBACK_MODELS",
    :active_provider     => "ACTIVE_PROVIDER",
    :openrouter_endpoint => "DEFAULT_OPENROUTER_ENDPOINT",
    :openrouter_timeout  => "OPENROUTER_TIMEOUT",
    :ollama_endpoint     => "OLLAMA_BASE_URL",
    :gemini_endpoint     => "GEMINI_ENDPOINT",
    :default_temperature => "DEFAULT_TEMPERATURE",
    :default_top_p       => "DEFAULT_TOP_P",
    :max_tokens          => "MAX_TOKENS",
    :reasoning_effort    => "REASONING_EFFORT",
    :host                => "SPARKBYTE_HOST",
    :port                => "SPARKBYTE_PORT",
    :debug_mode          => "SPARKBYTE_DEBUG",
    :log_level           => "SPARKBYTE_LOG_LEVEL",
)

const BOOTSTRAP_ENV_FIELDS = Set{Symbol}([
    :current_model,
    :active_provider,
    :openrouter_endpoint,
    :ollama_endpoint,
    :host,
    :port,
    :debug_mode,
])

const FIELD_CATEGORY_MAP = Dict{Symbol, String}(
    :current_model       => "model",
    :brain_model         => "model",
    :tool_model          => "model",
    :reviewer_model      => "model",
    :fallback_models     => "model",
    :active_provider     => "provider",
    :openrouter_endpoint => "provider",
    :openrouter_timeout  => "provider",
    :ollama_endpoint     => "provider",
    :gemini_endpoint     => "provider",
    :default_temperature => "sampling",
    :default_top_p       => "sampling",
    :max_tokens          => "sampling",
    :reasoning_effort    => "sampling",
    :host                => "network",
    :port                => "network",
    :debug_mode          => "runtime",
    :log_level           => "runtime",
    :root_dir            => "legacy",
    :master_file         => "legacy",
    :behavior_states_file=> "legacy",
    :signal_lexicon_file => "legacy",
    :mpf_registry_file   => "legacy",
    :agents_dir          => "legacy",
    :safety_on           => "legacy",
    :default_agent_name  => "legacy",
    :history_length      => "legacy",
)

const CREDENTIAL_ENV_MAP = Dict{Symbol, String}(
    :openrouter_api_key => "OPENROUTER_API_KEY",
    :gemini_api_key     => "GEMINI_API_KEY",
    :openai_api_key     => "OPENAI_API_KEY",
    :xai_api_key        => "XAI_API_KEY",
    :cerebras_api_key   => "CEREBRAS_API_KEY",
    :github_token       => "GITHUB_TOKEN",
)

# ── Validation ────────────────────────────────────────────────────────────────

"""
    validate_config_field(key::Symbol, value)::Tuple{Bool, String}

Validates a configuration key and its candidate value. Returns (true, "") on success,
or (false, error_message) on violation.
"""
function validate_config_field(key::Symbol, value)::Tuple{Bool, String}
    if haskey(CREDENTIAL_ENV_MAP, key)
        (value isa AbstractString && !isempty(strip(value))) || return (false, "$key must be a non-empty string")
    elseif key in (:current_model, :brain_model, :tool_model, :reviewer_model)
        (value isa AbstractString && !isempty(strip(value))) || return (false, "$key must be a non-empty string")
    elseif key == :fallback_models
        if value isa AbstractVector
            all(x -> x isa AbstractString && !isempty(strip(x)), value) || return (false, "all fallback models must be non-empty strings")
        else
            return (false, "fallback_models must be a vector of strings")
        end
    elseif key == :active_provider
        val_str = lowercase(string(value))
        val_str in ("openrouter", "ollama", "gemini", "openai", "custom", "noop") || return (false, "active_provider must be one of: openrouter, ollama, gemini, openai, custom, noop")
    elseif key in (:openrouter_endpoint, :ollama_endpoint, :gemini_endpoint)
        (value isa AbstractString && (startswith(value, "http://") || startswith(value, "https://"))) || return (false, "$key must be a valid HTTP or HTTPS URL")
    elseif key == :openrouter_timeout
        (value isa Integer && value > 0 && value <= 600) || return (false, "openrouter_timeout must be an integer between 1 and 600 seconds")
    elseif key == :default_temperature
        (value isa Real && value >= 0.0 && value <= 2.0) || return (false, "default_temperature must be a real number between 0.0 and 2.0")
    elseif key == :default_top_p
        (value isa Real && value >= 0.0 && value <= 1.0) || return (false, "default_top_p must be a real number between 0.0 and 1.0")
    elseif key == :max_tokens
        (value isa Integer && value >= 1 && value <= 128000) || return (false, "max_tokens must be an integer between 1 and 128000")
    elseif key == :reasoning_effort
        val_str = lowercase(string(value))
        val_str in ("none", "low", "medium", "high") || return (false, "reasoning_effort must be one of: none, low, medium, high")
    elseif key == :host
        (value isa AbstractString && !isempty(strip(value))) || return (false, "host must be a non-empty string (e.g. 127.0.0.1)")
    elseif key == :port
        (value isa Integer && value >= 1024 && value <= 65535) || return (false, "port must be an integer between 1024 and 65535")
    elseif key == :debug_mode
        value isa Bool || return (false, "debug_mode must be a boolean")
    elseif key == :log_level
        val_str = lowercase(string(value))
        val_str in ("debug", "info", "warn", "error") || return (false, "log_level must be one of: debug, info, warn, error")
    elseif key in (:root_dir, :master_file, :behavior_states_file, :signal_lexicon_file, :mpf_registry_file, :agents_dir, :default_agent_name)
        (value isa AbstractString && !isempty(strip(value))) || return (false, "$key must be a non-empty string")
    elseif key == :safety_on
        value isa Bool || return (false, "safety_on must be a boolean")
    elseif key == :history_length
        (value isa Integer && value >= 1) || return (false, "history_length must be a positive integer")
    else
        return (false, "Unknown configuration field: $key")
    end
    return (true, "")
end

# ── Comment-Preserving .env Synchronization ───────────────────────────────────

function _format_env_value(val::AbstractString)::String
    if occursin(" ", val) || occursin("#", val) || occursin("\"", val) || occursin("'", val)
        escaped = replace(val, "\"" => "\\\"")
        return "\"$escaped\""
    end
    return val
end

"""
    sync_env_file!(env_path::AbstractString, updates::AbstractDict{<:AbstractString, <:AbstractString})::Bool

Atomically update `.env` with new key-value pairs while strictly preserving
existing comments, empty lines, and indentation.
"""
function sync_env_file!(env_path::AbstractString, updates::AbstractDict{<:AbstractString, <:AbstractString})::Bool
    lines = isfile(env_path) ? readlines(env_path) : String[]
    remaining_keys = Dict{String, String}(String(k) => String(v) for (k, v) in updates)
    new_lines = String[]
    key_regex = r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$"

    for line in lines
        stripped = strip(line)
        if isempty(stripped) || startswith(stripped, "#")
            push!(new_lines, line)
            continue
        end

        m = match(key_regex, stripped)
        if m !== nothing
            k = m[1]
            if haskey(remaining_keys, k)
                val = remaining_keys[k]
                formatted_val = _format_env_value(val)
                push!(new_lines, "$k=$formatted_val")
                delete!(remaining_keys, k)
            else
                push!(new_lines, line)
            end
        else
            push!(new_lines, line)
        end
    end

    if !isempty(remaining_keys)
        push!(new_lines, "")
        push!(new_lines, "# ── Dynamic Runtime Configuration Updates ──────────────────────────")
        for (k, val) in remaining_keys
            push!(new_lines, "$k=$(_format_env_value(val))")
        end
    end

    dir = dirname(env_path)
    isempty(dir) && (dir = ".")
    tmp_path = joinpath(dir, ".env.tmp.$(getpid()).$(time_ns())")
    try
        open(tmp_path, "w") do io
            for l in new_lines
                println(io, l)
            end
            flush(io)
        end
        mv(tmp_path, env_path; force=true)
        return true
    catch e
        isfile(tmp_path) && rm(tmp_path; force=true)
        @error "Failed to atomically update .env" exception=(e, catch_backtrace())
        return false
    end
end

# ── SQLite Persistence ────────────────────────────────────────────────────────

"""
    init_config_table!(db::SQLite.DB)

Initializes authoritative `config` and audit `config_history` tables in SQLite.
"""
function init_config_table!(db::SQLite.DB)
    SQLite.execute(db, """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY NOT NULL,
            value_json TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'global',
            category TEXT NOT NULL DEFAULT 'general',
            description TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
    """)
    SQLite.execute(db, "CREATE INDEX IF NOT EXISTS idx_config_scope ON config(scope);")
    SQLite.execute(db, "CREATE INDEX IF NOT EXISTS idx_config_category ON config(category);")

    SQLite.execute(db, """
        CREATE TABLE IF NOT EXISTS config_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            old_value_json TEXT,
            new_value_json TEXT NOT NULL,
            scope TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    SQLite.execute(db, "CREATE INDEX IF NOT EXISTS idx_config_history_key ON config_history(key);")
end

function db_get_config(db::SQLite.DB, key::String; default=nothing)
    rows = [String(row[1]) for row in SQLite.DBInterface.execute(db, "SELECT value_json FROM config WHERE key = ? LIMIT 1", (key,))]
    if !isempty(rows)
        raw_val = rows[1]
        try
            return _materialize_json(JSON3.read(raw_val))
        catch
            return raw_val
        end
    end
    return default
end

function db_get_all_config(db::SQLite.DB)::Dict{String, Any}
    result = Dict{String, Any}()
    for row in SQLite.DBInterface.execute(db, "SELECT key, value_json FROM config")
        k = String(row[1])
        v_str = String(row[2])
        val = try
            _materialize_json(JSON3.read(v_str))
        catch
            v_str
        end
        result[k] = val
    end
    return result
end

function db_set_config!(
    db::SQLite.DB,
    key::String,
    value_json::String;
    scope::String="global",
    category::String="general",
    source::String="api"
)
    now_utc = string(Dates.now(Dates.UTC))
    SQLite.transaction(db) do
        rows = [String(row[1]) for row in SQLite.DBInterface.execute(db, "SELECT value_json FROM config WHERE key = ? LIMIT 1", (key,))]
        old_val = !isempty(rows) ? rows[1] : nothing

        SQLite.execute(db, """
            INSERT INTO config (key, value_json, scope, category, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                scope = excluded.scope,
                category = excluded.category,
                updated_at = excluded.updated_at
        """, (key, value_json, scope, category, now_utc))

        # Redact secrets from audit log if sensitive
        history_new_val = occursin("key", lowercase(key)) || occursin("token", lowercase(key)) ? "\"[REDACTED]\"" : value_json
        history_old_val = old_val !== nothing && (occursin("key", lowercase(key)) || occursin("token", lowercase(key))) ? "\"[REDACTED]\"" : old_val

        SQLite.execute(db, """
            INSERT INTO config_history (key, old_value_json, new_value_json, scope, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, history_old_val, history_new_val, scope, source, now_utc))
    end

    try
        if hasfield(typeof(db), :file) && db.file != ":memory:" && !isempty(db.file)
            SQLite.execute(db, "PRAGMA wal_checkpoint(PASSIVE);")
        end
    catch e
        @warn "Passive WAL checkpoint skipped" exception=e
    end
end

# ── Config Manager & Concurrency Safety ───────────────────────────────────────

"""
    copy_with(cfg::EngineConfig; kwargs...)::EngineConfig

Returns a new immutable EngineConfig with the specified field overrides.
"""
function copy_with(cfg::EngineConfig; kwargs...)::EngineConfig
    d = Dict{Symbol, Any}(f => getfield(cfg, f) for f in fieldnames(EngineConfig))
    for (k, v) in kwargs
        d[Symbol(k)] = v
    end
    return EngineConfig(; d...)
end

function copy_with(cfg::EngineConfig, overrides::Pair{Symbol, <:Any}...)::EngineConfig
    d = Dict{Symbol, Any}(f => getfield(cfg, f) for f in fieldnames(EngineConfig))
    for (k, v) in overrides
        d[k] = v
    end
    return EngineConfig(; d...)
end

function copy_with(cfg::EngineConfig, overrides::AbstractDict)::EngineConfig
    d = Dict{Symbol, Any}(f => getfield(cfg, f) for f in fieldnames(EngineConfig))
    for (k, v) in overrides
        d[Symbol(k)] = v
    end
    return EngineConfig(; d...)
end

mutable struct ConfigManager
    current::Ref{EngineConfig}
    lock::ReentrantLock
    db::Union{Nothing, SQLite.DB}
    env_path::String
end

const GLOBAL_CONFIG_MANAGER = Ref{Union{Nothing, ConfigManager}}(nothing)

"""
    load_config(db::Union{Nothing, SQLite.DB}, env_path::AbstractString; root_dir::String=pwd())::EngineConfig

Loads configuration following the deterministic precedence hierarchy:
1. EngineConfig struct base defaults
2. Local .env file
3. SQLite database (config table)
4. Runtime environment variables (ENV overrides)
"""
function load_config(db::Union{Nothing, SQLite.DB}, env_path::AbstractString; root_dir::String=pwd())::EngineConfig
    # 1. Base struct defaults
    cfg = EngineConfig(root_dir=root_dir)
    params = Dict{Symbol, Any}(f => getfield(cfg, f) for f in fieldnames(EngineConfig))

    # 2. Local .env file
    if isfile(env_path)
        for raw_line in eachline(env_path)
            line = strip(raw_line)
            (isempty(line) || startswith(line, "#")) && continue
            m = match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            m === nothing && continue
            env_k = m[1]
            raw_v = strip(m[2], ['"', '\''])

            for (field_sym, mapped_env) in ENV_FIELD_MAP
                if mapped_env == env_k
                    ftype = fieldtype(EngineConfig, field_sym)
                    parsed_val = _coerce_type(raw_v, ftype)
                    if parsed_val !== nothing
                        params[field_sym] = parsed_val
                    end
                end
            end
        end
    end

    # 3. SQLite database overrides
    if db !== nothing
        try
            db_configs = db_get_all_config(db)
            for (k_str, val) in db_configs
                sym = Symbol(k_str)
                if haskey(params, sym)
                    ftype = fieldtype(EngineConfig, sym)
                    coerced = _coerce_value(val, ftype)
                    if coerced !== nothing
                        params[sym] = coerced
                    end
                end
            end
        catch e
            @warn "Failed to read SQLite config table" exception=e
        end
    end

    # 4. Runtime ENV overrides (highest priority for bootstrap/port)
    for (field_sym, mapped_env) in ENV_FIELD_MAP
        if haskey(ENV, mapped_env) && !isempty(strip(ENV[mapped_env]))
            raw_v = strip(ENV[mapped_env], ['"', '\''])
            ftype = fieldtype(EngineConfig, field_sym)
            parsed_val = _coerce_type(raw_v, ftype)
            if parsed_val !== nothing
                params[field_sym] = parsed_val
            end
        end
    end

    final_cfg = EngineConfig(; params...)

    # Initialize global manager
    mgr = ConfigManager(Ref(final_cfg), ReentrantLock(), db, String(env_path))
    GLOBAL_CONFIG_MANAGER[] = mgr

    return final_cfg
end

function _coerce_type(str_val::AbstractString, target_type::Type)
    s_val = String(str_val)
    if target_type == String
        return s_val
    elseif target_type == Int
        return tryparse(Int, s_val)
    elseif target_type == Float64
        return tryparse(Float64, s_val)
    elseif target_type == Bool
        s = lowercase(s_val)
        return !(s in ("0", "false", "no", "off", ""))
    elseif target_type == Vector{String}
        # Try JSON array first
        try
            parsed = JSON3.read(s_val)
            if parsed isa JSON3.Array
                return [String(x) for x in parsed]
            end
        catch
        end
        # Fallback to comma-separated
        return [strip(s) for s in split(s_val, ",") if !isempty(strip(s))]
    end
    nothing
end

function _coerce_value(val, target_type::Type)
    if val isa target_type
        return val
    elseif val isa AbstractString
        return _coerce_type(val, target_type)
    elseif target_type == Float64 && val isa Real
        return Float64(val)
    elseif target_type == Int && val isa Real
        return round(Int, val)
    elseif target_type == Vector{String} && val isa AbstractVector
        return [string(x) for x in val]
    end
    nothing
end

"""
    update_config!(key::Union{Symbol, String}, value; scope::Symbol=:global, source::String="api")::Bool

Atomically updates a configuration setting, persists to SQLite and .env (if applicable),
and notifies registered runtime subsystems.
"""
function update_config!(key::Union{Symbol, String}, value; scope::Symbol=:global, source::String="api")::Bool
    mgr = GLOBAL_CONFIG_MANAGER[]
    mgr === nothing && error("ConfigManager is not initialized. Call load_config first.")

    sym_key = Symbol(key)
    str_key = string(key)

    # 1. Validation
    valid, err = validate_config_field(sym_key, value)
    if !valid
        throw(ArgumentError("Configuration validation failed for $(str_key): $(err)"))
    end

    lock(mgr.lock) do
        # 1b. Handle credential keys directly without modifying EngineConfig struct
        if haskey(CREDENTIAL_ENV_MAP, sym_key)
            env_var = CREDENTIAL_ENV_MAP[sym_key]
            str_env_val = strip(string(value))
            sync_env_file!(mgr.env_path, Dict(env_var => str_env_val))
            ENV[env_var] = str_env_val

            if mgr.db !== nothing
                now_utc = string(Dates.now(Dates.UTC))
                try
                    SQLite.execute(mgr.db, """
                        INSERT INTO config_history (key, old_value_json, new_value_json, scope, source, updated_at)
                        VALUES (?, '"[REDACTED]"', '"[REDACTED]"', ?, ?, ?)
                    """, (str_key, string(scope), source, now_utc))
                catch e
                    @warn "Failed to log credential update in config_history" exception=e
                end
            end

            # Propagate to backend if active
            if sym_key == :openrouter_api_key && isdefined(@__MODULE__, :get_backend)
                try
                    backend = get_backend("openrouter")
                    if backend !== nothing && hasfield(typeof(backend), :api_key)
                        # OpenRouter backend may use ENV or field
                    end
                catch err
                    @warn "Failed to update backend credential" exception=err
                end
            end

            # WebSocket broadcast if BYTE is initialized
            _byte = isdefined(Main, :JLEngine) && isdefined(Main.JLEngine, :BYTE) ? Main.JLEngine.BYTE :
                    (isdefined(Main, :BYTE) ? Main.BYTE : nothing)
            if _byte !== nothing && isdefined(_byte, :_broadcast)
                try
                    _byte._broadcast(Dict(
                        "type" => "settings_all_status",
                        "keys" => _byte._build_settings_status_payload()
                    ))
                catch err
                    @warn "Failed to broadcast settings status on credential update" exception=err
                end
            end

            return true
        end

        old_cfg = mgr.current[]
        ftype = fieldtype(EngineConfig, sym_key)
        coerced_value = _coerce_value(value, ftype)
        if coerced_value === nothing
            throw(ArgumentError("Cannot coerce $(value) to type $(ftype)"))
        end

        # 2. SQLite persistence
        if mgr.db !== nothing
            val_json = JSON.json(coerced_value)
            category = get(FIELD_CATEGORY_MAP, sym_key, "general")
            db_set_config!(mgr.db, str_key, val_json; scope=string(scope), category=category, source=source)
        end

        # 3. .env synchronization (for bootstrap keys)
        if sym_key in BOOTSTRAP_ENV_FIELDS && haskey(ENV_FIELD_MAP, sym_key)
            env_var = ENV_FIELD_MAP[sym_key]
            str_env_val = coerced_value isa Bool ? (coerced_value ? "true" : "false") : string(coerced_value)
            sync_env_file!(mgr.env_path, Dict(env_var => str_env_val))
            # Also update ENV in-process
            ENV[env_var] = str_env_val
        end

        # 4. Atomic in-memory swap
        new_cfg = copy_with(old_cfg, sym_key => coerced_value)
        mgr.current[] = new_cfg

        # 5. Side-effect propagation to runtime backends
        if sym_key in (:current_model, :brain_model, :tool_model)
            if isdefined(@__MODULE__, :set_backend_model!)
                try
                    set_backend_model!("openrouter", string(coerced_value))
                catch err
                    @warn "Failed to set backend model" exception=err
                end
            end
        elseif sym_key == :active_provider
            if isdefined(@__MODULE__, :ACTIVE_BACKENDS)
                try
                    ACTIVE_BACKENDS["current"] = string(coerced_value)
                catch err
                    @warn "Failed to update active backend" exception=err
                end
            end
        end

        # 6. WebSocket broadcast if BYTE is initialized
        _byte = isdefined(Main, :JLEngine) && isdefined(Main.JLEngine, :BYTE) ? Main.JLEngine.BYTE :
                (isdefined(Main, :BYTE) ? Main.BYTE : nothing)
        if _byte !== nothing && isdefined(_byte, :_broadcast)
            try
                _byte._broadcast(Dict(
                    "type" => "settings_all_status",
                    "keys" => _byte._build_settings_status_payload()
                ))
            catch err
                @warn "Failed to broadcast settings status" exception=err
            end
        end

        return true
    end
end

"""
    get_current_config()::EngineConfig

Returns the active EngineConfig instance.
"""
function get_current_config()::EngineConfig
    mgr = GLOBAL_CONFIG_MANAGER[]
    if mgr === nothing
        return EngineConfig()
    end
    return mgr.current[]
end

"""
    get_config_dict(; mask_secrets::Bool=true)::Dict{String, Any}

Returns the current typed configuration as a dictionary, masking sensitive tokens.
"""
function get_config_dict(; mask_secrets::Bool=true)::Dict{String, Any}
    cfg = get_current_config()
    d = Dict{String, Any}()
    for f in fieldnames(EngineConfig)
        val = getfield(cfg, f)
        d[string(f)] = val
    end
    # Add provider API key previews for all supported providers
    provider_keys = [
        (:openrouter, "OPENROUTER_API_KEY"),
        (:gemini,     "GEMINI_API_KEY"),
        (:openai,     "OPENAI_API_KEY"),
        (:xai,        "XAI_API_KEY"),
        (:cerebras,   "CEREBRAS_API_KEY"),
        (:github,     "GITHUB_TOKEN"),
    ]
    for (sym, env_var) in provider_keys
        k_val = get(ENV, env_var, "")
        if mask_secrets
            d["$(sym)_has_key"] = !isempty(k_val)
            d["$(sym)_key_preview"] = isempty(k_val) ? "" :
                (length(k_val) <= 8 ? "********" : (k_val[1:min(4, length(k_val))] * "…" * k_val[max(1, length(k_val)-3):end]))
        else
            d["$(sym)_api_key"] = k_val
        end
    end
    return d
end
