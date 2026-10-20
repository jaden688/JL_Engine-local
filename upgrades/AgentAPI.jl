# upgrades/AgentAPI.jl
# The Living Endpoint Architecture for Fat Agents

using HTTP
using JSON3
using Sockets

"""
    AgentAPIConfig
Defines the port and routes for a specific Fat Agent.
"""
struct AgentAPIConfig
    port::Int
    host::String
    allowed_ips::Vector{String}
end

"""
    start_agent_api!(engine::JLEngineCore, agent_name::String, config::AgentAPIConfig)

Spins up an asynchronous HTTP server for a specific agent. 
Incoming requests are routed directly into the engine's `run_turn!` loop, 
forcing the request through the agent's Behavioral Grid and Memory.
"""
function start_agent_api!(engine, agent_name::String, config::AgentAPIConfig)
    println("[AgentAPI] Booting living endpoint for $(agent_name) on $(config.host):$(config.port)...")
    
    # Run the server asynchronously so it doesn't block the main engine loop
    errormonitor(@async begin
        try
            HTTP.serve(config.host, config.port) do req::HTTP.Request
            # 1. Basic Security Check
            client_ip = string(req.context[:ip])
            if !isempty(config.allowed_ips) && !(client_ip in config.allowed_ips)
                return HTTP.Response(403, "Forbidden: Agent $(agent_name) does not talk to strangers.")
            end

            # 2. Parse the incoming payload
            local payload
            try
                payload = JSON3.read(String(req.body))
            catch
                return HTTP.Response(400, "Bad Request: I only speak JSON, honey.")
            end

            user_message = get(payload, "message", "")
            if isempty(user_message)
                return HTTP.Response(400, "Bad Request: You didn't say anything.")
            end

            # 3. The Magic: Route the request through the JL Engine
            # We temporarily set the engine to this specific agent, run the turn, and capture the output.
            println("[AgentAPI] $(agent_name) received request: $(first(user_message, 50))...")
            
            # Run the turn (This triggers Signals, Behavior, Drift, and the LLM)
            result = process_turn(engine, user_message; operator_name=agent_name)
            
            # 4. Format the response
            response_data = Dict(
                "agent" => agent_name,
                "reply" => result["reply"],
                "emotional_state" => result["telemetry"]["behavior_state"]["name"],
                "drift_pressure" => result["telemetry"]["drift"]["pressure"]
            )

            return HTTP.Response(200, ["Content-Type" => "application/json"], JSON3.write(response_data))
        end
        catch e
            @warn "[AgentAPI] $agent_name server crashed" exception=(e, catch_backtrace())
        end
    end)
    return true
end

# --- How to wire this into the Engine ---
# In `App.jl` or `Core.jl`, after loading the MPF profiles:
# 
# for (name, profile) in engine.mpf_profiles
#     api_config = get(profile.raw_data, "hosted_api", nothing)
#     if api_config !== nothing
#         config = AgentAPIConfig(
#             get(api_config, "port", 8080),
#             get(api_config, "host", "127.0.0.1"),
#             get(api_config, "allowed_ips", ["127.0.0.1"])
#         )
#         start_agent_api!(engine, name, config)
#     end
# end
