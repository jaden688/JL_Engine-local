using Test
using JLEngine
using PythonCall

@testset "Browser failures release pages and allow another request" begin
    stack = JLEngine._start_browser_context()
    @test stack.browser_context !== nothing
    JLEngine.BYTE._state[:browser_context] = stack.browser_context
    try
        for _ in 1:3
            result = JLEngine.BYTE.tool_browse_url(Dict("url" => "http://127.0.0.1:1/"))
            @test haskey(result, "error")
            @test pylen(stack.browser_context.pages) == 0
        end
        result = JLEngine.BYTE.tool_browse_url(Dict("url" => "data:text/html,<body>browser-recovered</body>"))
        @test get(result, "content", "") == "browser-recovered"
        @test pylen(stack.browser_context.pages) == 0
        result = JLEngine.BYTE.tool_playwright_interact(Dict("url" => "http://127.0.0.1:1/"))
        @test haskey(result, "error")
        @test pylen(stack.browser_context.pages) == 0
    finally
        JLEngine.BYTE._state[:browser_context] = nothing
        stack.browser.close()
        stack.pw_instance.stop()
    end
end

@testset "Browser cleanup closes context before driver" begin
    stack = JLEngine._start_browser_context()
    @test isdefined(JLEngine, :_close_browser_stack)
    if isdefined(JLEngine, :_close_browser_stack)
        JLEngine._close_browser_stack(stack)
        @test !pyconvert(Bool, stack.browser.is_connected())
        @test_nowarn JLEngine._close_browser_stack((; pw_instance=nothing, browser=nothing, browser_context=nothing))
    else
        stack.browser.close()
        stack.pw_instance.stop()
    end
end

@testset "Failed browser launch leaves engine usable" begin
    mock = pyimport("unittest.mock")
    patch = mock.patch("playwright.sync_api._generated.BrowserType.launch",
        side_effect=pyimport("builtins").RuntimeError("intentional launch failure"))
    patch.start()
    try
        stack = nothing
        @test_logs (:warn, r"Browser stack unavailable") begin
            stack = JLEngine._start_browser_context()
        end
        @test stack.pw_instance === nothing
        @test stack.browser === nothing
        @test stack.browser_context === nothing
        JLEngine.BYTE._state[:browser_context] = nothing
        @test haskey(JLEngine.BYTE.tool_browse_url(Dict("url" => "about:blank")), "error")
    finally
        patch.stop()
    end
end
