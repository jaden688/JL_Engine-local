using JSON
include("src/JLEngine.jl")
using .JLEngine

engine = JLEngineCore()
println("MPF Profiles in Engine:")
for k in keys(engine.mpf_profiles)
    println(" - ", k)
end
