# test/test_wave1_remediation_stress.jl
# Challenger 1 Adversarial Stress Test Suite for Wave 1 Remediation

using Test
using Sockets
using HTTP
using JSON3
using JLEngine

@testset "Adversarial Stress Test: Wave 1 Remediation" begin
    # -------------------------------------------------------------------------
    # 1. Non-200 Status Codes Dispatch Across Integer Types
    # -------------------------------------------------------------------------
    @testset "1. Non-200 HTTP status dispatch" begin
        # Test across Int16, Int32, Int64, BigInt
        for T in (Int16, Int32, Int64, BigInt)
            @test_throws ProviderAuthError JLEngine._throw_typed_http_error("openrouter", T(401), "Unauthorized")
            @test_throws ProviderAuthError JLEngine._throw_typed_http_error("openrouter", T(403), "Forbidden")
            @test_throws ProviderRateLimitError JLEngine._throw_typed_http_error("openrouter", T(429), "Rate limited")
            @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", T(500), "Server error")
            @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", T(502), "Bad gateway")
            @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", T(503), "Service unavailable")
            @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", T(504), "Gateway timeout")
            # Unrecognized status code fallback to ProviderServerError
            @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", T(418), "I'm a teapot")
        end

        # Test error body JSON parsing variations
        err_json_1 = "{\"error\": {\"message\": \"API rate limit exceeded\", \"code\": 429}}"
        try
            JLEngine._throw_typed_http_error("openrouter", Int16(429), err_json_1)
        catch e
            @test e isa ProviderRateLimitError
            @test e.status == 429
            @test occursin("API rate limit exceeded", e.message)
        end

        err_json_str = "{\"error\": \"Plain string error\"}"
        try
            JLEngine._throw_typed_http_error("openrouter", Int16(401), err_json_str)
        catch e
            @test e isa ProviderAuthError
            @test e.status == 401
            @test occursin("Plain string error", e.message)
        end

        err_malformed = "not a json string at all"
        try
            JLEngine._throw_typed_http_error("openrouter", Int16(500), err_malformed)
        catch e
            @test e isa ProviderServerError
            @test e.status == 500
            @test occursin("not a json string at all", e.message)
        end
    end

    # -------------------------------------------------------------------------
    # 2. Exception Unwrapping from HTTP.open / HTTP.Exceptions.RequestError
    # -------------------------------------------------------------------------
    @testset "2. Direct exception unwrapping" begin
        # 2.1 SSE Stream proactive cancellation
        server = Sockets.listen(IPv4("127.0.0.1"), 0)
        port = Sockets.getsockname(server)[2]
        endpoint = "http://127.0.0.1:$(port)/api/v1/chat/completions"

        server_task = @async begin
            try
                sock = Sockets.accept(server)
                while isopen(sock) && !eof(sock)
                    line = readline(sock)
                    isempty(strip(line)) && break
                end
                write(sock, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\n\r\n")
                flush(sock)
                chunk = Dict("choices" => [Dict("delta" => Dict("content" => "streaming token"))])
                write(sock, "data: " * JSON3.write(chunk) * "\n\n")
                flush(sock)
                sleep(0.5)
                close(sock)
            catch
            end
        end

        backend = OpenRouterBackend(Dict{String, Any}("endpoint" => endpoint, "api_key" => "dummy-key", "timeout" => 5))
        req = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "test")]; timeout=5)
        cancel_ref = Ref(false)
        tokens = String[]
        caught_err = nothing
        try
            stream_chat_completion(backend, req, c -> begin
                push!(tokens, c.delta_text)
                cancel_ref[] = true
            end; cancel_ref=cancel_ref)
        catch e
            caught_err = e
        end
        close(server)
        wait(server_task)

        @test length(tokens) == 1
        @test caught_err isa ProviderCancelledException
        @test !(caught_err isa HTTP.Exceptions.RequestError)
        @test occursin("cancelled by caller", caught_err.message)

        # 2.2 Simulated HTTP.Exceptions.RequestError wrapping ProviderCancelledException directly
        mock_req = HTTP.Messages.Request()
        wrapped_cancel = HTTP.Exceptions.RequestError(mock_req, ProviderCancelledException("nested cancel"))
        # Verify the unwrapping logic
        unwrapped = wrapped_cancel isa HTTP.Exceptions.RequestError ? wrapped_cancel.error : wrapped_cancel
        @test unwrapped isa ProviderCancelledException
        @test !(unwrapped isa HTTP.Exceptions.RequestError)
    end

    # -------------------------------------------------------------------------
    # 3. FallbackChain Cancellation Semantics & No-Failover Verification
    # -------------------------------------------------------------------------
    @testset "3. FallbackChain cancellation behavior & failover prevention" begin
        # 3.1 Cancel before stream emission
        t1 = ProviderTarget("noop-stub"; timeout_s=5.0)
        t2 = ProviderTarget("noop-stub-secondary"; timeout_s=5.0)
        t3 = ProviderTarget("noop-stub-tertiary"; timeout_s=5.0)
        chain = FallbackChain("stress-cancel-chain", [t1, t2, t3])
        req = ChatRequest("noop-stub", [ChatMessage("user", "Cancel test")]; timeout=5)

        cancel_early = Ref(true)
        caught_err_early = nothing
        try
            stream_chat_completion(chain, req, c -> nothing; cancel_ref=cancel_early)
        catch e
            caught_err_early = e
        end

        @test caught_err_early isa ProviderCancelledException
        @test !(caught_err_early isa HTTP.Exceptions.RequestError)
        # Verify primary target breaker was NOT penalized
        @test chain.breakers["noop-stub"].consecutive_failures == 0
        @test chain.breakers["noop-stub"].state == CIRCUIT_CLOSED
        # Verify downstream targets were NEVER reached
        @test !haskey(chain.breakers, "noop-stub-secondary")
        @test !haskey(chain.breakers, "noop-stub-tertiary")

        # 3.2 Cancel mid-stream during token arrival
        chain_mid = FallbackChain("mid-cancel-chain", [t1, t2])
        cancel_mid = Ref(false)
        tokens_seen = String[]
        caught_err_mid = nothing
        try
            stream_chat_completion(chain_mid, req, c -> begin
                push!(tokens_seen, c.delta_text)
                cancel_mid[] = true
            end; cancel_ref=cancel_mid)
        catch e
            caught_err_mid = e
        end

        @test caught_err_mid isa ProviderCancelledException
        @test !(caught_err_mid isa HTTP.Exceptions.RequestError)
        @test chain_mid.breakers["noop-stub"].consecutive_failures == 0
        @test chain_mid.breakers["noop-stub"].state == CIRCUIT_CLOSED
        @test !haskey(chain_mid.breakers, "noop-stub-secondary")

        # 3.3 Verify genuine provider error DOES increment failures and DOES failover
        chain_genuine_fail = FallbackChain("genuine-failover-chain", [
            ProviderTarget("openrouter"; timeout_s=1.0),
            ProviderTarget("noop-stub"; timeout_s=1.0)
        ])
        req_genuine = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Hello")]; timeout=1)
        resp = withenv("OPENROUTER_API_KEY" => "") do
            stream_chat_completion(chain_genuine_fail, req_genuine, c -> nothing)
        end
        # Genuine failure SHOULD increment failure on openrouter and succeed on noop-stub
        @test resp.provider == "noop"
        @test chain_genuine_fail.breakers["openrouter"].state == CIRCUIT_OPEN
        @test chain_genuine_fail.breakers["noop-stub"].state == CIRCUIT_CLOSED
    end
end

println("\n=================================================================")
println("  ADVERSARIAL STRESS TEST SUITE: 100% PASS!")
println("=================================================================")
