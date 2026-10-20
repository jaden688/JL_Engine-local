using Test
using JLEngine
using SQLite
using Sockets
using JSON3

@testset "Backends: Typed Taxonomy & Structs" begin
    # ChatMessage
    msg = ChatMessage("user", "Hello Omni!")
    @test msg.role == "user"
    @test msg.content == "Hello Omni!"
    @test msg.name === nothing
    @test msg.tool_calls === nothing
    @test msg.tool_call_id === nothing

    tool_msg = ChatMessage("tool", "{\"result\": 42}"; tool_call_id="call_123")
    @test tool_msg.role == "tool"
    @test tool_msg.tool_call_id == "call_123"

    # ChatRequest
    req = ChatRequest("deepseek/deepseek-v4-flash", [msg]; temperature=0.5, top_p=0.9, timeout=60)
    @test req.model == "deepseek/deepseek-v4-flash"
    @test length(req.messages) == 1
    @test req.temperature == 0.5
    @test req.top_p == 0.9
    @test req.timeout == 60
    @test req.stream == false

    # TokenUsage
    usage = TokenUsage(100, 50, 150, 0.002)
    @test usage.prompt_tokens == 100
    @test usage.completion_tokens == 50
    @test usage.total_tokens == 150

    # StreamChunk
    chunk = StreamChunk("hello", "thinking step", nothing, nothing, nothing)
    @test chunk.delta_text == "hello"
    @test chunk.reasoning_delta == "thinking step"
    @test chunk.finish_reason === nothing

    # ChatResponse
    resp = ChatResponse("Hello there!", "reasoning", "model-x", "provider-y", "stop", usage, Dict{String, Any}[], Dict{String, Any}())
    @test resp.text == "Hello there!"
    @test resp.reasoning == "reasoning"
    @test resp.model == "model-x"
    @test resp.provider == "provider-y"
    @test resp.finish_reason == "stop"
    @test resp.usage.total_tokens == 150

    # ModelInfo
    m_info = ModelInfo("deepseek/deepseek-v4-flash", "DeepSeek V4", "openrouter", 64000, 0.14, 0.28, true, true, false, false, "Test model")
    @test m_info.id == "deepseek/deepseek-v4-flash"
    @test m_info.context_length == 64000
    @test m_info.supports_streaming == true
    @test m_info.supports_tools == true

    # ConnectionStatus
    c_status = ConnectionStatus(true, "openrouter", "https://openrouter.ai/api/v1", 45.2, nothing, 460)
    @test c_status.ok == true
    @test c_status.latency_ms == 45.2
    @test c_status.models_available == 460
end

@testset "Backends: Exception Taxonomy" begin
    auth_err = ProviderAuthError("openrouter", 401, "Invalid API Key")
    @test auth_err isa ProviderError
    @test auth_err.status == 401

    rate_err = ProviderRateLimitError("openrouter", 429, 2.5, "Rate limit exceeded")
    @test rate_err isa ProviderError
    @test rate_err.retry_after_s == 2.5

    timeout_err = ProviderTimeoutError("openrouter", 120.0, "Request timed out")
    @test timeout_err isa ProviderError
    @test timeout_err.timeout_s == 120.0

    server_err = ProviderServerError("openrouter", 502, "Bad Gateway")
    @test server_err isa ProviderError
    @test server_err.status == 502

    conn_err = ProviderConnectionError("ollama", "Connection refused")
    @test conn_err isa ProviderError

    cancel_err = ProviderCancelledException("Cancelled by caller")
    @test cancel_err isa ProviderError

    stream_err = ProviderStreamInterruptedError("openrouter", "Interrupted mid-stream", "partial text")
    @test stream_err isa ProviderError
    @test stream_err.partial_text == "partial text"
end

@testset "Backends: Hierarchy & AbstractBackend Interface" begin
    noop = NoopBackend(Dict{String, Any}("id" => "noop-stub"))
    @test noop isa AbstractBackend

    or = OpenRouterBackend(Dict{String, Any}("endpoint" => "https://openrouter.ai/api/v1/chat/completions"))
    @test or isa AbstractBackend

    ollama = OllamaBackend(Dict{String, Any}("base_url" => "http://127.0.0.1:11434"))
    @test ollama isa AbstractBackend

    gemini = GoogleGeminiBackend(Dict{String, Any}("endpoint" => "https://generativelanguage.googleapis.com/v1beta"))
    @test gemini isa AbstractBackend

    custom = CustomHTTPBackend(Dict{String, Any}("endpoint" => "http://127.0.0.1:8000/v1"))
    @test custom isa AbstractBackend
end

@testset "Backends: NoopBackend Execution & Streaming" begin
    noop = NoopBackend(Dict{String, Any}())
    req = ChatRequest("noop-stub", [ChatMessage("user", "Ping test")])

    # Synchronous completion
    resp = chat_completion(noop, req)
    @test resp.provider == "noop"
    @test resp.model == "noop-stub"
    @test occursin("Ping test", resp.text)
    @test resp.finish_reason == "stop"

    # Streaming completion
    chunks = StreamChunk[]
    stream_resp = stream_chat_completion(noop, req, c -> push!(chunks, c))
    @test !isempty(chunks)
    @test join([c.delta_text for c in chunks]) == resp.text
    @test stream_resp.text == resp.text

    # Cancellation token abort
    cancel_ref = Ref(true)
    @test_throws ProviderCancelledException stream_chat_completion(noop, req, c -> nothing; cancel_ref=cancel_ref)

    # Model catalog & Connection test
    models = fetch_model_catalog(noop)
    @test length(models) == 1
    @test models[1].id == "noop-stub"

    c_stat = test_connection(noop)
    @test c_stat.ok == true
    @test c_stat.provider == "noop"

    # Legacy generate wrapper
    gen_text, gen_meta = generate(noop, [Dict("role" => "user", "content" => "Legacy call")])
    @test occursin("Legacy call", gen_text)
    @test gen_meta["provider"] == "noop"
end

@testset "Backends: OpenRouter Auth Failure & Diagnostics" begin
    # With empty API key, must throw ProviderAuthError
    backend = OpenRouterBackend(Dict{String, Any}("api_key" => ""))
    # Ensure environment does not accidentally supply one for this isolated test
    withenv("OPENROUTER_API_KEY" => "") do
        req = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Hello")])
        @test_throws ProviderAuthError chat_completion(backend, req)
        @test_throws ProviderAuthError stream_chat_completion(backend, req, c -> nothing)

        # Connection test reports failure gracefully without throwing
        c_status = test_connection(backend)
        @test c_status.ok == false
        @test occursin("API key is not set", c_status.error_message)
    end
end

@testset "Backends: FallbackChain & Circuit Breaker" begin
    # Setup a chain: Target 1 fails (unconfigured OpenRouter), Target 2 succeeds (NoopBackend)
    t1 = ProviderTarget("openrouter"; timeout_s=5.0)
    t2 = ProviderTarget("noop-stub"; timeout_s=5.0)
    chain = FallbackChain("test-chain", [t1, t2])

    withenv("OPENROUTER_API_KEY" => "") do
        req = ChatRequest("deepseek/deepseek-v4-flash", [ChatMessage("user", "Failover ping")])

        # Chat completion should gracefully fail over from OpenRouter to Noop
        resp = chat_completion(chain, req)
        @test resp.provider == "noop"
        @test occursin("Failover ping", resp.text)

        # Check circuit breaker tripped for Target 1
        b1 = chain.breakers["openrouter"]
        @test b1.state == CIRCUIT_OPEN
        @test !isempty(chain.history)
        @test chain.history[1]["target"] == "openrouter"

        # Streaming completion should also fail over
        chunks = StreamChunk[]
        stream_resp = stream_chat_completion(chain, req, c -> push!(chunks, c))
        @test stream_resp.provider == "noop"
        @test !isempty(chunks)
    end
end

@testset "Backends: CircuitBreaker State Machine" begin
    cb = CircuitBreaker(threshold=3, cooldown=2.0)
    @test cb.state == CIRCUIT_CLOSED
    @test cb.consecutive_failures == 0

    cb.consecutive_failures = 1
    @test cb.state == CIRCUIT_CLOSED

    cb.consecutive_failures = 3
    cb.state = CIRCUIT_OPEN
    cb.last_failure_time = time()
    @test cb.state == CIRCUIT_OPEN

    # Within cooldown, remains open
    @test time() - cb.last_failure_time < cb.cooldown_s

    # Reset
    cb.state = CIRCUIT_CLOSED
    cb.consecutive_failures = 0
    @test cb.state == CIRCUIT_CLOSED
end

@testset "Backends: Model Catalog SQLite Persistence" begin
    # In-memory test SQLite DB
    db = SQLite.DB()
    init_model_catalog_table!(db)

    test_models = [
        ModelInfo("test/model-1", "Test Model 1", "test", 8192, 0.5, 1.5, true, true, false, false, "Desc 1"),
        ModelInfo("test/model-2", "Test Model 2", "test", 16384, 1.0, 2.0, true, true, true, true, "Desc 2"),
    ]

    JLEngine._persist_model_catalog_sqlite(test_models, db)
    loaded = JLEngine._load_model_catalog_sqlite(db)

    @test length(loaded) == 2
    @test loaded[1].id == "test/model-1"
    @test loaded[1].context_length == 8192
    @test loaded[2].supports_vision == true
    @test loaded[2].supports_reasoning == true
end

@testset "Backends: Registry & Role Management" begin
    set_backend_model!("openrouter", "meta-llama/llama-3.3-70b-instruct")
    @test JLEngine.BACKEND_REGISTRY["openrouter"]["model"] == "meta-llama/llama-3.3-70b-instruct"

    # Reset back to default
    set_backend_model!("openrouter", "deepseek/deepseek-v4-flash")
    @test JLEngine.BACKEND_REGISTRY["openrouter"]["model"] == "deepseek/deepseek-v4-flash"

    configure_backends!(brain_id="openrouter", tool_id="noop-stub")
    @test JLEngine.ACTIVE_BACKENDS["brain"] == "openrouter"
    @test JLEngine.ACTIVE_BACKENDS["tool"] == "noop-stub"

    b_brain = get_brain_backend()
    @test b_brain isa OpenRouterBackend

    b_tool = get_tool_backend()
    @test b_tool isa NoopBackend

    # Restore default
    configure_backends!(brain_id="openrouter", tool_id="openrouter")
end

@testset "Backends: SSE Streaming Exception Handling & Cancellation" begin
    # 1. Non-200 typed HTTP status dispatch (Int16 compatibility)
    @test_throws ProviderAuthError JLEngine._throw_typed_http_error("openrouter", Int16(401), "Unauthorized")
    @test_throws ProviderRateLimitError JLEngine._throw_typed_http_error("openrouter", Int16(429), "Rate limited")
    @test_throws ProviderServerError JLEngine._throw_typed_http_error("openrouter", Int16(503), "Service unavailable")

    # 2. OpenRouter SSE streaming cancellation throws ProviderCancelledException directly
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
            chunk = Dict("choices" => [Dict("delta" => Dict("content" => "token1"))])
            write(sock, "data: " * JSON3.write(chunk) * "\n\n")
            flush(sock)
            sleep(0.2)
            close(sock)
        catch
        end
    end

    backend = OpenRouterBackend(Dict{String, Any}("endpoint" => endpoint, "api_key" => "k", "timeout" => 5))
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

    # 3. FallbackChain stream cancellation does NOT trip breaker or increment failures
    chain_cancel = FallbackChain("cancel-test-chain", [ProviderTarget("noop-stub"; timeout_s=5.0)])
    req_cancel = ChatRequest("noop-stub", [ChatMessage("user", "Cancel test")]; timeout=5)
    cancel_token = Ref(true)
    caught_chain_err = nothing
    try
        stream_chat_completion(chain_cancel, req_cancel, c -> nothing; cancel_ref=cancel_token)
    catch e
        caught_chain_err = e
    end
    @test caught_chain_err isa ProviderCancelledException
    @test chain_cancel.breakers["noop-stub"].consecutive_failures == 0
    @test chain_cancel.breakers["noop-stub"].state == CIRCUIT_CLOSED
end

