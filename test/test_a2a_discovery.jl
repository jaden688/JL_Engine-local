using Test
using HTTP
using JSON
using SQLite
using JLEngine

isdefined(Main, :handle_public_a2a_request) || include(joinpath(@__DIR__, "..", "a2a_server.jl"))

if !isdefined(Main, :BYTE)
    @eval Main const BYTE = JLEngine.BYTE
end

function _discover_agent(path::AbstractString)
    req = HTTP.Messages.Request(
        "GET",
        path,
        [
            "Host" => "agent.example.com",
            "X-Forwarded-Proto" => "https",
        ],
    )
    db = SQLite.DB(":memory:")
    return handle_public_a2a_request(req, db)
end

@testset "A2A discovery" begin
    expected_scheme = _a2a_auth_scheme()

    strict_resp = _discover_agent("/.well-known/agent-card.json")
    strict = JSON.parse(String(strict_resp.body))

    @test strict_resp.status == 200
    @test strict["name"] == "JL Engine"
    @test strict["provider"]["organization"] == "JL Engine"
    @test strict["provider"]["url"] == "https://agent.example.com"
    @test !haskey(strict, "url")
    @test strict["supportedInterfaces"][1]["protocolBinding"] == "JSONRPC"
    @test strict["supportedInterfaces"][1]["protocolVersion"] == A2A_PROTOCOL_VERSION
    @test strict["capabilities"]["streaming"] == true
    @test strict["capabilities"]["pushNotifications"] == true
    @test haskey(strict["capabilities"], "extendedAgentCard")
    @test any(skill -> skill["id"] == "read_file", strict["skills"])

    if _a2a_auth_required()
        @test haskey(strict, "securitySchemes")
        @test haskey(strict, "securityRequirements")
        @test haskey(strict["securitySchemes"]["bearerAuth"], "httpAuthSecurityScheme")
    else
        @test !haskey(strict, "securitySchemes")
        @test !haskey(strict, "securityRequirements")
    end

    legacy_resp = _discover_agent("/.well-known/agent.json")
    legacy = JSON.parse(String(legacy_resp.body))
    legacy_skills = legacy["skills"]

    @test legacy_resp.status == 200
    @test legacy["name"] == "JL Engine"
    @test legacy["url"] == "https://agent.example.com"
    @test legacy["provider"]["organization"] == "JL Engine"
    @test legacy["preferredTransport"] == "JSONRPC"
    @test legacy["tool_count"] == length(legacy_skills)
    @test legacy["capabilities"]["streaming"] == true
    @test legacy["capabilities"]["pushNotifications"] == true
    @test legacy["capabilities"]["stateTransitionHistory"] == true
    @test any(skill -> skill["id"] == "read_file", legacy_skills)
    @test legacy["authentication"][1]["scheme"] == expected_scheme
end
