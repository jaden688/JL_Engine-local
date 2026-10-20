using Test
using SQLite
using JSON
using JSON3

# Ensure JLEngine is loaded
using JLEngine

@testset "Adversarial Challenge: Wave 1 Persistent Settings & SQLite WAL" begin

    # =========================================================================
    # CHALLENGE 1: All 18 Typed Fields Persistence Across Process / DB Restarts
    # =========================================================================
    @testset "Challenge 1: All 18 Typed Fields Persistence & Reload" begin
        tmp_dir = mktempdir()
        db_path = joinpath(tmp_dir, "test_settings_18.db")
        env_path = joinpath(tmp_dir, ".env")
        touch(env_path)

        db = SQLite.DB(db_path)
        SQLite.execute(db, "PRAGMA journal_mode=WAL;")
        SQLite.execute(db, "PRAGMA busy_timeout=5000;")
        init_config_table!(db)

        # Initial baseline load
        initial_cfg = load_config(db, env_path; root_dir=tmp_dir)
        @test initial_cfg isa EngineConfig

        # Map of all 18 typed test values (non-default, challenging values)
        typed_test_updates = Dict{Symbol, Any}(
            # 1-5: Model roles
            :current_model       => "anthropic/claude-3-5-sonnet-20241022",
            :brain_model         => "openai/o1-preview",
            :tool_model          => "meta-llama/llama-3.1-70b-instruct",
            :reviewer_model      => "google/gemini-1.5-pro",
            :fallback_models     => String["mistralai/mistral-large-2407", "qwen/qwen-2.5-72b-instruct"],
            # 6-10: Provider endpoints
            :active_provider     => "ollama",
            :openrouter_endpoint => "https://openrouter.ai/api/v2/chat/completions",
            :openrouter_timeout  => 240,
            :ollama_endpoint     => "http://192.168.1.50:11434",
            :gemini_endpoint     => "https://generativelanguage.googleapis.com/v2",
            # 11-14: Sampling parameters
            :default_temperature => 1.35,
            :default_top_p       => 0.88,
            :max_tokens          => 16384,
            :reasoning_effort    => "high",
            # 15-18: Network and runtime
            :host                => "0.0.0.0",
            :port                => 8095,
            :debug_mode          => true,
            :log_level           => "debug"
        )

        @test length(typed_test_updates) == 18

        # Apply update_config! for all 18 fields
        for (sym_key, test_val) in typed_test_updates
            ok = update_config!(sym_key, test_val; scope=:global, source="challenger_test")
            @test ok == true
        end

        # Verify in-memory state matches immediately
        mem_cfg = get_current_config()
        for (sym_key, test_val) in typed_test_updates
            actual_val = getfield(mem_cfg, sym_key)
            @test actual_val == test_val
            @test typeof(actual_val) == typeof(test_val)
        end

        # Verify SQLite table holds every single one of the 18 keys
        all_db_config = JLEngine.db_get_all_config(db)
        for (sym_key, test_val) in typed_test_updates
            str_key = string(sym_key)
            @test haskey(all_db_config, str_key)
            db_val = all_db_config[str_key]
            if test_val isa Vector{String}
                @test [string(x) for x in db_val] == test_val
            else
                @test db_val == test_val
            end
        end

        # Hard restart: Close SQLite handle, unbind global manager
        SQLite.execute(db, "PRAGMA wal_checkpoint(TRUNCATE);")
        SQLite.close(db)
        JLEngine.GLOBAL_CONFIG_MANAGER[] = nothing

        # Reopen database in a new handle & reload
        db2 = SQLite.DB(db_path)
        reloaded_cfg = load_config(db2, env_path; root_dir=tmp_dir)

        # Verify all 18 fields survived restart and reloaded accurately
        @test reloaded_cfg.current_model == "anthropic/claude-3-5-sonnet-20241022"
        @test reloaded_cfg.brain_model == "openai/o1-preview"
        @test reloaded_cfg.tool_model == "meta-llama/llama-3.1-70b-instruct"
        @test reloaded_cfg.reviewer_model == "google/gemini-1.5-pro"
        @test reloaded_cfg.fallback_models == String["mistralai/mistral-large-2407", "qwen/qwen-2.5-72b-instruct"]
        @test reloaded_cfg.fallback_models isa Vector{String}

        @test reloaded_cfg.active_provider == "ollama"
        @test reloaded_cfg.openrouter_endpoint == "https://openrouter.ai/api/v2/chat/completions"
        @test reloaded_cfg.openrouter_timeout == 240
        @test reloaded_cfg.openrouter_timeout isa Int
        @test reloaded_cfg.ollama_endpoint == "http://192.168.1.50:11434"
        @test reloaded_cfg.gemini_endpoint == "https://generativelanguage.googleapis.com/v2"

        @test reloaded_cfg.default_temperature ≈ 1.35
        @test reloaded_cfg.default_temperature isa Float64
        @test reloaded_cfg.default_top_p ≈ 0.88
        @test reloaded_cfg.default_top_p isa Float64
        @test reloaded_cfg.max_tokens == 16384
        @test reloaded_cfg.max_tokens isa Int
        @test reloaded_cfg.reasoning_effort == "high"

        @test reloaded_cfg.host == "0.0.0.0"
        @test reloaded_cfg.port == 8095
        @test reloaded_cfg.port isa Int
        @test reloaded_cfg.debug_mode == true
        @test reloaded_cfg.debug_mode isa Bool
        @test reloaded_cfg.log_level == "debug"

        # Edge cases: Boundary values and coercion
        update_config!(:default_temperature, 0.0)
        update_config!(:default_top_p, 1.0)
        update_config!(:max_tokens, 1)
        update_config!(:port, 1024)
        update_config!(:reasoning_effort, "none")
        update_config!(:debug_mode, false)

        boundary_cfg = get_current_config()
        @test boundary_cfg.default_temperature == 0.0
        @test boundary_cfg.default_top_p == 1.0
        @test boundary_cfg.max_tokens == 1
        @test boundary_cfg.port == 1024
        @test boundary_cfg.reasoning_effort == "none"
        @test boundary_cfg.debug_mode == false

        # Adversarial Bug Check: In db_set_config! / db_get_config, does updating an existing
        # record leave a dangling cursor holding a table lock?
        # When an existing key is updated, db_set_config! breaks early from SQLite.DBInterface.execute.
        # This causes PRAGMA wal_checkpoint(TRUNCATE) to fail with SQLiteException("database table is locked").
        checkpoint_failed_due_to_lock = false
        try
            SQLite.execute(db2, "PRAGMA wal_checkpoint(TRUNCATE);")
        catch e
            if e isa SQLite.SQLiteException && occursin("database table is locked", e.msg)
                checkpoint_failed_due_to_lock = true
            else
                rethrow(e)
            end
        end

        # Verify that cursor is exhausted and table lock is released:
        @test checkpoint_failed_due_to_lock == false

        # Clean close attempt
        try SQLite.close(db2) catch; end
        JLEngine.GLOBAL_CONFIG_MANAGER[] = nothing

        # Adversarial Invalid Inputs: Must be rejected without corrupting DB
        db3 = SQLite.DB(db_path)
        load_config(db3, env_path; root_dir=tmp_dir)

        @test_throws ArgumentError update_config!(:port, 1023)
        @test_throws ArgumentError update_config!(:port, 65536)
        @test_throws ArgumentError update_config!(:openrouter_timeout, 0)
        @test_throws ArgumentError update_config!(:openrouter_timeout, 601)
        @test_throws ArgumentError update_config!(:default_temperature, -0.01)
        @test_throws ArgumentError update_config!(:default_temperature, 2.01)
        @test_throws ArgumentError update_config!(:default_top_p, -0.01)
        @test_throws ArgumentError update_config!(:default_top_p, 1.01)
        @test_throws ArgumentError update_config!(:max_tokens, 0)
        @test_throws ArgumentError update_config!(:max_tokens, 128001)
        @test_throws ArgumentError update_config!(:active_provider, "invalid_llm")
        @test_throws ArgumentError update_config!(:reasoning_effort, "invalid_effort")
        @test_throws ArgumentError update_config!(:log_level, "verbose")
        @test_throws ArgumentError update_config!(:current_model, "")
        @test_throws ArgumentError update_config!(:fallback_models, ["valid_model", ""])

        try SQLite.close(db3) catch; end
        try rm(tmp_dir; recursive=true, force=true) catch; end
    end

    # =========================================================================
    # CHALLENGE 2: Comment-Preserving .env Synchronization Stress Testing
    # =========================================================================
    @testset "Challenge 2: Comment-Preserving .env Synchronization" begin
        tmp_dir = mktempdir()
        env_file = joinpath(tmp_dir, ".env")

        complex_env = """
###############################################################################
#   SparkByte Omni ASCENSION - Runtime Configuration Environment
#   DO NOT EXPOSE CREDENTIALS IN PUBLIC LOGS OR TELEMETRY
#   Security Classification: Internal 🚀 🛡️
###############################################################################

# ── 1. Network & Ingress Settings ──────────────────────────────────────────
# Port allocation note: default 8081 for BYTE, 8082 for cluster A2A
   SPARKBYTE_HOST=127.0.0.1   
SPARKBYTE_PORT=8081

# Inactive fallback port for staging tests (DO NOT UNCOMMENT IN PROD):
# SPARKBYTE_PORT=9999

# ── 2. LLM Provider Credentials & Defaults ─────────────────────────────────
# OpenRouter endpoint and default model designation
DEFAULT_OPENROUTER_MODEL=deepseek/deepseek-v4-flash
DEFAULT_OPENROUTER_ENDPOINT=https://openrouter.ai/api/v1/chat/completions

# Commented out legacy model:
# DEFAULT_OPENROUTER_MODEL=openai/gpt-3.5-turbo

# ── 3. External Infrastructure (Non-Configuration Variables) ───────────────
DATABASE_URL=postgres://sparkuser:p%40ssw0rd@127.0.0.1:5432/sparkbyte_db
SENTRY_DSN=https://abc123def456@o9999.ingest.sentry.io/7777777
CUSTOM_API_KEY="my-raw-secret-key-12345"

# ── 4. End of Configuration File ───────────────────────────────────────────
"""
        write(env_file, complex_env)

        # 1. Update existing keys: SPARKBYTE_PORT to 8092, DEFAULT_OPENROUTER_MODEL to claude-3-5
        updates = Dict{String, String}(
            "SPARKBYTE_PORT" => "8092",
            "DEFAULT_OPENROUTER_MODEL" => "anthropic/claude-3-5-sonnet-20241022",
            "NEW_BOOTSTRAP_KEY" => "custom_bootstrap_value"
        )

        ok = sync_env_file!(env_file, updates)
        @test ok == true

        res_content = read(env_file, String)

        # Verify comments and headers are preserved intact
        @test occursin("SparkByte Omni ASCENSION - Runtime Configuration Environment", res_content)
        @test occursin("Security Classification: Internal 🚀 🛡️", res_content)
        @test occursin("# ── 1. Network & Ingress Settings ──────────────────────────────────────────", res_content)
        @test occursin("# Port allocation note: default 8081 for BYTE, 8082 for cluster A2A", res_content)
        @test occursin("# ── 2. LLM Provider Credentials & Defaults ─────────────────────────────────", res_content)
        @test occursin("# ── 3. External Infrastructure (Non-Configuration Variables) ───────────────", res_content)

        # Verify commented-out keys were NEVER altered or replaced
        @test occursin("# SPARKBYTE_PORT=9999", res_content)
        @test occursin("# DEFAULT_OPENROUTER_MODEL=openai/gpt-3.5-turbo", res_content)

        # Verify non-configuration variables are untouched
        @test occursin("DATABASE_URL=postgres://sparkuser:p%40ssw0rd@127.0.0.1:5432/sparkbyte_db", res_content)
        @test occursin("SENTRY_DSN=https://abc123def456@o9999.ingest.sentry.io/7777777", res_content)
        @test occursin("CUSTOM_API_KEY=\"my-raw-secret-key-12345\"", res_content)

        # Verify active keys were updated in-place
        @test occursin("SPARKBYTE_PORT=8092", res_content)
        @test !occursin("SPARKBYTE_PORT=8081", res_content)
        @test occursin("DEFAULT_OPENROUTER_MODEL=anthropic/claude-3-5-sonnet-20241022", res_content)
        @test !occursin("DEFAULT_OPENROUTER_MODEL=deepseek/deepseek-v4-flash", res_content)

        # Verify new key was added cleanly
        @test occursin("NEW_BOOTSTRAP_KEY=custom_bootstrap_value", res_content)

        # 2. Stress Test: Multiple sequential updates to the same file
        for p in 8093:8100
            ok_loop = sync_env_file!(env_file, Dict("SPARKBYTE_PORT" => string(p)))
            @test ok_loop == true
        end

        res_loop_content = read(env_file, String)
        @test occursin("SPARKBYTE_PORT=8100", res_loop_content)
        # Ensure SPARKBYTE_PORT is not duplicated
        port_matches = collect(eachmatch(r"^SPARKBYTE_PORT=.*$"m, res_loop_content))
        @test length(port_matches) == 1
        @test port_matches[1].match == "SPARKBYTE_PORT=8100"

        # Non-config keys still intact after multiple updates
        @test occursin("DATABASE_URL=postgres://sparkuser:p%40ssw0rd@127.0.0.1:5432/sparkbyte_db", res_loop_content)
        @test occursin("# SPARKBYTE_PORT=9999", res_loop_content)

        # 3. Quoting edge cases: values with spaces, quotes, hashes
        sync_env_file!(env_file, Dict("SPARKBYTE_NOTE" => "Testing spaces and #comments in value"))
        res_quoted = read(env_file, String)
        @test occursin("SPARKBYTE_NOTE=\"Testing spaces and #comments in value\"", res_quoted)

        try rm(tmp_dir; recursive=true, force=true) catch; end
    end

    # =========================================================================
    # CHALLENGE 3: SQLite WAL Checkpoint & Shutdown Behavior (Subprocess & Anti-pattern)
    # =========================================================================
    @testset "Challenge 3: SQLite WAL Checkpoint & Clean Shutdown" begin
        # 3A: In-process WAL Checkpoint(TRUNCATE) validation on clean DB
        tmp_dir = mktempdir()
        db_file = joinpath(tmp_dir, "wal_test.db")
        wal_file = db_file * "-wal"

        db = SQLite.DB(db_file)
        SQLite.execute(db, "PRAGMA journal_mode=WAL;")
        SQLite.execute(db, "PRAGMA busy_timeout=5000;")
        SQLite.execute(db, "PRAGMA synchronous=NORMAL;")
        init_config_table!(db)

        # Direct table inserts (without hitting unclosed cursor in db_set_config!)
        for i in 1:100
            SQLite.execute(db, "INSERT INTO config (key, value_json, scope, category, updated_at) VALUES (?, ?, 'global', 'general', '2026-10-14')", ("bulk_key_$i", "\"test_value_$i\""))
        end

        # Check WAL file exists and contains frames
        @test isfile(wal_file)
        initial_wal_size = filesize(wal_file)
        @test initial_wal_size > 0

        # Run PRAGMA wal_checkpoint(TRUNCATE)
        checkpoint_result = [NamedTuple(row) for row in SQLite.DBInterface.execute(db, "PRAGMA wal_checkpoint(TRUNCATE);")]
        @test length(checkpoint_result) == 1
        r = checkpoint_result[1]
        @test r.busy == 0
        @test r.checkpointed == r.log

        # After TRUNCATE on clean connections, WAL file is 0 bytes
        @test filesize(wal_file) == 0
        SQLite.close(db)

        # 3B: Standalone Subprocess Simulation of App atexit Hook with Base.julia_cmd()
        # Case 1: Fresh insertions (new keys) where cursor is exhausted
        subproc_script1 = joinpath(tmp_dir, "subproc_wal_insert.jl")
        subproc_db1 = joinpath(tmp_dir, "app_wal_insert.db")
        subproc_wal1 = subproc_db1 * "-wal"

        script_code1 = """
        using SQLite
        using Dates
        using JLEngine

        db = SQLite.DB($(repr(subproc_db1)))
        SQLite.execute(db, "PRAGMA journal_mode=WAL;")
        SQLite.execute(db, "PRAGMA busy_timeout=5000;")
        SQLite.execute(db, "PRAGMA synchronous=NORMAL;")
        init_config_table!(db)

        for i in 1:50
            JLEngine.db_set_config!(db, "subproc_key_\$i", "\\"subproc_val_\$i\\"")
        end

        # Register exact atexit hook from src/App.jl lines 446-453
        atexit() do
            try
                SQLite.execute(db, "PRAGMA wal_checkpoint(TRUNCATE);")
                SQLite.close(db)
            catch err
                @warn "Failed to checkpoint SQLite WAL on exit" exception=(err, catch_backtrace())
            end
        end

        exit(0)
        """
        write(subproc_script1, script_code1)

        cmd1 = `$(Base.julia_cmd()) --project=. $(subproc_script1)`
        proc1 = run(cmd1)
        @test success(proc1)

        # Checkpoint worked for fresh keys because cursor returned 0 rows
        if isfile(subproc_wal1)
            @test filesize(subproc_wal1) == 0
        else
            @test !isfile(subproc_wal1)
        end

        # Case 2: Subprocess updating an EXISTING key via update_config! / db_set_config!
        # This exercises the dangling statement / table lock bug on exit!
        subproc_script2 = joinpath(tmp_dir, "subproc_wal_update.jl")
        subproc_db2 = joinpath(tmp_dir, "app_wal_update.db")
        subproc_wal2 = subproc_db2 * "-wal"
        subproc_stderr = joinpath(tmp_dir, "subproc_update.err")

        script_code2 = """
        using SQLite
        using Dates
        using JLEngine

        db = SQLite.DB($(repr(subproc_db2)))
        SQLite.execute(db, "PRAGMA journal_mode=WAL;")
        SQLite.execute(db, "PRAGMA busy_timeout=5000;")
        SQLite.execute(db, "PRAGMA synchronous=NORMAL;")
        init_config_table!(db)

        # 1. Insert initial key
        JLEngine.db_set_config!(db, "existing_key", "\\"initial_val\\"")

        # 2. Update existing key (triggers: break inside SQLite.DBInterface.execute)
        JLEngine.db_set_config!(db, "existing_key", "\\"updated_val\\"")

        # 3. Register exact atexit hook from src/App.jl lines 446-453
        atexit() do
            try
                SQLite.execute(db, "PRAGMA wal_checkpoint(TRUNCATE);")
                SQLite.close(db)
            catch err
                @warn "Failed to checkpoint SQLite WAL on exit" exception=(err, catch_backtrace())
            end
        end

        exit(0)
        """
        write(subproc_script2, script_code2)

        # Execute and capture stderr
        err_io = open(subproc_stderr, "w")
        cmd2 = pipeline(`$(Base.julia_cmd()) --project=. $(subproc_script2)`, stderr=err_io)
        proc2 = run(cmd2)
        close(err_io)

        stderr_output = read(subproc_stderr, String)

        # Verify that WAL checkpoint on exit succeeds cleanly with zero table lock warnings:
        checkpoint_failed_on_exit = occursin("Failed to checkpoint SQLite WAL on exit", stderr_output)
        @test checkpoint_failed_on_exit == false
        @test !occursin("database table is locked", stderr_output)


        # 3C: Anti-pattern Enforcement: Strict Ban on Manual WAL/SHM Deletion
        repo_root = normpath(joinpath(@__DIR__, ".."))
        violations = String[]

        for (root, dirs, files) in walkdir(repo_root)
            occursin(".git", root) && continue
            occursin(".agents", root) && continue

            for f in files
                (endswith(f, ".jl") || endswith(f, ".bat") || endswith(f, ".sh") || endswith(f, ".ps1")) || continue
                path = joinpath(root, f)
                content = read(path, String)
                if occursin(r"(rm|del|unlink|remove).*(\.db-wal|\.db-shm|\.sqlite-wal|\.sqlite-shm|\*wal|\*shm)"i, content)
                    if !occursin("reject", lowercase(content)) && !occursin("anti-pattern", lowercase(content)) && !occursin("anti_pattern", lowercase(content))
                        push!(violations, "\$path contains potential manual WAL deletion: \$content")
                    end
                end
            end
        end

        @test isempty(violations)

        try rm(tmp_dir; recursive=true, force=true) catch; end
    end

end
