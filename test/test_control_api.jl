using Test
using HTTP
using JSON
using SQLite
using JLEngine
using UUIDs

if !isdefined(Main, :BYTE)
    @eval Main const BYTE = JLEngine.BYTE
end

# ── Mock HTTP Stream for In-Process Handler Testing ───────────────────────────
# Use the same agent-data root as the application, so identity checks are real.
_control_test_engine() = JLEngine.JLEngineCore(JLEngine.EngineConfig(
    root_dir=normpath(joinpath(@__DIR__, "..", "data"))))

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
    return JSON.parse(String(take!(s.body_out)))
end

function _get_header(s::MockHttpStream, name::String)
    for (k, v) in s.headers
        lowercase(k) == lowercase(name) && return v
    end
    return nothing
end

@testset "Control API: CORS Preflight & Headers" begin
    stream = MockHttpStream()
    BYTE._http_cors_preflight(stream)

    @test stream.status == 204
    @test stream.started == true
    @test _get_header(stream, "Access-Control-Allow-Origin") == "*"
    @test occursin("OPTIONS", _get_header(stream, "Access-Control-Allow-Methods"))
    @test occursin("Content-Type", _get_header(stream, "Access-Control-Allow-Headers"))
    @test _get_header(stream, "Access-Control-Max-Age") == "86400"
end

@testset "Control API: GET /control/state" begin
    engine = _control_test_engine()
    stream = MockHttpStream()
    boot_t = time() - 100.0

    BYTE._handle_control_state_request(stream, engine, "127.0.0.1", 8081, boot_t)

    @test stream.status == 200
    @test _get_header(stream, "Access-Control-Allow-Origin") == "*"
    @test _get_header(stream, "Content-Type") == "application/json; charset=utf-8"

    data = _response_json(stream)
    @test data["ok"] == true
    @test data["service"] == "sparkbyte-omni"
    @test data["port"] == 8081
    @test haskey(data, "active_provider")
    @test haskey(data, "current_model")
    @test data["loaded_tools_count"] >= 15
    @test data["memory_items_count"] >= 0
    @test data["connected_clients_count"] >= 0
    @test data["uptime"] >= 100.0
    @test data["active_agent"] == "SparkByte"
    @test haskey(data, "tokens")
    @test haskey(data, "timestamp")
end

@testset "Control API: GET /control/tools" begin
    stream = MockHttpStream()
    BYTE._handle_control_tools_request(stream)

    @test stream.status == 200
    @test _get_header(stream, "Access-Control-Allow-Origin") == "*"

    data = _response_json(stream)
    @test data["ok"] == true
    @test data["total_tools"] >= 15
    @test data["builtin_count"] >= 15
    @test data["dynamic_count"] >= 0

    tools = data["tools"]
    @test tools isa AbstractVector
    tool_names = [t["name"] for t in tools]

    @test "read_file" in tool_names
    @test "write_file" in tool_names
    @test "run_command" in tool_names
    @test "forge_new_tool" in tool_names

    rf = filter(t -> t["name"] == "read_file", tools)[1]
    @test rf["category"] == "builtin"
    @test rf["is_dynamic"] == false
    @test haskey(rf, "description")
    @test haskey(rf, "parameters")
end

@testset "Control API: POST /control/dispatch" begin
    engine = _control_test_engine()

    # 1. Validation failure: empty task
    stream_bad = MockHttpStream(JSON.json(Dict("task" => "")))
    BYTE._handle_control_dispatch_request(stream_bad, engine)
    @test stream_bad.status == 400
    err_data = _response_json(stream_bad)
    @test err_data["ok"] == false
    @test occursin("cannot be empty", err_data["error"])

    # 2. Valid local dispatch: direct local tool invocation
    body_tool = JSON.json(Dict(
        "task" => "get_os_info",
        "agent" => "SparkByte",
        "timeout_s" => 30
    ))
    stream_tool = MockHttpStream(body_tool)
    BYTE._handle_control_dispatch_request(stream_tool, engine)
    @test stream_tool.status == 200
    tool_data = _response_json(stream_tool)
    @test tool_data["ok"] == true
    @test tool_data["status"] == "completed"
    @test haskey(tool_data, "task_id")
    @test length(tool_data["tools_called"]) >= 1
    @test tool_data["tools_called"][1]["tool"] == "get_os_info"

    # 3. Valid local dispatch: general prompt with NoopBackend
    # Register NoopBackend as active to verify backend integration
    JLEngine.set_brain_backend_id!("noop-stub")

    body_gen = JSON.json(Dict(
        "task" => "Summarize engine status",
        "agent" => "SparkByte",
        "timeout_s" => 30
    ))
    stream_gen = MockHttpStream(body_gen)
    BYTE._handle_control_dispatch_request(stream_gen, engine)
    @test stream_gen.status == 200
    gen_data = _response_json(stream_gen)
    @test gen_data["ok"] == true
    @test gen_data["status"] == "completed"
    @test occursin("Summarize engine status", gen_data["result"])
end

@testset "Control API: POST /control/cancel" begin
    # 1. Cancel specific task
    cancel_body = JSON.json(Dict("task_id" => "test-task-123"))
    stream = MockHttpStream(cancel_body)
    BYTE._handle_control_cancel_request(stream)

    @test stream.status == 200
    data = _response_json(stream)
    @test data["ok"] == true
    @test data["task_id"] == "test-task-123"
    @test data["status"] == "cancelled"

    # 2. Cancel all tasks
    cancel_all_body = JSON.json(Dict("task_id" => "all"))
    stream_all = MockHttpStream(cancel_all_body)
    BYTE._handle_control_cancel_request(stream_all)

    @test stream_all.status == 200
    all_data = _response_json(stream_all)
    @test all_data["ok"] == true
    @test all_data["status"] == "cancelled"
end

@testset "Control dispatch reports local tool failures" begin
    engine = _control_test_engine()
    stream = MockHttpStream(JSON.json(Dict("task" => "read_file", "agent" => "SparkByte")))
    BYTE._handle_control_dispatch_request(stream, engine)
    data = _response_json(stream)
    @test stream.status == 500
    @test data["ok"] == false
    @test data["status"] == "failed"
    @test haskey(data, "error")
    @test !occursin("successfully", get(data, "result", ""))
end
