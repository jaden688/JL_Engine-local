# test/test_wave0_challenge.jl
# Challenger 1 Adversarial Verification Harness for Wave 0 Baseline

using Test
using Dates
using Sockets

println("=================================================================")
println("  CHALLENGER 1: Wave 0 Adversarial Test Harness Starting...")
println("=================================================================")

# -----------------------------------------------------------------------------
# TEST SUITE 1: Port 8081 & Environment Configuration Tests
# -----------------------------------------------------------------------------
@testset "Suite 1: Port Resolution & Default Constants" begin
    # 1.1 App.jl default port constant
    include(joinpath(@__DIR__, "..", "src", "App.jl"))
    @test DEFAULT_PORT == 8081
    @test DEFAULT_HOST == "127.0.0.1"

    # 1.2 _env_port resolution logic
    withenv("SPARKBYTE_PORT" => nothing) do
        @test _env_port() == 8081
    end

    withenv("SPARKBYTE_PORT" => "9090") do
        @test _env_port() == 9090
    end

    withenv("SPARKBYTE_PORT" => "invalid_port") do
        @test _env_port() == 8081  # Fallback to DEFAULT_PORT
    end

    withenv("SPARKBYTE_PORT" => "") do
        @test _env_port() == 8081  # Fallback to DEFAULT_PORT
    end

    # 1.3 BYTE.jl serve default argument
    # Method inspection of BYTE.serve
    methods_serve = methods(BYTE.serve)
    @test !isempty(methods_serve)
    
    # Check default kwargs of BYTE.serve by inspecting definition or calling with dummy
    # In BYTE/src/BYTE.jl line 1778: function serve(engine; host::String="127.0.0.1", port::Int=8081)
    # Check that BYTE.serve default port is 8081
    byte_src = read(joinpath(@__DIR__, "..", "BYTE", "src", "BYTE.jl"), String)
    @test occursin(r"function\s+serve\(engine;\s*host::String\s*=\s*\"127\.0\.0\.1\",\s*port::Int\s*=\s*8081\)", byte_src)

    # 1.4 Launch_SparkByte.bat content audit
    launch_bat = read(joinpath(@__DIR__, "..", "Launch_SparkByte.bat"), String)
    @test occursin("set \"SPARKBYTE_PORT=8081\"", launch_bat)
    @test occursin("set \"SPARKBYTE_UI=http://127.0.0.1:8081/\"", launch_bat)
    @test occursin("Write-Error 'JL_OS did not become healthy on port 8081'", launch_bat)
    @test !occursin("8008", launch_bat)

    # 1.5 .env.example content audit
    env_example = read(joinpath(@__DIR__, "..", ".env.example"), String)
    @test occursin("SPARKBYTE_PORT=8081", env_example)
    @test occursin("SPARKBYTE_PUBLIC_PORT=8081", env_example)
    @test !occursin("8008", env_example)

    # 1.6 All batch files in root repo must not bind to 8008
    for bat in ["Launch_SparkByte.bat", "start.bat", "install.bat", "crush.bat", "run_demo.bat"]
        path = joinpath(@__DIR__, "..", bat)
        if isfile(path)
            content = read(path, String)
            @test !occursin("8008", content)
        end
    end
end

# -----------------------------------------------------------------------------
# TEST SUITE 2: Early .env Loader Behavior
# -----------------------------------------------------------------------------
@testset "Suite 2: Early .env Loader Logic & Timing" begin
    # Test the parsing logic extracted from sparkbyte.jl line-by-line
    function parse_env_lines(lines::Vector{String})
        env_dict = Dict{String, String}()
        for raw_line in lines
            line = strip(raw_line)
            (isempty(line) || startswith(line, "#")) && continue
            m = match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            m !== nothing && (env_dict[m[1]] = strip(m[2], ['"', '\'']))
        end
        return env_dict
    end

    # Test cases:
    parsed = parse_env_lines([
        "# This is a comment",
        "",
        "   ",
        "SPARKBYTE_PORT=8085",
        "SPARKBYTE_HOST=\"127.0.0.1\"",
        "SINGLE_QUOTES='hello_world'",
        "WITH_EQUALS=https://example.com/api?a=1&b=2",
        "EMPTY_VAL=",
        "SPACED_KEY = invalid", # Key with space should not match [A-Za-z_][A-Za-z0-9_]*
        "# COMMENTED_VAR=123",
        "TRAILING_SPACES=test_val   "
    ])

    @test parsed["SPARKBYTE_PORT"] == "8085"
    @test parsed["SPARKBYTE_HOST"] == "127.0.0.1"
    @test parsed["SINGLE_QUOTES"] == "hello_world"
    @test parsed["WITH_EQUALS"] == "https://example.com/api?a=1&b=2"
    @test parsed["EMPTY_VAL"] == ""
    @test !haskey(parsed, "SPACED_KEY")
    @test !haskey(parsed, "COMMENTED_VAR")
    @test parsed["TRAILING_SPACES"] == "test_val"

    # Test live execution of early loader via sparkbyte.jl simulated boot
    # Check that in sparkbyte.jl, .env is loaded BEFORE run_health_check()
    sparkbyte_src = read(joinpath(@__DIR__, "..", "sparkbyte.jl"), String)
    env_load_idx = findfirst("# ── Early .env loading", sparkbyte_src)
    health_check_idx = findfirst("run_health_check()", sparkbyte_src)
    pkg_instantiate_idx = findfirst("Pkg.instantiate()", sparkbyte_src)

    @test env_load_idx !== nothing
    @test health_check_idx !== nothing
    @test pkg_instantiate_idx !== nothing
    # Verify order: early .env loading precedes Pkg.instantiate and health check
    @test first(env_load_idx) < first(pkg_instantiate_idx)
    @test first(pkg_instantiate_idx) < first(health_check_idx)
end

# -----------------------------------------------------------------------------
# TEST SUITE 3: health_check.jl Scanner Robustness & Edge Cases
# -----------------------------------------------------------------------------
@testset "Suite 3: health_check.jl Scanner Verification" begin
    include(joinpath(@__DIR__, "..", "health_check.jl"))

    # 3.1 Real codebase health check must pass with 0 errors, 0 warnings
    res = run_health_check(verbose=false)
    @test res.errors == 0
    @test res.warnings == 0

    # 3.2 Synthetic edge cases on _scan_file
    mktempdir() do tmpdir
        # Case A: @async with inline comments — should NOT be treated as @async
        f_comment_async = joinpath(tmpdir, "comment_async.jl")
        write(f_comment_async, """
        # @async with catch inside a comment
        # catch without logging in a comment
        function normal_func()
            return 42
        end
        """)
        issues = _scan_file(f_comment_async)
        @test isempty(issues)

        # Case B: @async on a line with trailing comment
        f_trailing_async = joinpath(tmpdir, "trailing_async.jl")
        write(f_trailing_async, """
        function launch_bg()
            @async begin # background task
                try
                    sleep(1)
                catch e
                    @warn "Task failed" exception=e
                end
            end
        end
        """)
        issues = _scan_file(f_trailing_async)
        @test isempty(issues)

        # Case C: @async with silent catch (MUST flag warning)
        f_silent_async = joinpath(tmpdir, "silent_async.jl")
        write(f_silent_async, """
        function bad_bg()
            @async begin
                try
                    sleep(1)
                catch e
                    # completely silent catch
                end
            end
        end
        """)
        issues = _scan_file(f_silent_async)
        @test any(iss.code == :async_silent for iss in issues)

        # Case D: Single line silent catch (MUST flag error)
        f_silent_catch = joinpath(tmpdir, "silent_catch.jl")
        write(f_silent_catch, """
        function bad_catch()
            try foo() catch; end
        end
        """)
        issues = _scan_file(f_silent_catch)
        @test any(iss.code == :silent_catch && iss.severity == :error for iss in issues)

        # Case E: Single line catch in a comment (should NOT flag error)
        f_comment_catch = joinpath(tmpdir, "comment_catch.jl")
        write(f_comment_catch, """
        # try foo() catch; end
        function good_func()
            return 1
        end
        """)
        issues = _scan_file(f_comment_catch)
        @test isempty(issues)

        # Case F: TODO / FIXME markers (MUST flag warning)
        f_todo = joinpath(tmpdir, "todo.jl")
        write(f_todo, """
        # TODO: implement this later
        function pending()
            return 1
        end
        """)
        issues = _scan_file(f_todo)
        @test any(iss.code == :stub for iss in issues)

        # Case G: Return nothing with trailing comment (should NOT flag return_nothing warning)
        f_return_comment = joinpath(tmpdir, "return_comment.jl")
        write(f_return_comment, """
        function find_item()
            return nothing  # Item not found
        end
        """)
        issues = _scan_file(f_return_comment)
        @test !any(iss.code == :return_nothing for iss in issues)

        # Case H: Return nothing standalone (MUST flag return_nothing warning)
        f_return_bare = joinpath(tmpdir, "return_bare.jl")
        write(f_return_bare, """
        function stub_func()
            return nothing
        end
        """)
        issues = _scan_file(f_return_bare)
        @test any(iss.code == :return_nothing for iss in issues)
    end
end

# -----------------------------------------------------------------------------
# TEST SUITE 4: Adversarial Stress Tests & Edge Case Discovery
# -----------------------------------------------------------------------------
@testset "Suite 4: Adversarial Edge Cases & Scanner Limitations" begin
    include(joinpath(@__DIR__, "..", "health_check.jl"))

    mktempdir() do tmpdir
        # Challenge 4.1: Word "catch" in an explanatory comment inside @async
        f_comment_catch_in_async = joinpath(tmpdir, "comment_catch_async.jl")
        write(f_comment_catch_in_async, """
        function bg_poller()
            @async begin
                # We catch up with upstream queue events here
                poll_events()
            end
        end
        """)
        issues = _scan_file(f_comment_catch_in_async)
        # Empirical test: Does this false-positive trigger :async_silent?
        has_false_positive = any(iss.code == :async_silent for iss in issues)
        println("  [Adversarial 4.1] False positive on '# catch up' in @async: ", has_false_positive)
        # Note: We observe the scanner behavior empirically
        @test has_false_positive == true  # Demonstrates heuristic limitation

        # Challenge 4.2: Clean @async followed by unrelated try-catch within 150-line window
        f_bleed = joinpath(tmpdir, "window_bleed.jl")
        write(f_bleed, """
        function clean_async()
            @async begin
                run_task()
            end
        end

        function parse_int_or_zero(s::String)
            try
                return parse(Int, s)
            catch
                return 0
            end
        end
        """)
        issues_bleed = _scan_file(f_bleed)
        has_bleed_fp = any(iss.code == :async_silent for iss in issues_bleed)
        println("  [Adversarial 4.2] False positive due to 150-line window bleeding into unrelated function: ", has_bleed_fp)
        @test has_bleed_fp == true  # Demonstrates 150-line window bleed limitation

        # Challenge 4.3: @async with @info or rethrow instead of @warn/@error/println
        f_info_async = joinpath(tmpdir, "info_async.jl")
        write(f_info_async, """
        function info_logged_async()
            @async begin
                try
                    run_service()
                catch err
                    @info "Service stopped" exception=err
                end
            end
        end
        """)
        issues_info = _scan_file(f_info_async)
        has_info_fp = any(iss.code == :async_silent for iss in issues_info)
        println("  [Adversarial 4.3] False positive on @info logging in @async catch: ", has_info_fp)
        @test has_info_fp == true  # Demonstrates @info not included in logging whitelist

        # Challenge 4.4: Early .env loader behavior on inline comments
        function parse_single_line(line::String)
            m = match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            m !== nothing ? strip(m[2], ['"', '\'']) : nothing
        end
        val = parse_single_line("SPARKBYTE_PORT=8085 # override port")
        println("  [Adversarial 4.4] Parsed value with inline comment: ", repr(val))
        @test val == "8085 # override port"
        # In App.jl, tryparse(Int, val) will be nothing!
        @test tryparse(Int, val) === nothing
    end
end

println("=================================================================")
println("  ALL CHALLENGER TEST SUITES EXECUTED.")
println("=================================================================")

