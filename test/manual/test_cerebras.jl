using Pkg
Pkg.activate(".")
include("src/JLEngine/Config.jl")
include("src/JLEngine/Backends.jl")

using JSON3

# Manually set CEREBRAS_API_KEY from .env for the test if not set
if isempty(get(ENV, "CEREBRAS_API_KEY", ""))
    println("Loading .env for test...")
    if isfile(".env")
        for line in eachline(".env")
            if startswith(line, "CEREBRAS_API_KEY=")
                ENV["CEREBRAS_API_KEY"] = split(line, "=")[2]
                break
            end
        end
    end
end

println("Testing cerebras backend (gpt-oss-120b)...")
backend = get_backend("cerebras"; overrides=Dict("model" => "gpt-oss-120b"))
res, info = generate(backend, [Dict("role" => "user", "content" => "ping")])

println("Result: ", res)
println("Info: ", info)
