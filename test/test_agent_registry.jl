using Test
using JLEngine

@testset "Registered agents load their complete profiles" begin
    data_root = normpath(joinpath(@__DIR__, "..", "data"))
    cfg = EngineConfig(root_dir=data_root)
    engine = JLEngineCore(cfg)
    registry = load_mpf_registry(joinpath(data_root, "agents", "Agents.mpf.json"))
    for (name, profile) in registry
        @test isfile(joinpath(data_root, "agents", profile.agent_file))
        @test set_agent!(engine, name)
        @test engine.current_agent_name == name
        @test engine.current_agent_data == load_agent_file(joinpath(data_root, "agents", profile.agent_file))
    end
    @test registry["Balthazar"].agent_file == "Balthazar.json"
    @test set_agent!(engine, "Balthazar")
    @test engine.current_agent_file == "Balthazar.json"
    @test !isfile(joinpath(data_root, "agents", "Balth.json"))
end
