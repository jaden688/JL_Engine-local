# upgrades/AgentAPI_Integration.jl
# This script patches the engine boot sequence to enable AgentAPI.jl

using JSON3

function patch_engine_boot!(engine_root::String)
    app_jl_path = joinpath(engine_root, "src", "App.jl")
    content = read(app_jl_path, String)
    
    # Check if already patched
    if occursin("AgentAPI", content)
        println("[AgentAPI] Already patched.")
        return
    end

    # Patching logic: Inject the API boot sequence after MPF registry load
    patch = """
    # --- AgentAPI Integration ---
    include(joinpath(engine_root, "upgrades", "AgentAPI.jl"))
    for (name, profile) in engine.mpf_profiles
        agent_data = load_operator_file(joinpath(engine_root, "data", "agents", profile.operator_file))
        api_config = get(agent_data, "hosted_api", nothing)
        if api_config !== nothing
            config = AgentAPIConfig(
                get(api_config, "port", 8080),
                get(api_config, "host", "127.0.0.1"),
                get(api_config, "allowed_ips", ["127.0.0.1"])
            )
            start_agent_api!(engine, name, config)
        end
    end
    # ----------------------------
    """
    
    # Find where to inject (after load_mpf_registry)
    new_content = replace(content, "engine = JLEngineCore(config)" => "engine = JLEngineCore(config)\n" * patch)
    
    write(app_jl_path, new_content)
    println("[AgentAPI] Successfully patched src/App.jl")
end
