module TestF02PortBinding

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F02: Port 8081 Alignment"

    run_test_case!(report, suite_name, "T1-F02-01", "Engine default port is 8081", () -> begin
        app_file = joinpath(repo_root, "src", "App.jl")
        assert_file_exists(app_file, "src/App.jl must exist")
        assert_file_contains(app_file, r"const\s+DEFAULT_PORT\s*=\s*8081",
                             "src/App.jl must set DEFAULT_PORT = 8081")
    end; bail=bail)

    run_test_case!(report, suite_name, "T1-F02-02", "Canonical start.jl entrypoint invokes JLEngine", () -> begin
        entry = joinpath(repo_root, "start.jl")
        assert_file_exists(entry, "start.jl must exist")
        assert_file_contains(entry, r"using\s+JLEngine", "start.jl must load JLEngine")
        assert_file_contains(entry, r"JLEngine\.julia_main\(\)", "start.jl must call the package entrypoint")
    end; bail=bail)

    run_test_case!(report, suite_name, "T1-F02-03", "Single Windows launcher uses canonical entrypoint", () -> begin
        launcher = joinpath(repo_root, "start.bat")
        assert_file_exists(launcher, "start.bat must exist")
        assert_file_contains(launcher, r"julia\s+--project=\.\s+start\.jl",
                             "start.bat must run julia --project=. start.jl")
        assert_true(!isfile(joinpath(repo_root, "Launch_SparkByte.bat")),
                    "duplicate Launch_SparkByte.bat must not exist")
    end; bail=bail)

    run_test_case!(report, suite_name, "T1-F02-04", "BYTE web server defaults to port 8081", () -> begin
        byte_file = joinpath(repo_root, "BYTE", "src", "BYTE.jl")
        assert_file_exists(byte_file, "BYTE/src/BYTE.jl must exist")
        assert_file_contains(byte_file, r"function\s+serve\(engine;\s*host::String=\"127\.0\.0\.1\",\s*port::Int=8081\)",
                             "BYTE.jl serve() must default to port 8081")
    end; bail=bail)
end

end # module
