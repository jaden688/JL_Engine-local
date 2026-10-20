using Test

include(joinpath(@__DIR__, "..", "BYTE", "src", "Schema.jl"))
include(joinpath(@__DIR__, "..", "BYTE", "src", "Tools.jl"))

@testset "execute_code language handling" begin
    inferred = tool_execute_code(Dict(
        "code" => "import os\nprint('python:' + os.name)"
    ))
    @test !haskey(inferred, "error")
    @test inferred["language"] == "python"
    @test occursin("python:", inferred["stdout"])

    explicit = tool_execute_code(Dict(
        "language" => "python",
        "code" => "print('explicit-python')"
    ))
    @test !haskey(explicit, "error")
    @test explicit["language"] == "python"
    @test occursin("explicit-python", explicit["stdout"])

    rejected = tool_execute_code(Dict(
        "language" => "ruby",
        "code" => "puts 'nope'"
    ))
    @test occursin("Unsupported language", rejected["error"])
end

include("test_backends.jl")
include("test_config.jl")
include("test_a2a_discovery.jl")
include("test_a2a_billing.jl")
include("test_a2a_protocol.jl")
include("test_control_api.jl")

include("test_agent_registry.jl")
include("test_state_directory.jl")

include("test_control_dispatch_validation.jl")

include("test_history_health_regressions.jl")

include("test_startup_ports.jl")
