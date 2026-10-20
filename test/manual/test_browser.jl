using Pkg
Pkg.activate(".")
include("src/JLEngine.jl")
include("BYTE/src/BYTE.jl")

# Initialize browser context
BYTE._init_browser_context!()

# Test browse_url tool
result = BYTE.tool_browse_url(Dict("url" => "https://httpbin.org/html"))
println("Browser test result:")
println(result)