include("data/dynamic_tools.jl")
res = tool_sassy_sys_roast(Dict())
if res["success"]
    println(res["report"])
else
    println("FAILED: ", res["error"])
end
