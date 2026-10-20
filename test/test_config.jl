using Test
using JLEngine
using SQLite
using JSON3
using JSON

@testset "Config: EngineConfig Struct Schema" begin
    # Default instantiation
    cfg = EngineConfig()

    # 1. Model Roles
    @test cfg.current_model == "deepseek/deepseek-v4-flash"
    @test cfg.brain_model == "deepseek/deepseek-v4-flash"
    @test cfg.tool_model == "deepseek/deepseek-v4-flash"
    @test cfg.reviewer_model == "deepseek/deepseek-v4-flash"
    @test cfg.fallback_models == ["anthropic/claude-3.7-sonnet", "openai/gpt-4o", "meta-llama/llama-3.3-70b-instruct"]

    # 2. Provider Settings
    @test cfg.active_provider == "openrouter"
    @test cfg.openrouter_endpoint == "https://openrouter.ai/api/v1/chat/completions"
    @test cfg.openrouter_timeout == 120
    @test cfg.ollama_endpoint == "http://127.0.0.1:11434"
    @test cfg.gemini_endpoint == "https://generativelanguage.googleapis.com/v1beta"

    # 3. Sampling
    @test cfg.default_temperature == 0.7
    @test cfg.default_top_p == 0.95
    @test cfg.max_tokens == 4096
    @test cfg.reasoning_effort == "medium"

    # 4. Network & Runtime
    @test cfg.host == "127.0.0.1"
    @test cfg.port == 8081
    @test cfg.debug_mode == false
    @test cfg.log_level == "info"

    # 5. Legacy Fields
    @test cfg.safety_on == true
    @test cfg.default_agent_name == "SparkByte"
    @test cfg.history_length == 20

    # Custom instantiation
    custom_cfg = EngineConfig(
        current_model = "anthropic/claude-3.7-sonnet",
        active_provider = "ollama",
        port = 8090,
        default_temperature = 0.2
    )
    @test custom_cfg.current_model == "anthropic/claude-3.7-sonnet"
    @test custom_cfg.active_provider == "ollama"
    @test custom_cfg.port == 8090
    @test custom_cfg.default_temperature == 0.2

    # copy_with
    updated_cfg = copy_with(custom_cfg, port=8088, reasoning_effort="high")
    @test updated_cfg.port == 8088
    @test updated_cfg.reasoning_effort == "high"
    @test updated_cfg.current_model == "anthropic/claude-3.7-sonnet"
end

@testset "Config: Field Validation Rules" begin
    # Model fields
    @test validate_config_field(:current_model, "openai/gpt-4o")[1] == true
    @test validate_config_field(:current_model, "")[1] == false
    @test validate_config_field(:current_model, 123)[1] == false

    # Fallback models
    @test validate_config_field(:fallback_models, ["m1", "m2"])[1] == true
    @test validate_config_field(:fallback_models, "m1")[1] == false
    @test validate_config_field(:fallback_models, ["m1", ""])[1] == false

    # Provider
    @test validate_config_field(:active_provider, "openrouter")[1] == true
    @test validate_config_field(:active_provider, "ollama")[1] == true
    @test validate_config_field(:active_provider, "gemini")[1] == true
    @test validate_config_field(:active_provider, "invalid_provider")[1] == false

    # Endpoints
    @test validate_config_field(:openrouter_endpoint, "https://openrouter.ai/api/v1")[1] == true
    @test validate_config_field(:openrouter_endpoint, "ftp://bad")[1] == false
    @test validate_config_field(:ollama_endpoint, "http://localhost:11434")[1] == true

    # Timeouts
    @test validate_config_field(:openrouter_timeout, 120)[1] == true
    @test validate_config_field(:openrouter_timeout, 0)[1] == false
    @test validate_config_field(:openrouter_timeout, 700)[1] == false

    # Temperature & Top-P
    @test validate_config_field(:default_temperature, 0.7)[1] == true
    @test validate_config_field(:default_temperature, -0.1)[1] == false
    @test validate_config_field(:default_temperature, 2.5)[1] == false
    @test validate_config_field(:default_top_p, 0.95)[1] == true
    @test validate_config_field(:default_top_p, 1.5)[1] == false

    # Max tokens
    @test validate_config_field(:max_tokens, 4096)[1] == true
    @test validate_config_field(:max_tokens, 0)[1] == false
    @test validate_config_field(:max_tokens, 200000)[1] == false

    # Reasoning effort
    @test validate_config_field(:reasoning_effort, "low")[1] == true
    @test validate_config_field(:reasoning_effort, "high")[1] == true
    @test validate_config_field(:reasoning_effort, "extreme")[1] == false

    # Network
    @test validate_config_field(:host, "0.0.0.0")[1] == true
    @test validate_config_field(:host, "")[1] == false
    @test validate_config_field(:port, 8081)[1] == true
    @test validate_config_field(:port, 80)[1] == false
    @test validate_config_field(:port, 70000)[1] == false

    # Runtime
    @test validate_config_field(:debug_mode, true)[1] == true
    @test validate_config_field(:debug_mode, "yes")[1] == false
    @test validate_config_field(:log_level, "info")[1] == true
    @test validate_config_field(:log_level, "verbose")[1] == false

    # Unknown
    @test validate_config_field(:unknown_setting, "value")[1] == false
end

@testset "Config: Comment-Preserving .env Synchronization" begin
    tmp_dir = mktempdir()
    env_file = joinpath(tmp_dir, ".env")

    initial_content = """
# ── Primary Server Settings ──────────────────────────
SPARKBYTE_HOST=127.0.0.1
SPARKBYTE_PORT=8081

# Developer Note: keep debug mode false in production
SPARKBYTE_DEBUG=false

# ── Model Configuration ──────────────────────────────
DEFAULT_OPENROUTER_MODEL=deepseek/deepseek-v4-flash
"""
    write(env_file, initial_content)

    updates = Dict{String, String}(
        "SPARKBYTE_PORT" => "8090",
        "DEFAULT_OPENROUTER_MODEL" => "anthropic/claude-3.7-sonnet",
        "NEW_DYNAMIC_VAR" => "hello world"
    )

    ok = sync_env_file!(env_file, updates)
    @test ok == true

    result_content = read(env_file, String)

    # 1. Comments preserved
    @test occursin("# ── Primary Server Settings ──────────────────────────", result_content)
    @test occursin("# Developer Note: keep debug mode false in production", result_content)
    @test occursin("# ── Model Configuration ──────────────────────────────", result_content)

    # 2. Existing keys updated in-place
    @test occursin("SPARKBYTE_PORT=8090", result_content)
    @test occursin("DEFAULT_OPENROUTER_MODEL=anthropic/claude-3.7-sonnet", result_content)
    @test !occursin("SPARKBYTE_PORT=8081", result_content)

    # 3. New keys appended safely with quotation for spaces
    @test occursin("NEW_DYNAMIC_VAR=\"hello world\"", result_content)

    rm(tmp_dir; recursive=true, force=true)
end

@testset "Config: SQLite Persistence & Audit History" begin
    db = SQLite.DB()
    init_config_table!(db)

    # 1. Upsert config
    JLEngine.db_set_config!(db, "current_model", "\"openai/gpt-4o\""; scope="global", category="model", source="api")
    val = JLEngine.db_get_config(db, "current_model")
    @test val == "openai/gpt-4o"

    # 2. Upsert update and verify audit history
    JLEngine.db_set_config!(db, "current_model", "\"anthropic/claude-3.7-sonnet\""; scope="global", category="model", source="ui")
    updated_val = JLEngine.db_get_config(db, "current_model")
    @test updated_val == "anthropic/claude-3.7-sonnet"

    # Verify history table has 2 records
    history_rows = [NamedTuple(row) for row in SQLite.DBInterface.execute(db, "SELECT * FROM config_history WHERE key = 'current_model' ORDER BY id ASC")]
    @test length(history_rows) == 2
    @test ismissing(history_rows[1].old_value_json) || history_rows[1].old_value_json === nothing
    @test string(history_rows[1].new_value_json) == "\"openai/gpt-4o\""
    @test string(history_rows[2].old_value_json) == "\"openai/gpt-4o\""
    @test string(history_rows[2].new_value_json) == "\"anthropic/claude-3.7-sonnet\""

    # 3. Verify sensitive keys are redacted in history
    JLEngine.db_set_config!(db, "openrouter_api_key", "\"sk-or-v1-secret12345\""; source="api")
    key_history = [NamedTuple(row) for row in SQLite.DBInterface.execute(db, "SELECT * FROM config_history WHERE key = 'openrouter_api_key'")]
    @test length(key_history) == 1
    @test occursin("[REDACTED]", string(key_history[1].new_value_json))
    @test !occursin("secret12345", string(key_history[1].new_value_json))
end

@testset "Config: Deterministic Hierarchy (load_config & update_config!)" begin
    tmp_dir = mktempdir()
    env_path = joinpath(tmp_dir, ".env")
    db = SQLite.DB()
    init_config_table!(db)

    # 1. Write bootstrap .env setting port to 8085
    write(env_path, "SPARKBYTE_PORT=8085\nDEFAULT_OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct\n")

    # 2. Write SQLite override for model setting it to claude-3.7-sonnet
    JLEngine.db_set_config!(db, "current_model", "\"anthropic/claude-3.7-sonnet\"")

    # 3. load_config: .env sets port to 8085, SQLite overrides current_model to claude-3.7-sonnet
    loaded = load_config(db, env_path; root_dir=tmp_dir)
    @test loaded.port == 8085
    @test loaded.current_model == "anthropic/claude-3.7-sonnet"

    # 4. update_config!: Update port to 8089 and default_temperature to 0.4
    update_config!(:port, 8089)
    update_config!(:default_temperature, 0.4)

    cur_cfg = get_current_config()
    @test cur_cfg.port == 8089
    @test cur_cfg.default_temperature == 0.4

    # Verify SQLite reflects update
    @test JLEngine.db_get_config(db, "port") == 8089
    @test JLEngine.db_get_config(db, "default_temperature") == 0.4

    # Verify .env was synchronized for bootstrap key port
    env_content = read(env_path, String)
    @test occursin("SPARKBYTE_PORT=8089", env_content)

    # 5. Validation failure rejection
    @test_throws ArgumentError update_config!(:default_temperature, 5.0)
    @test_throws ArgumentError update_config!(:port, 99999)

    # 6. get_config_dict with masked secrets
    cfg_d = get_config_dict(; mask_secrets=true)
    @test cfg_d["port"] == 8089
    @test cfg_d["default_temperature"] == 0.4
    @test haskey(cfg_d, "openrouter_key_preview")

    rm(tmp_dir; recursive=true, force=true)
end
