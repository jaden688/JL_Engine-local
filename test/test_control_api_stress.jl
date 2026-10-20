# test/test_control_api_stress.jl
# Adversarial Stress and Concurrency Test Suite for Headless Control API (M2 Wave 2)

using Test
using HTTP
using JSON
using SQLite
using UUIDs
using Dates

# Import project engine and BYTE module
using JLEngine
if !isdefined(Main, :BYTE)
    @eval Main const BYTE = JLEngine.BYTE
end

# ── Mock HTTP Stream with Header and Body Inspection ─────────────────────────
mutable struct MockHttpStream
    status::Int
    headers::Vector{Pair{String, String}}
    body_in::IOBuffer
    body_out::IOBuffer
    started::Bool
end

MockHttpStream(body_str::String="") = MockHttpStream(200, Pair{String,String}[], IOBuffer(body_str), IOBuffer(), false)
HTTP.setstatus(s::MockHttpStream, status::Int) = (s.status = status; status)
HTTP.setheader(s::MockHttpStream, h::Pair) = (push!(s.headers, string(h.first) => string(h.second)); s.headers)
HTTP.startwrite(s::MockHttpStream) = (s.started = true; nothing)
Base.write(s::MockHttpStream, data) = write(s.body_out, data)
Base.read(s::MockHttpStream) = read(s.body_in)

function _response_json(s::MockHttpStream)
    seekstart(s.body_out)
    raw = String(take!(s.body_out))
    isempty(raw) && return Dict{String, Any}()
    return JSON.parse(raw)
end

function _get_header(s::MockHttpStream, name::String)
    for (k, v) in s.headers
        lowercase(k) == lowercase(name) && return v
    end
    return nothing
end

# Helper to invoke router preflight or routes directly
function _mock_request(method::String, target::String, body::String="", headers::Vector{Pair{String,String}}=Pair{String,String}[]; engine=nothing, host="127.0.0.1", port=8081)
    s = MockHttpStream(body)
    for h in headers
        HTTP.setheader(s, h)
    end
    if method == "OPTIONS" && (startswith(target, "/api/") || startswith(target, "/control/"))
        BYTE._http_cors_preflight(s)
    elseif method == "GET" && (target == "/control/state" || startswith(target, "/control/state?"))
        BYTE._handle_control_state_request(s, engine, host, port, BYTE._BOOT_TIME)
    elseif method == "GET" && (target == "/control/tools" || startswith(target, "/control/tools?"))
        BYTE._handle_control_tools_request(s)
    elseif method == "POST" && (target == "/control/dispatch" || startswith(target, "/control/dispatch?"))
        BYTE._handle_control_dispatch_request(s, engine)
    elseif method == "POST" && (target == "/control/cancel" || startswith(target, "/control/cancel?"))
        BYTE._handle_control_cancel_request(s)
    else
        HTTP.setstatus(s, 404)
    end
    return s
end

println("====================================================================")
println("  Control API Adversarial Challenge & Stress Harness")
println("====================================================================")

# Ensure noop-stub is registered for deterministic headless execution
JLEngine.set_brain_backend_id!("noop-stub")
engine = JLEngine.JLEngineCore(JLEngine.EngineConfig(
    root_dir=normpath(joinpath(@__DIR__, "..", "data"))))

@testset "Adversarial 1: /control/state Rapid & Concurrent Stress" begin
    # 1. Basic Schema & Field Verification
    s_init = _mock_request("GET", "/control/state"; engine=engine, port=8081)
    @test s_init.status == 200
    @test _get_header(s_init, "Access-Control-Allow-Origin") == "*"
    @test _get_header(s_init, "Content-Type") == "application/json; charset=utf-8"
    
    data_init = _response_json(s_init)
    @test data_init["ok"] == true
    @test data_init["service"] == "sparkbyte-omni"
    @test data_init["port"] == 8081
    @test haskey(data_init, "active_provider")
    @test haskey(data_init, "current_model")
    @test data_init["loaded_tools_count"] >= 15
    @test data_init["memory_items_count"] >= 0
    @test data_init["connected_clients_count"] >= 0
    @test data_init["uptime"] >= 0.0
    @test haskey(data_init, "active_agent")
    @test haskey(data_init, "gear")
    @test haskey(data_init, "tokens")
    @test haskey(data_init, "timestamp")

    # Custom port reflection check
    s_custom_port = _mock_request("GET", "/control/state"; engine=engine, port=9099)
    data_custom_port = _response_json(s_custom_port)
    @test data_custom_port["port"] == 9099

    # 2. Rapid Sequential Requests (100 in tight loop)
    N_SEQ = 100
    t_start = time()
    uptimes = Float64[]
    for i in 1:N_SEQ
        s = _mock_request("GET", "/control/state"; engine=engine, port=8081)
        @test s.status == 200
        d = _response_json(s)
        @test d["ok"] == true
        @test d["port"] == 8081
        push!(uptimes, Float64(d["uptime"]))
    end
    t_elapsed = time() - t_start
    avg_latency_ms = (t_elapsed / N_SEQ) * 1000.0
    println("  ✓ 100 sequential /control/state requests completed in $(round(t_elapsed, digits=3))s (avg $(round(avg_latency_ms, digits=2))ms/req)")
    @test avg_latency_ms < 20.0 # Sub-20ms per request requirement
    # Verify uptime monotonicity
    @test issorted(uptimes)

    # 3. Concurrent Requests (50 simultaneous requests)
    N_CONCURRENT = 50
    concurrent_results = Vector{Any}(undef, N_CONCURRENT)
    @sync for i in 1:N_CONCURRENT
        @async begin
            s = _mock_request("GET", "/control/state"; engine=engine, port=8081)
            concurrent_results[i] = (status=s.status, json=_response_json(s))
        end
    end
    @test length(concurrent_results) == N_CONCURRENT
    for r in concurrent_results
        @test r.status == 200
        @test r.json["ok"] == true
        @test r.json["port"] == 8081
        @test r.json["loaded_tools_count"] >= 15
    end
    println("  ✓ 50 concurrent /control/state requests completed cleanly without deadlock or race condition.")
end

@testset "Adversarial 2: /control/tools Schema & Dynamic Tool Lifecycle" begin
    s_tools = _mock_request("GET", "/control/tools")
    @test s_tools.status == 200
    @test _get_header(s_tools, "Access-Control-Allow-Origin") == "*"

    data = _response_json(s_tools)
    @test data["ok"] == true
    @test data["total_tools"] >= 15
    @test data["builtin_count"] >= 15
    @test data["dynamic_count"] >= 0
    @test data["total_tools"] == data["builtin_count"] + data["dynamic_count"]

    tools = data["tools"]
    @test tools isa AbstractVector
    @test length(tools) == data["total_tools"]

    # Parameter schema validation for every enumerated tool
    required_builtins = ["read_file", "write_file", "run_command", "execute_code", "remember", "recall", "browse_url", "forge_new_tool"]
    found_names = String[]

    for tool in tools
        tname = tool["name"]
        push!(found_names, tname)
        @test !isempty(tname)
        @test tool["category"] in ["builtin", "dynamic"]
        @test tool["is_dynamic"] isa Bool
        @test haskey(tool, "description")
        @test haskey(tool, "call_count")
        @test haskey(tool, "last_used")
        @test haskey(tool, "parameters")

        params = tool["parameters"]
        @test params isa AbstractDict
        @test lowercase(get(params, "type", "")) == "object"
        @test haskey(params, "properties")
        @test params["properties"] isa AbstractDict
    end

    for req_tool in required_builtins
        @test req_tool in found_names
    end

    # Test Dynamic Tool Lifecycle: Inject a dynamic tool schema into DYNAMIC_SCHEMA
    mock_dyn_name = "test_stress_calc_$(UUIDs.uuid4())"
    mock_dyn_schema = Dict{String, Any}(
        "name" => mock_dyn_name,
        "description" => "Dynamic tool for stress testing",
        "parameters" => Dict{String, Any}(
            "type" => "object",
            "properties" => Dict{String, Any}(
                "value" => Dict{String, Any}("type" => "number", "description" => "Input number")
            ),
            "required" => ["value"]
        )
    )

    initial_dyn_count = data["dynamic_count"]
    push!(BYTE.DYNAMIC_SCHEMA, mock_dyn_schema)

    try
        s_dyn = _mock_request("GET", "/control/tools")
        @test s_dyn.status == 200
        d_dyn = _response_json(s_dyn)
        @test d_dyn["dynamic_count"] == initial_dyn_count + 1
        
        dyn_matches = filter(t -> t["name"] == mock_dyn_name, d_dyn["tools"])
        @test length(dyn_matches) == 1
        d_tool = dyn_matches[1]
        @test d_tool["category"] == "dynamic"
        @test d_tool["is_dynamic"] == true
        @test d_tool["description"] == "Dynamic tool for stress testing"
        @test d_tool["parameters"]["type"] == "object"
        @test haskey(d_tool["parameters"]["properties"], "value")
    finally
        filter!(x -> get(x, "name", "") != mock_dyn_name, BYTE.DYNAMIC_SCHEMA)
    end

    # Verify clean teardown
    s_clean = _mock_request("GET", "/control/tools")
    d_clean = _response_json(s_clean)
    @test d_clean["dynamic_count"] == initial_dyn_count
    println("  ✓ Dynamic tool schema injection and lifecycle enumeration verified.")
end

@testset "Adversarial 3: /control/dispatch Payload Validation & Edge Cases" begin
    # 1. Empty body
    s1 = _mock_request("POST", "/control/dispatch", ""; engine=engine)
    @test s1.status == 400
    d1 = _response_json(s1)
    @test d1["ok"] == false
    @test occursin("valid JSON", d1["error"])

    # 2. Whitespace-only task
    s2 = _mock_request("POST", "/control/dispatch", JSON.json(Dict("task" => "   \n\t  ")); engine=engine)
    @test s2.status == 400
    d2 = _response_json(s2)
    @test d2["ok"] == false
    @test occursin("cannot be empty", d2["error"])

    # 3. Missing task key
    s3 = _mock_request("POST", "/control/dispatch", JSON.json(Dict("agent" => "SparkByte")); engine=engine)
    @test s3.status == 400
    d3 = _response_json(s3)
    @test d3["ok"] == false

    # 4. Malformed JSON
    s4 = _mock_request("POST", "/control/dispatch", "{not valid json: true"; engine=engine)
    @test s4.status == 400
    d4 = _response_json(s4)
    @test d4["ok"] == false

    # 5. Non-object JSON is rejected before task execution.
    s5 = _mock_request("POST", "/control/dispatch",
        JSON.json(["task", "read_file Project.toml"]); engine=engine)
    @test s5.status == 400
    @test _response_json(s5)["ok"] == false

    # 6. Failed local tool dispatch must not claim completion
    s_tool = _mock_request("POST", "/control/dispatch", JSON.json(Dict(
        "task" => "read_file Project.toml",
        "agent" => "SparkByte",
        "timeout_s" => 30
    )); engine=engine)
    @test s_tool.status == 500
    d_tool = _response_json(s_tool)
    @test d_tool["ok"] == false
    @test d_tool["status"] == "failed"
    @test d_tool["agent"] == "SparkByte"
    @test haskey(d_tool, "task_id")
    @test length(d_tool["tools_called"]) >= 1
    @test d_tool["tools_called"][1]["tool"] == "read_file"
    @test d_tool["tools_called"][1]["status"] == "error"

    # 6b. Valid Local Tool Dispatch with clean output: get_os_info
    s_os = _mock_request("POST", "/control/dispatch", JSON.json(Dict(
        "task" => "get_os_info",
        "agent" => "SparkByte",
        "timeout_s" => 30
    )); engine=engine)
    @test s_os.status == 200
    d_os = _response_json(s_os)
    @test d_os["ok"] == true
    @test d_os["status"] == "completed"
    @test length(d_os["tools_called"]) >= 1
    @test d_os["tools_called"][1]["tool"] == "get_os_info"
    @test d_os["tools_called"][1]["status"] == "success"
    @test haskey(d_os["tools_called"][1]["result"], "os")

    # 7. Valid General Dispatch with NoopBackend
    s_gen = _mock_request("POST", "/control/dispatch", JSON.json(Dict(
        "task" => "Echo stress test dispatch",
        "agent" => "SparkByte",
        "timeout_s" => 30
    )); engine=engine)
    @test s_gen.status == 200
    d_gen = _response_json(s_gen)
    @test d_gen["ok"] == true
    @test d_gen["status"] == "completed"
    @test occursin("Echo stress test dispatch", d_gen["result"])
    @test haskey(d_gen, "telemetry")
    println("  ✓ Dispatch payload validation and execution contracts verified.")
end

@testset "Adversarial 4: Concurrency & Lock Safety in Task Dispatch" begin
    # Verify initial task registry is empty
    initial_tasks_count = lock(BYTE._CONTROL_TASKS_LOCK) do
        length(BYTE._CONTROL_TASKS)
    end
    @test initial_tasks_count == 0

    # Dispatch 20 concurrent tasks
    N_TASKS = 20
    results = Vector{Any}(undef, N_TASKS)
    t_start = time()

    @sync for i in 1:N_TASKS
        @async begin
            body = JSON.json(Dict(
                "task" => "Concurrent prompt #$i echo",
                "agent" => "SparkByte",
                "timeout_s" => 30
            ))
            s = _mock_request("POST", "/control/dispatch", body; engine=engine)
            results[i] = (status=s.status, json=_response_json(s))
        end
    end

    duration = time() - t_start
    println("  ✓ $N_TASKS concurrent dispatches completed in $(round(duration, digits=3))s")

    task_ids = Set{String}()
    for (i, r) in enumerate(results)
        @test r.status == 200
        @test r.json["ok"] == true
        @test r.json["status"] == "completed"
        @test r.json["agent"] == "SparkByte"
        @test haskey(r.json, "task_id")
        tid = r.json["task_id"]
        @test !(tid in task_ids) # Ensure all task IDs are unique UUIDs
        push!(task_ids, tid)
    end
    @test length(task_ids) == N_TASKS

    # Verify task registry is cleaned up post-completion
    final_tasks_count = lock(BYTE._CONTROL_TASKS_LOCK) do
        length(BYTE._CONTROL_TASKS)
    end
    @test final_tasks_count == 0
    # Lock must not be left locked
    @test !islocked(BYTE._CONTROL_TASKS_LOCK)
    println("  ✓ Concurrency test passed: 20/20 tasks unique, completed, zero leaked locks/tasks.")
end

@testset "Adversarial 5: /control/cancel In-Flight Task Abort & Resource Cleanup" begin
    # 1. Cancellation of In-Flight Dispatch Task
    # We simulate a long running task via a custom tool or by observing cancel_ref transition
    task_id_test = string(UUIDs.uuid4())
    cancel_ref_test = Ref(false)
    runner_started = Channel{Bool}(1)
    runner_cancelled = Channel{Bool}(1)

    dummy_runner = @async begin
        put!(runner_started, true)
        # Wait up to 5 seconds for cancellation
        t0 = time()
        while time() - t0 < 5.0 && !cancel_ref_test[]
            sleep(0.01)
        end
        put!(runner_cancelled, cancel_ref_test[])
    end

    BYTE._register_control_task!(task_id_test, "CancelTargetAgent", "Long running task", cancel_ref_test, dummy_runner)

    # Verify task is registered
    is_reg = lock(BYTE._CONTROL_TASKS_LOCK) do
        haskey(BYTE._CONTROL_TASKS, task_id_test)
    end
    @test is_reg == true

    # Wait until runner task is active
    @test take!(runner_started) == true

    # Now issue /control/cancel for this specific task
    s_cancel = _mock_request("POST", "/control/cancel", JSON.json(Dict("task_id" => task_id_test)))
    @test s_cancel.status == 200
    d_cancel = _response_json(s_cancel)
    @test d_cancel["ok"] == true
    @test d_cancel["task_id"] == task_id_test
    @test d_cancel["status"] == "cancelled"
    @test task_id_test in d_cancel["cancelled_tasks"]

    # Verify runner noticed cancellation
    runner_saw_cancel = take!(runner_cancelled)
    @test runner_saw_cancel == true
    @test cancel_ref_test[] == true

    # Cleanup test task
    BYTE._unregister_control_task!(task_id_test)
    @test !haskey(BYTE._CONTROL_TASKS, task_id_test)

    # 2. Cancel All In-Flight Tasks ("all")
    task_ids_bulk = [string(UUIDs.uuid4()) for _ in 1:5]
    cancel_refs_bulk = [Ref(false) for _ in 1:5]
    runners_bulk = Task[]

    for (tid, cref) in zip(task_ids_bulk, cancel_refs_bulk)
        t = @async begin
            t0 = time()
            while time() - t0 < 5.0 && !cref[]
                sleep(0.01)
            end
        end
        push!(runners_bulk, t)
        BYTE._register_control_task!(tid, "BulkAgent", "Bulk task $tid", cref, t)
    end

    # Confirm all 5 are in registry
    registered_bulk = lock(BYTE._CONTROL_TASKS_LOCK) do
        all(tid -> haskey(BYTE._CONTROL_TASKS, tid), task_ids_bulk)
    end
    @test registered_bulk == true

    # Issue cancel "all"
    s_cancel_all = _mock_request("POST", "/control/cancel", JSON.json(Dict("task_id" => "all")))
    @test s_cancel_all.status == 200
    d_cancel_all = _response_json(s_cancel_all)
    @test d_cancel_all["ok"] == true
    @test d_cancel_all["status"] == "cancelled"
    for tid in task_ids_bulk
        @test tid in d_cancel_all["cancelled_tasks"]
    end
    for cref in cancel_refs_bulk
        @test cref[] == true
    end

    # Clean up bulk tasks
    for tid in task_ids_bulk
        BYTE._unregister_control_task!(tid)
    end
    @test !islocked(BYTE._CONTROL_TASKS_LOCK)

    # 3. Cancel Non-existent Task (Idempotency & Resiliency)
    s_ghost = _mock_request("POST", "/control/cancel", JSON.json(Dict("task_id" => "non-existent-uuid-999")))
    @test s_ghost.status == 200
    d_ghost = _response_json(s_ghost)
    @test d_ghost["ok"] == true
    @test d_ghost["status"] == "cancelled"
    @test isempty(d_ghost["cancelled_tasks"])

    println("  ✓ In-flight cancellation, bulk abort, and lock safety verified.")
end

@testset "Adversarial 6: CORS Preflight & Cross-Origin Security" begin
    # 1. OPTIONS Preflight on all /control/* routes
    test_routes = ["/control/state", "/control/tools", "/control/dispatch", "/control/cancel", "/api/models", "/api/config"]
    origin_header = "https://external-dev-studio.local:3000"

    for route in test_routes
        s_opt = _mock_request("OPTIONS", route, "", [
            "Origin" => origin_header,
            "Access-Control-Request-Method" => "POST",
            "Access-Control-Request-Headers" => "Content-Type, Authorization"
        ])

        @test s_opt.status == 204
        @test _get_header(s_opt, "Access-Control-Allow-Origin") == "*"
        allow_methods = _get_header(s_opt, "Access-Control-Allow-Methods")
        @test occursin("OPTIONS", allow_methods)
        @test occursin("GET", allow_methods)
        @test occursin("POST", allow_methods)
        
        allow_headers = _get_header(s_opt, "Access-Control-Allow-Headers")
        @test occursin("Content-Type", allow_headers)
        @test occursin("Authorization", allow_headers)
        @test _get_header(s_opt, "Access-Control-Max-Age") == "86400"
    end

    # 2. CORS headers on GET /control/state response
    s_get = _mock_request("GET", "/control/state", "", ["Origin" => origin_header]; engine=engine)
    @test s_get.status == 200
    @test _get_header(s_get, "Access-Control-Allow-Origin") == "*"

    # 3. CORS headers on POST /control/dispatch response
    s_post = _mock_request("POST", "/control/dispatch", JSON.json(Dict("task" => "CORS test")), ["Origin" => origin_header]; engine=engine)
    @test s_post.status == 200
    @test _get_header(s_post, "Access-Control-Allow-Origin") == "*"

    # 4. CORS headers on error response (e.g. 400 Bad Request)
    s_err = _mock_request("POST", "/control/dispatch", JSON.json(Dict("task" => "")), ["Origin" => origin_header]; engine=engine)
    @test s_err.status == 400
    @test _get_header(s_err, "Access-Control-Allow-Origin") == "*"

    println("  ✓ CORS preflight and response origin headers verified across all routes.")
end

@testset "Adversarial 7: Live TCP Socket Over-the-Wire Verification" begin
    port = 18081
    host = "127.0.0.1"
    
    server = HTTP.serve!(host, port; stream=true) do stream
        req = stream.message
        if req.method == "OPTIONS" && (startswith(req.target, "/api/") || startswith(req.target, "/control/"))
            BYTE._http_cors_preflight(stream)
        elseif req.method == "GET" && (req.target == "/control/state" || startswith(req.target, "/control/state?"))
            BYTE._handle_control_state_request(stream, engine, host, port, BYTE._BOOT_TIME)
        elseif req.method == "GET" && (req.target == "/control/tools" || startswith(req.target, "/control/tools?"))
            BYTE._handle_control_tools_request(stream)
        elseif req.method == "POST" && (req.target == "/control/dispatch" || startswith(req.target, "/control/dispatch?"))
            BYTE._handle_control_dispatch_request(stream, engine)
        elseif req.method == "POST" && (req.target == "/control/cancel" || startswith(req.target, "/control/cancel?"))
            BYTE._handle_control_cancel_request(stream)
        else
            HTTP.setstatus(stream, 404)
        end
    end

    try
        sleep(0.5) # Allow listener to bind
        base_url = "http://$host:$port"

        # 1. OPTIONS over live socket
        r_opt = HTTP.request("OPTIONS", "$base_url/control/state", [
            "Origin" => "http://test-client.local",
            "Access-Control-Request-Method" => "GET"
        ])
        @test r_opt.status == 204
        headers_dict = Dict(lowercase(k) => v for (k, v) in r_opt.headers)
        @test headers_dict["access-control-allow-origin"] == "*"
        @test occursin("OPTIONS", headers_dict["access-control-allow-methods"])

        # 2. GET /control/state over live socket
        r_state = HTTP.request("GET", "$base_url/control/state", ["Origin" => "http://test-client.local"])
        @test r_state.status == 200
        d_state = JSON.parse(String(r_state.body))
        @test d_state["ok"] == true
        @test d_state["port"] == port
        @test d_state["service"] == "sparkbyte-omni"

        # 3. GET /control/tools over live socket
        r_tools = HTTP.request("GET", "$base_url/control/tools")
        @test r_tools.status == 200
        d_tools = JSON.parse(String(r_tools.body))
        @test d_tools["ok"] == true
        @test d_tools["total_tools"] >= 15

        # 4. POST /control/dispatch over live socket
        r_disp = HTTP.request("POST", "$base_url/control/dispatch", 
            ["Content-Type" => "application/json"],
            JSON.json(Dict("task" => "Live socket dispatch test", "agent" => "SparkByte"))
        )
        @test r_disp.status == 200
        d_disp = JSON.parse(String(r_disp.body))
        @test d_disp["ok"] == true
        @test d_disp["status"] == "completed"
        @test d_disp["agent"] == "SparkByte"

        # 5. POST /control/cancel over live socket
        r_cancel = HTTP.request("POST", "$base_url/control/cancel",
            ["Content-Type" => "application/json"],
            JSON.json(Dict("task_id" => "all"))
        )
        @test r_cancel.status == 200
        d_cancel = JSON.parse(String(r_cancel.body))
        @test d_cancel["ok"] == true
        @test d_cancel["status"] == "cancelled"

        println("  ✓ Live TCP socket HTTP client communication verified across all endpoints.")
    finally
        close(server)
    end
end

println("====================================================================")
println("  All Adversarial Stress & Concurrency Tests Passed!")
println("====================================================================")
