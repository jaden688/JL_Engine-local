module TestF02PortBinding

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F02: Port 8081 Alignment"

    # T1-F02-01: Engine default port standardization in src/App.jl
    run_test_case!(report, suite_name, "T1-F02-01", "Engine default port is standardized to 8081 in src/App.jl", () -> begin
        app_file = joinpath(repo_root, "src", "App.jl")
        assert_file_exists(app_file, "src/App.jl must exist")
        assert_file_contains(app_file, r"const\s+DEFAULT_PORT\s*=\s*8081",
                             "src/App.jl must set DEFAULT_PORT = 8081")
    end; bail=bail)

    # T1-F02-02: Windows launcher Launch_SparkByte.bat specifies port 8081
    run_test_case!(report, suite_name, "T1-F02-02", "Launch_SparkByte.bat specifies SPARKBYTE_PORT=8081", () -> begin
        bat_file = joinpath(repo_root, "Launch_SparkByte.bat")
        assert_file_exists(bat_file, "Launch_SparkByte.bat must exist")
        assert_file_contains(bat_file, r"SPARKBYTE_PORT=8081",
                             "Launch_SparkByte.bat must configure SPARKBYTE_PORT=8081")
        assert_file_contains(bat_file, r"http://127\.0\.0\.1:8081/?",
                             "Launch_SparkByte.bat must configure UI URL to port 8081")
    end; bail=bail)

    # T1-F02-03: Windows startup launcher start.bat boots engine via sparkbyte.jl
    run_test_case!(report, suite_name, "T1-F02-03", "start.bat exists and executes sparkbyte.jl on project environment", () -> begin
        start_bat = joinpath(repo_root, "start.bat")
        assert_file_exists(start_bat, "start.bat must exist at repository root")
        assert_file_contains(start_bat, r"julia\s+--project=\.\s+sparkbyte\.jl",
                             "start.bat must run julia --project=. sparkbyte.jl")
    end; bail=bail)

    # T1-F02-04: BYTE server default port in BYTE/src/BYTE.jl defaults to 8081
    run_test_case!(report, suite_name, "T1-F02-04", "BYTE web server default port is 8081", () -> begin
        byte_file = joinpath(repo_root, "BYTE", "src", "BYTE.jl")
        assert_file_exists(byte_file, "BYTE/src/BYTE.jl must exist")
        assert_file_contains(byte_file, r"function\s+serve\(engine;\s*host::String=\"127\.0\.0\.1\",\s*port::Int=8081\)",
                             "BYTE.jl serve() must default to port 8081")
    end; bail=bail)

    # T1-F02-05: Port override support: SPARKBYTE_PORT environment override is respected
    run_test_case!(report, suite_name, "T1-F02-05", "SPARKBYTE_PORT environment override is parsed and respected", () -> begin
        with_isolated_env(Dict("SPARKBYTE_PORT" => "19090"), () -> begin
            raw = get(ENV, "SPARKBYTE_PORT", "8081")
            parsed_port = something(tryparse(Int, raw), 8081)
            assert_equal(parsed_port, 19090, "Parsed port must match environment override 19090")
        end)
    end; bail=bail)
end

end # module
