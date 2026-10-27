using Test
using JLEngine

@testset "browse_url is isolated from Julia async tasks" begin
    previous = JLEngine.BYTE._state[:browser_context]
    JLEngine.BYTE._state[:browser_context] = nothing
    tmp = tempname() * ".html"
    write(tmp, "<html><body>isolated-browser-ok</body></html>")
    try
        result = JLEngine.BYTE.tool_browse_url(Dict("url" => "file://" * tmp))
        @test !haskey(result, "error")
        @test get(result, "content", "") == "isolated-browser-ok"
    finally
        JLEngine.BYTE._state[:browser_context] = previous
        isfile(tmp) && rm(tmp; force=true)
    end
end
