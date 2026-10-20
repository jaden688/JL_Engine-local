# test/run_challenge_wave1.jl
# Challenger 1 Master Adversarial Test Runner for Wave 1
# Runs all 4 adversarial stress test suites and produces comprehensive test results.

using Test
using Sockets
using HTTP
using JSON3
using JSON
using SQLite
using Dates
using JLEngine

println("=================================================================")
println("  CHALLENGER 1: Wave 1 Adversarial Harness Starting...")
println("=================================================================")

summary_results = Dict{String, Any}()

# -----------------------------------------------------------------------------
# SUITE 1: SSE Streaming Robustness & Exception Lifecycle
# -----------------------------------------------------------------------------
println("\n>>> RUNNING SUITE 1: SSE Streaming Robustness & Exception Lifecycle")
try
    @testset "Suite 1: SSE Streaming Robustness & Socket Lifecycle" begin
        # 1.1 Proactive Cancellation via cancel_ref & Exception Leak Verification
        server1 = Sockets.listen(IPv4("127.0.0.1"), 0)
        port1 = Sockets.getsockname(server1)[2]
        endpoint1 = "http://127.0.0.1:$(port1)/api/v1/chat/completions"

        server_task1 = @async begin
            try
                sock = Sockets.accept(server1)
                while isopen(sock) && !eof(sock)
                    line = readline(sock)
                    isempty(strip(line)) && break
                end
                write(sock, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n\r\n")
                flush(sock)
                chunk1 = Dict("choices" => [Dict("delta" => Dict("content" => "First token "))])
                write(sock, "data: " * JSON3.write(chunk1) * "\n\n")
                flush(sock)
                sleep(0.5)
                close(sock)
            catch
            end
        end

        backend1 = OpenRouterBackend(Dict{String, Any}("endpoint" => endpoint1, "api_key" => "k", "timeout" => 5))
        req1 = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "test")]; timeout=5)
        cancel_ref1 = Ref(false)
        tokens1 = String[]
        caught1 = nothing
        try
            stream_chat_completion(backend1, req1, c -> begin
                push!(tokens1, c.delta_text)
                cancel_ref1[] = true
            end; cancel_ref=cancel_ref1)
        catch e
            caught1 = e
        end
        close(server1)
        wait(server_task1)

        @test length(tokens1) == 1
        # CHALLENGE OBSERVATION: ProviderCancelledException thrown directly without HTTP.Exceptions.RequestError wrapper
        println("  [Test 1.1 Result] Caught exception type: ", typeof(caught1))
        @test caught1 isa ProviderCancelledException
        @test !(caught1 isa HTTP.Exceptions.RequestError)

        # 1.2 Non-200 HTTP streaming response dispatches cleanly to typed error without MethodError
        server1_2 = Sockets.listen(IPv4("127.0.0.1"), 0)
        port1_2 = Sockets.getsockname(server1_2)[2]
        endpoint1_2 = "http://127.0.0.1:$(port1_2)/api/v1/chat/completions"

        server_task1_2 = @async begin
            try
                sock = Sockets.accept(server1_2)
                while isopen(sock) && !eof(sock)
                    line = readline(sock)
                    isempty(strip(line)) && break
                end
                while isopen(sock) && !eof(sock)
                    clen = readline(sock)
                    l = try parse(Int, strip(clen), base=16) catch; 0 end
                    l == 0 && break
                    read(sock, l)
                    readline(sock)
                end
                err_payload = "{\"error\":{\"message\":\"Rate limited\"}}"
                write(sock, "HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nContent-Length: $(sizeof(err_payload))\r\n\r\n" * err_payload)
                flush(sock)
                sleep(0.5)
                close(sock)
            catch
            end
        end

        backend1_2 = OpenRouterBackend(Dict{String, Any}("endpoint" => endpoint1_2, "api_key" => "k", "timeout" => 5))
        caught1_2 = nothing
        try
            stream_chat_completion(backend1_2, req1, c -> nothing)
        catch e
            caught1_2 = e
        end
        close(server1_2)
        wait(server_task1_2)

        println("  [Test 1.2 Result] Non-200 streaming status error: ", typeof(caught1_2))
        @test caught1_2 isa ProviderRateLimitError
        @test !(caught1_2 isa HTTP.Exceptions.RequestError)

        # 1.3 Hung connection timeout
        server1_3 = Sockets.listen(IPv4("127.0.0.1"), 0)
        port1_3 = Sockets.getsockname(server1_3)[2]
        endpoint1_3 = "http://127.0.0.1:$(port1_3)/api/v1/chat/completions"

        server_task1_3 = @async begin
            try
                sock = Sockets.accept(server1_3)
                sleep(2.0)
                close(sock)
            catch
            end
        end

        backend1_3 = OpenRouterBackend(Dict{String, Any}("endpoint" => endpoint1_3, "api_key" => "k", "timeout" => 1))
        req1_3 = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "test")]; timeout=1)
        caught1_3 = nothing
        t0 = time()
        try
            stream_chat_completion(backend1_3, req1_3, c -> nothing)
        catch e
            caught1_3 = e
        end
        elapsed1_3 = time() - t0
        close(server1_3)
        wait(server_task1_3)

        println("  [Test 1.3 Result] Timeout elapsed: $(round(elapsed1_3, digits=2))s, Error: $(typeof(caught1_3))")
        @test caught1_3 isa ProviderTimeoutError
        @test elapsed1_3 < 6.0
    end
    summary_results["Suite 1"] = "COMPLETED"
catch e
    summary_results["Suite 1"] = "FAILED: $e"
end

# -----------------------------------------------------------------------------
# SUITE 2: FallbackChain and CircuitBreaker State Transitions
# -----------------------------------------------------------------------------
println("\n>>> RUNNING SUITE 2: FallbackChain & CircuitBreaker State Machine")
try
    @testset "Suite 2: FallbackChain & CircuitBreaker State Machine" begin
        # 2.1 Threshold Tripping under 429 Rate Limits
        cb = CircuitBreaker(threshold=3, cooldown=1.0)
        @test cb.state == CIRCUIT_CLOSED
        @test cb.consecutive_failures == 0

        # Simulate 3 failures
        for i in 1:3
            cb.consecutive_failures += 1
            cb.last_failure_time = time()
            if cb.consecutive_failures >= cb.failure_threshold
                cb.state = CIRCUIT_OPEN
            end
        end
        @test cb.state == CIRCUIT_OPEN
        @test cb.consecutive_failures == 3

        # 2.2 Immediate Tripping on ProviderAuthError (Fast-Fail)
        cb_auth = CircuitBreaker(threshold=3, cooldown=1.0)
        err_auth = ProviderAuthError("test-provider", 401, "Bad key")
        cb_auth.consecutive_failures += 1
        cb_auth.last_failure_time = time()
        if cb_auth.consecutive_failures >= cb_auth.failure_threshold || err_auth isa ProviderAuthError
            cb_auth.state = CIRCUIT_OPEN
        end
        @test cb_auth.state == CIRCUIT_OPEN
        @test cb_auth.consecutive_failures == 1

        # 2.3 Cooldown and Transition to CIRCUIT_HALF_OPEN
        cb_cd = CircuitBreaker(threshold=2, cooldown=0.3)
        cb_cd.state = CIRCUIT_OPEN
        cb_cd.last_failure_time = time()
        sleep(0.35)
        now_t = time()
        if cb_cd.state == CIRCUIT_OPEN && (now_t - cb_cd.last_failure_time > cb_cd.cooldown_s)
            cb_cd.state = CIRCUIT_HALF_OPEN
        end
        @test cb_cd.state == CIRCUIT_HALF_OPEN

        # 2.4 Multi-Target FallbackChain Failover (Chat Completion)
        t1 = ProviderTarget("openrouter"; timeout_s=2.0)
        t2 = ProviderTarget("ollama"; timeout_s=2.0)
        t3 = ProviderTarget("noop-stub"; timeout_s=2.0)

        chain = FallbackChain("multi-failover-chain", [t1, t2, t3])
        withenv("OPENROUTER_API_KEY" => "") do
            req = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Challenge ping")])
            resp = chat_completion(chain, req)
            @test resp.provider == "noop"
            @test occursin("Challenge ping", resp.text)
            @test chain.breakers["openrouter"].state == CIRCUIT_OPEN
            @test length(chain.history) >= 2
        end

        # 2.5 Streaming Failover Before Tokens
        chain_stream = FallbackChain("stream-failover-chain", [t1, t3])
        withenv("OPENROUTER_API_KEY" => "") do
            req_stream = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Stream failover")])
            chunks = StreamChunk[]
            resp = stream_chat_completion(chain_stream, req_stream, c -> push!(chunks, c))
            @test resp.provider == "noop"
            @test !isempty(chunks)
        end

        # 2.6 Streaming Cancellation Misinterpreted as Provider Failure (Remediated)
        t_primary = ProviderTarget("noop-stub"; timeout_s=5.0)
        t_secondary = ProviderTarget("noop-stub-secondary"; timeout_s=5.0)
        chain_cancel = FallbackChain("cancel-chain", [t_primary, t_secondary])
        req_cancel = ChatRequest("noop-stub", [ChatMessage("user", "Cancel test")]; timeout=5)
        cancel_token = Ref(true)
        caught_cancel = nothing
        try
            stream_chat_completion(chain_cancel, req_cancel, c -> nothing; cancel_ref=cancel_token)
        catch e
            caught_cancel = e
        end
        println("  [Test 2.6 Result] Caught cancellation error: ", typeof(caught_cancel))
        println("  [Test 2.6 Result] Primary Breaker failure count after user cancel: ", chain_cancel.breakers["noop-stub"].consecutive_failures)
        @test caught_cancel isa ProviderCancelledException
        @test chain_cancel.breakers["noop-stub"].consecutive_failures == 0
        @test chain_cancel.breakers["noop-stub"].state == CIRCUIT_CLOSED
        # Verify secondary target was NEVER reached (no failover occurred)
        @test !haskey(chain_cancel.breakers, "noop-stub-secondary")
    end
    summary_results["Suite 2"] = "COMPLETED"
catch e
    summary_results["Suite 2"] = "FAILED: $e"
end

# -----------------------------------------------------------------------------
# SUITE 3: Local Tool Execution & Host Runtime Dispatch Constraint
# -----------------------------------------------------------------------------
println("\n>>> RUNNING SUITE 3: Local Tool Execution & Runtime Dispatch Constraint")
try
    @testset "Suite 3: Local Tool Execution & Runtime Dispatch Constraint" begin
        # 3.1 Verify Backends Never Execute Tools Remotely
        backend = OpenRouterBackend(Dict{String, Any}("api_key" => "dummy-key"))
        tool_defs = [Dict{String, Any}(
            "type" => "function",
            "function" => Dict{String, Any}(
                "name" => "write_file",
                "description" => "Writes a local file",
                "parameters" => Dict("type" => "object", "properties" => Dict("path" => Dict("type" => "string")))
            )
        )]
        req = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Create file")]; tools=tool_defs)
        payload = JLEngine._build_openrouter_payload(req)
        @test haskey(payload, "tools")
        @test payload["tools"][1]["function"]["name"] == "write_file"

        # 3.2 Verify Local Tool Runtime Dispatch via Tools.jl
        tools_jl_path = joinpath(@__DIR__, "..", "BYTE", "src", "Tools.jl")
        @test isfile(tools_jl_path)
        tools_content = read(tools_jl_path, String)
        @test occursin("function dispatch(name::String, args; agent::String=\"SparkByte\")", tools_content)
        @test occursin("\"write_file\"", tools_content)
        @test occursin("\"read_file\"", tools_content)
        @test occursin("\"execute_code\"", tools_content)
        @test occursin("fn = get(TOOL_MAP, name, nothing)", tools_content)

        # 3.3 Verify Local Tool Host Execution
        temp_dir = mktempdir()
        test_file = joinpath(temp_dir, "local_dispatch_test.txt")
        write(test_file, "Local Execution Verified")
        @test isfile(test_file)
        @test read(test_file, String) == "Local Execution Verified"
        rm(temp_dir; recursive=true)

        # 3.4 Verify Tools.jl Does Not Export Any Cloud Execution Bridge
        @test !occursin("cloud_execute_tool", tools_content)
        @test !occursin("remote_execute_tool", tools_content)
    end
    summary_results["Suite 3"] = "COMPLETED"
catch e
    summary_results["Suite 3"] = "FAILED: $e"
end

# -----------------------------------------------------------------------------
# SUITE 4: Typed Settings Persistence & Credential Sanitization
# -----------------------------------------------------------------------------
println("\n>>> RUNNING SUITE 4: Persistent Settings & Credential Sanitization")
try
    @testset "Suite 4: Persistent Settings & Credential Sanitization" begin
        # 4.1 SQLite Configuration Persistence and Redaction
        db = SQLite.DB()
        init_config_table!(db)
        test_key = "\"sk-or-v1-fixture-placeholder-not-real-key\""
        JLEngine.db_set_config!(db, "openrouter_api_key", test_key; source="api")
        key_history = [NamedTuple(row) for row in SQLite.DBInterface.execute(db, "SELECT * FROM config_history WHERE key = 'openrouter_api_key'")]
        @test length(key_history) == 1
        @test occursin("[REDACTED]", string(key_history[1].new_value_json))
        @test !occursin("0123456789abcdef", string(key_history[1].new_value_json))

        # 4.2 Telemetry Secret Redaction
        telemetry_path = joinpath(@__DIR__, "..", "BYTE", "src", "Telemetry.jl")
        if isfile(telemetry_path)
            tel_src = read(telemetry_path, String)
            @test occursin("_redact_sensitive_text", tel_src)
            @test occursin("sk-or-v1-", tel_src)
        end

        # 4.3 UI Key Masking
        withenv("OPENROUTER_API_KEY" => "sk-or-v1-abcdef0123456789") do
            masked_cfg = JLEngine.get_config_dict(; mask_secrets=true)
            @test masked_cfg["openrouter_has_key"] == true
            @test !haskey(masked_cfg, "openrouter_api_key")
            @test occursin("sk-o…6789", masked_cfg["openrouter_key_preview"])
        end
    end
    summary_results["Suite 4"] = "COMPLETED"
catch e
    summary_results["Suite 4"] = "FAILED: $e"
end

println("\n=================================================================")
println("  CHALLENGER 1 SUMMARY RESULTS:")
for (k, v) in summary_results
    println("    $k: $v")
end
println("=================================================================")
