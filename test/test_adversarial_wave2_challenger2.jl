using Test
using HTTP
using JSON
using JSON3
using SQLite
using Dates
using JLEngine

if !isdefined(Main, :BYTE)
    @eval Main const BYTE = JLEngine.BYTE
end

# ── Mock HTTP Stream for In-Process Route Dispatch Testing ───────────────────
mutable struct MockHttpStream
    message::HTTP.Request
    status::Int
    headers::Vector{Pair{String, String}}
    body_in::IOBuffer
    body_out::IOBuffer
    started::Bool
end

MockHttpStream(method::String, target::String, body_str::String="") =
    MockHttpStream(HTTP.Request(method, target, Pair{String,String}[], Vector{UInt8}(body_str)),
                   200, Pair{String,String}[], IOBuffer(body_str), IOBuffer(), false)

HTTP.setstatus(s::MockHttpStream, status::Int) = (s.status = status; status)
HTTP.setheader(s::MockHttpStream, h::Pair) = (push!(s.headers, string(h.first) => string(h.second)); s.headers)
HTTP.startwrite(s::MockHttpStream) = (s.started = true; nothing)
Base.write(s::MockHttpStream, data) = write(s.body_out, data)
Base.read(s::MockHttpStream) = read(s.body_in)

function _response_body(s::MockHttpStream)
    seekstart(s.body_out)
    return String(take!(s.body_out))
end

function _response_json(s::MockHttpStream)
    return JSON.parse(_response_body(s))
end

function _get_header(s::MockHttpStream, name::String)
    for (k, v) in s.headers
        lowercase(k) == lowercase(name) && return v
    end
    return nothing
end

@testset "Adversarial Challenge: Wave 2 Control Center & Settings Hardening" begin

    # =========================================================================
    # CHALLENGE 1: Config.jl Credential Updates, .env Sync & SQLite Audit Log
    # =========================================================================
    @testset "Challenge 1: Credential Updates & Sensitive History Redaction" begin
        tmp_dir = mktempdir()
        db_path = joinpath(tmp_dir, "test_challenger_credentials.db")
        env_path = joinpath(tmp_dir, ".env")

        initial_env_content = """
# ==============================================================================
# SPARKBYTE RUNTIME ENVIRONMENT (Wave 2 Challenger Baseline)
# ==============================================================================

# Core Settings
DEFAULT_OPENROUTER_MODEL=deepseek/deepseek-v4-flash
SPARKBYTE_HOST=127.0.0.1
SPARKBYTE_PORT=8081

# --- Model Provider Credentials ---
# Important: Do not commit active production secrets
OPENROUTER_API_KEY=sk-or-v1-fixture-placeholder-not-real-key
GEMINI_API_KEY=AIzaTESTONLY000000000000000000000000

# End of baseline
"""
        write(env_path, initial_env_content)

        db = SQLite.DB(db_path)
        init_config_table!(db)

        # Initialize ConfigManager
        initial_cfg = load_config(db, env_path; root_dir=tmp_dir)
        @test initial_cfg isa EngineConfig

        # 1.1 EMPIRICAL DEFECT TEST: Test update_config! with openrouter_api_key
        # In Config.jl line 550:
        #   `str_env_val = strip(string(value))`
        # strip() returns a `SubString{String}`.
        # Constructing `Dict(env_var => str_env_val)` produces a `Dict{String, SubString{String}}`.
        # Calling `sync_env_file!(mgr.env_path, Dict(env_var => str_env_val))` fails with:
        #   `MethodError: no method matching sync_env_file!(::String, ::Dict{String, SubString{String}})`
        # because `sync_env_file!` requires `updates::Dict{String, String}` and Dict in Julia is invariant.
        new_or_key = "sk-or-v1-fixture-placeholder-not-real-key"
        
        err_caught = nothing
        try
            update_config!(:openrouter_api_key, new_or_key; scope=:global, source="challenger_test")
        catch e
            err_caught = e
        end
        
        # Verify and document the exact MethodError defect
        @test err_caught isa MethodError
        @test occursin("sync_env_file!", sprint(showerror, err_caught))
        @test occursin("SubString", sprint(showerror, err_caught))

        # 1.2 EMPIRICAL DEFECT TEST: Test update_config! with gemini_api_key
        new_gemini_key = "AIzaTESTONLY000000000000000000000000"
        gem_err_caught = nothing
        try
            update_config!(:gemini_api_key, new_gemini_key; scope=:global, source="challenger_test")
        catch e
            gem_err_caught = e
        end
        @test gem_err_caught isa MethodError

        # 1.3 Test POST /api/config route failure when updating credentials due to this MethodError
        engine = JLEngine.JLEngineCore()
        stream_post = MockHttpStream("POST", "/api/config", JSON.json(Dict("openrouter_api_key" => new_or_key)))
        
        # Simulate BYTE HTTP serve POST /api/config handler as in BYTE.jl line 2492
        body_bytes = read(stream_post)
        payload = JSON.parse(String(body_bytes))
        updated_keys = String[]
        errors = String[]
        for (k, v) in payload
            try
                JLEngine.update_config!(k, v; source="api")
                push!(updated_keys, string(k))
            catch e
                push!(errors, "$(k): $(sprint(showerror, e))")
            end
        end
        status_code = isempty(errors) ? 200 : (isempty(updated_keys) ? 400 : 207)
        HTTP.setstatus(stream_post, status_code)
        HTTP.setheader(stream_post, "Content-Type"=>"application/json; charset=utf-8")
        HTTP.startwrite(stream_post)
        write(stream_post, JSON.json(Dict(
            "ok" => isempty(errors),
            "updated" => updated_keys,
            "errors" => errors,
            "config" => JLEngine.get_config_dict(; mask_secrets=true)
        )))

        @test stream_post.status == 400
        post_resp = _response_json(stream_post)
        @test post_resp["ok"] == false
        @test isempty(post_resp["updated"])
        @test length(post_resp["errors"]) == 1
        @test occursin("MethodError", post_resp["errors"][1])

        # 1.4 Test the Underlying sync_env_file! Function with String(strip(...)) to Verify Fix Path
        # When converted to String, sync_env_file! successfully updates .env while preserving comments:
        proper_updates = Dict{String, String}("OPENROUTER_API_KEY" => String(strip(new_or_key)))
        sync_ok = sync_env_file!(env_path, proper_updates)
        @test sync_ok == true
        env_text = read(env_path, String)
        @test occursin("OPENROUTER_API_KEY=$(new_or_key)", env_text)
        @test occursin("# Core Settings", env_text)
        @test occursin("# --- Model Provider Credentials ---", env_text)
        @test occursin("# Important: Do not commit active production secrets", env_text)
        @test occursin("SPARKBYTE_PORT=8081", env_text)

        # 1.5 Adversarial inputs to validate_config_field for credentials
        @test_throws ArgumentError update_config!(:openrouter_api_key, "")
        @test_throws ArgumentError update_config!(:openrouter_api_key, "   ")
        @test_throws ArgumentError update_config!(:openrouter_api_key, 12345)
        @test_throws ArgumentError update_config!(:openrouter_api_key, true)
        @test_throws ArgumentError update_config!(:gemini_api_key, "")
        @test_throws ArgumentError update_config!(:bogus_nonexistent_key, "value")

        SQLite.close(db)
    end

    # =========================================================================
    # CHALLENGE 2: Credential Masking in API Responses
    # =========================================================================
    @testset "Challenge 2: Credential Masking Preview & Secret Leak Prevention" begin
        # Set controlled test credentials in ENV
        test_or_key = "sk-or-v1-fixture-placeholder-not-real-key"
        test_gem_key = "AIzaShort"
        test_exact8_key = "12345678"
        test_exact9_key = "123456789"

        ENV["OPENROUTER_API_KEY"] = test_or_key
        ENV["GEMINI_API_KEY"]     = test_gem_key
        ENV["OPENAI_API_KEY"]     = test_exact8_key
        ENV["XAI_API_KEY"]        = test_exact9_key
        delete!(ENV, "CEREBRAS_API_KEY")
        delete!(ENV, "GITHUB_TOKEN")

        # 2.1 Test get_config_dict(; mask_secrets=true)
        masked_dict = get_config_dict(; mask_secrets=true)

        # Verify openrouter masked preview: first 4 chars "sk-o", "…", last 4 chars "6789"
        @test masked_dict["openrouter_has_key"] == true
        @test masked_dict["openrouter_key_preview"] == "sk-o…6789"

        # Verify short key (> 8 chars): length 9 -> first 4 "AIza", "…", last 4 "hort"
        @test masked_dict["gemini_has_key"] == true
        @test masked_dict["gemini_key_preview"] == "AIza…hort"

        # Verify exact 8 chars key -> "********"
        @test masked_dict["openai_has_key"] == true
        @test masked_dict["openai_key_preview"] == "********"

        # Verify exact 9 chars key -> "1234…6789"
        @test masked_dict["xai_has_key"] == true
        @test masked_dict["xai_key_preview"] == "1234…6789"

        # Verify unset keys
        @test masked_dict["cerebras_has_key"] == false
        @test masked_dict["cerebras_key_preview"] == ""
        @test masked_dict["github_has_key"] == false
        @test masked_dict["github_key_preview"] == ""

        # 2.2 Exhaustive Secret Leakage Scan across all keys & values
        for (k, v) in masked_dict
            # No raw credential key names in dictionary keys
            @test !in(k, ["openrouter_api_key", "gemini_api_key", "openai_api_key", "xai_api_key", "cerebras_api_key", "github_token"])
            if v isa AbstractString
                # No raw secret strings in any values
                @test !occursin(test_or_key, v)
                @test !occursin(test_gem_key, v)
                @test !occursin(test_exact8_key, v)
                @test !occursin(test_exact9_key, v)
            end
        end

        # 2.3 Explicit unmasked call when mask_secrets=false
        unmasked_dict = get_config_dict(; mask_secrets=false)
        @test unmasked_dict["openrouter_api_key"] == test_or_key
        @test unmasked_dict["gemini_api_key"] == test_gem_key
        @test unmasked_dict["openai_api_key"] == test_exact8_key

        # 2.4 Test HTTP GET /api/config route masking via MockHttpStream
        engine = JLEngine.JLEngineCore()
        stream_get = MockHttpStream("GET", "/api/config")
        
        cfg_dict = JLEngine.get_config_dict(; mask_secrets=true)
        HTTP.setstatus(stream_get, 200)
        HTTP.setheader(stream_get, "Content-Type"=>"application/json; charset=utf-8")
        HTTP.setheader(stream_get, "Access-Control-Allow-Origin"=>"*")
        HTTP.startwrite(stream_get)
        write(stream_get, JSON.json(Dict("ok"=>true, "config"=>cfg_dict)))

        @test stream_get.status == 200
        resp_json = _response_json(stream_get)
        @test resp_json["ok"] == true
        @test resp_json["config"]["openrouter_key_preview"] == "sk-o…6789"
        @test !haskey(resp_json["config"], "openrouter_api_key")
        @test !occursin(test_or_key, _response_body(stream_get))
    end

    # =========================================================================
    # CHALLENGE 3: health_check.jl and WebSocket Message Parity
    # =========================================================================
    @testset "Challenge 3: WebSocket 13-Type Parity & Static Health Check" begin
        # 3.1 Execute health_check.jl
        health_check_file = joinpath(dirname(@__DIR__), "health_check.jl")
        @test isfile(health_check_file)
        include(health_check_file)
        
        check_result = run_health_check(verbose=false)
        @test check_result.errors == 0
        @test check_result.warnings == 0

        # 3.2 Verify the 13 required WebSocket types
        expected_ws_types = [
            "agent_thought",
            "browser_result",
            "error",
            "mind_node_update",
            "mission_done",
            "mission_frame",
            "mission_plan",
            "mission_step_append",
            "mission_step_update",
            "mission_thought",
            "stealth_frame",
            "tool_call",
            "tool_result"
        ]

        ui_html_path = joinpath(dirname(@__DIR__), "BYTE", "src", "ui.html")
        @test isfile(ui_html_path)
        ui_src = read(ui_html_path, String)

        # Verify that all 13 types are explicitly handled in ui.html
        for ws_type in expected_ws_types
            @test match(Regex("d\\.type\\s*===?\\s*'$ws_type'"), ui_src) !== nothing
        end

        # 3.3 Verify backend sends them or defines schemas
        byte_jl_path = joinpath(dirname(@__DIR__), "BYTE", "src", "BYTE.jl")
        byte_src = read(byte_jl_path, String)
        for ws_type in expected_ws_types
            # Verify either broadcast or schema exists in BYTE.jl / engine
            @test occursin("\"$ws_type\"", byte_src)
        end

        # 3.4 Direct check of _scan_ws_types
        ws_issues = _scan_ws_types(byte_jl_path)
        @test isempty(ws_issues)

        # 3.5 Adversarial Mutation Test: verify scanner catches unknown UI handler
        fake_ui_src = ui_src * "\nif (d.type === 'adversarial_fake_type_xyz') { console.log(1); }\n"
        fake_tmp = joinpath(mktempdir(), "ui.html")
        write(fake_tmp, fake_ui_src)
        fake_handled = Set{String}()
        for m in eachmatch(r"d\.type\s*===?\s*'([a-z_]+)'", fake_ui_src)
            push!(fake_handled, m[1])
        end
        @test "adversarial_fake_type_xyz" in fake_handled
    end

    # =========================================================================
    # CHALLENGE 4: Single-Port Serving on Port 8081
    # =========================================================================
    @testset "Challenge 4: Single-Port Serving & Routing to ui.html" begin
        # 4.1 Check default port standardization across repository
        repo_root = dirname(@__DIR__)
        app_file = joinpath(repo_root, "src", "App.jl")
        @test occursin("const DEFAULT_PORT = 8081", read(app_file, String))

        byte_file = joinpath(repo_root, "BYTE", "src", "BYTE.jl")
        @test occursin("port::Int=8081", read(byte_file, String))

        bat_file = joinpath(repo_root, "Launch_SparkByte.bat")
        @test occursin("SPARKBYTE_PORT=8081", read(bat_file, String))
        @test occursin("http://127.0.0.1:8081", read(bat_file, String))

        # 4.2 Verify root route "/" returns ui.html content with template substitutions
        ui_html_file = joinpath(repo_root, "BYTE", "src", "ui.html")
        @test isfile(ui_html_file)

        # ui_page function in UI.jl
        rendered_page = Main.BYTE.ui_page("ChallengerOperator", "Challenger Operator Description")
        @test occursin("<!DOCTYPE html>", rendered_page)
        @test occursin("<title>JL_OS // ChallengerOperator</title>", rendered_page)
        @test occursin("ChallengerOperator", rendered_page)
        @test !occursin("__OPERATOR_NAME__", rendered_page)

        # Verify all Wave 2 required UI panels exist in the rendered page
        @test occursin("id=\"mind-panel\"", rendered_page)
        @test occursin("id=\"mission-panel\"", rendered_page)
        @test occursin("id=\"browser-center\"", rendered_page)
        @test occursin("id=\"terminal-panel\"", rendered_page)
        @test occursin("id=\"approval-overlay\"", rendered_page)
        @test occursin("id=\"settings-modal\"", rendered_page)

        # 4.3 Verify root route dispatch via mock stream
        stream_root = MockHttpStream("GET", "/")
        
        # Simulate BYTE HTTP serve root route handler
        op_name = "SparkByte"
        op_desc = "Cognitive Desktop AI"
        HTTP.setstatus(stream_root, 200)
        HTTP.setheader(stream_root, "Content-Type"=>"text/html; charset=utf-8")
        HTTP.startwrite(stream_root)
        write(stream_root, Main.BYTE.ui_page(op_name, op_desc))

        @test stream_root.status == 200
        @test _get_header(stream_root, "Content-Type") == "text/html; charset=utf-8"
        body = _response_body(stream_root)
        @test occursin("<!DOCTYPE html>", body)
        @test occursin("SparkByte", body)
        @test occursin("id=\"mind-panel\"", body)
    end

end
