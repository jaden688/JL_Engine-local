using Pkg
Pkg.activate(".")
include("BYTE/src/BYTE.jl")
import .BYTE

# The internal function name is tool_forge_new_tool
tool_code = """
function tool_chaos_lattice_sync(args::Dict{String,Any})
    return Dict("status" => "LATTICE_SYNC_OK", "msg" => "Memory silo barriers breached. Persistence achieved.")
end
"""

BYTE.tool_forge_new_tool(Dict("name" => "chaos_lattice_sync", "description" => "Forces sync.", "code" => tool_code))
println("Tool forged successfully.")
