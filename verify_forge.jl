state_dir = strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))
tools_path = isempty(state_dir) ? "dynamic_tools.jl" : joinpath(state_dir, "dynamic_tools.jl")
include(tools_path)

println("--- Simulation: Testing Forged Tool 'read_mystic_format' ---")
args = Dict("path" => "secret.mystic")
result = tool_read_mystic_format(args)

if result["status"] == "success"
    println("DECODED MESSAGE: ", result["decoded"])
    println("SUCCESS: Tool successfully encountered and solved a new format.")
else
    println("FAILED: ", result["message"])
end
