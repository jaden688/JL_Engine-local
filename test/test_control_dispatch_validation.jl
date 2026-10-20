using Test
using JSON
using JLEngine

if !isdefined(Main, :MockHttpStream)
    include("test_control_api.jl")
end

@testset "Control dispatch rejects invalid requests before execution" begin
    cases = [
        ("array body", ["task", "get_os_info"]),
        ("null body", nothing),
        ("numeric body", 42),
        ("numeric task", Dict("task" => 42)),
        ("null task", Dict("task" => nothing)),
        ("numeric agent", Dict("task" => "get_os_info", "agent" => 42)),
        ("empty agent", Dict("task" => "get_os_info", "agent" => "")),
        ("unknown agent", Dict("task" => "get_os_info", "agent" => "OmniTester")),
        ("string timeout", Dict("task" => "get_os_info", "timeout_s" => "bad")),
        ("null timeout", Dict("task" => "get_os_info", "timeout_s" => nothing)),
        ("boolean timeout", Dict("task" => "get_os_info", "timeout_s" => true)),
        ("zero timeout", Dict("task" => "get_os_info", "timeout_s" => 0)),
        ("negative timeout", Dict("task" => "get_os_info", "timeout_s" => -1)),
    ]
    for (label, payload) in cases
        @testset "$label" begin
            engine = _control_test_engine()
            stream = MockHttpStream(JSON.json(payload))
            thrown = try
                BYTE._handle_control_dispatch_request(stream, engine)
                nothing
            catch err
                err
            end
            @test thrown === nothing
            @test stream.status == 400
            data = stream.started ? _response_json(stream) : Dict()
            @test get(data, "ok", true) === false
            @test haskey(data, "error")
            @test !haskey(data, "task_id")
            @test engine.current_agent_name == "SparkByte"
        end
    end
end

@testset "Control dispatch identifies malformed JSON" begin
    engine = _control_test_engine()
    stream = MockHttpStream("{not valid json")
    BYTE._handle_control_dispatch_request(stream, engine)
    data = _response_json(stream)
    @test stream.status == 400
    @test occursin("JSON", data["error"])
    @test !haskey(data, "task_id")
end

@testset "Control dispatch uses the current registered agent by default" begin
    engine = _control_test_engine()
    stream = MockHttpStream(JSON.json(Dict("task" => "get_os_info")))
    BYTE._handle_control_dispatch_request(stream, engine)
    data = _response_json(stream)
    @test stream.status == 200
    @test data["agent"] == "SparkByte"
    @test data["tools_called"][1]["tool"] == "get_os_info"
end
