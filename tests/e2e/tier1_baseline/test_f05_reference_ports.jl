module TestF05ReferencePorts

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F05: Reference Candidate Ports (Wave 0)"

    # T1-F05-01: Standardized .env.example exists at repository root
    run_test_case!(report, suite_name, "T1-F05-01", ".env.example exists and documents OpenRouter and runtime parameters", () -> begin
        env_example = joinpath(repo_root, ".env.example")
        assert_file_exists(env_example, ".env.example must exist at repository root")
        content = read(env_example, String)
        assert_match("OPENROUTER_API_KEY", content, ".env.example must document OPENROUTER_API_KEY")
        assert_match("SPARKBYTE_PORT=8081", content, ".env.example must specify default SPARKBYTE_PORT=8081")
        assert_match("DEFAULT_OPENROUTER_MODEL", content, ".env.example must specify DEFAULT_OPENROUTER_MODEL")
    end; bail=bail)

    # T1-F05-02: Early .env file loader in sparkbyte.jl loads variables before imports
    run_test_case!(report, suite_name, "T1-F05-02", "sparkbyte.jl contains early .env loader prior to package imports", () -> begin
        sparkbyte_file = joinpath(repo_root, "sparkbyte.jl")
        assert_file_exists(sparkbyte_file, "sparkbyte.jl must exist")
        content = read(sparkbyte_file, String)
        assert_match(r"env_path\s*=\s*joinpath\(@__DIR__,\s*\"\.env\"\)", content,
                     "sparkbyte.jl must look for local .env file")
        assert_match(r"ENV\[m\[1\]\]\s*=", content,
                     "sparkbyte.jl must populate ENV from .env")
    end; bail=bail)

    # T1-F05-03: health_check.jl executes cleanly via CLI with exit code 0
    run_test_case!(report, suite_name, "T1-F05-03", "health_check.jl executes successfully via CLI", () -> begin
        julia_args = String[arg for arg in Base.julia_cmd().exec]
        cmd = vcat(julia_args, String["--project=.", "health_check.jl"])
        res = run_cli_command(cmd; cwd=repo_root, timeout_sec=25.0)
        assert_equal(res.exit_code, 0, "health_check.jl must exit with status 0. Stderr: $(res.stderr)")
    end; bail=bail)

    # T1-F05-04: health_check.log reports 0 errors and 0 warnings
    run_test_case!(report, suite_name, "T1-F05-04", "health_check.log confirms zero errors and zero warnings", () -> begin
        log_file = joinpath(repo_root, "health_check.log")
        assert_file_exists(log_file, "health_check.log must be created")
        content = read(log_file, String)
        assert_match(r"0\s+errors\s+0\s+warnings", content, "health_check.log must report 0 errors 0 warnings")
        assert_match(r"✓\s*Clean", content, "health_check.log must report Clean status")
    end; bail=bail)

    # T1-F05-05: Windows launchers invoke Julia with --project=.
    run_test_case!(report, suite_name, "T1-F05-05", "Windows launchers invoke Julia with --project=.", () -> begin
        launch_bat = joinpath(repo_root, "Launch_SparkByte.bat")
        start_bat = joinpath(repo_root, "start.bat")
        assert_file_exists(launch_bat, "Launch_SparkByte.bat must exist")
        assert_file_exists(start_bat, "start.bat must exist")
        assert_file_contains(launch_bat, r"--project=\.", "Launch_SparkByte.bat must use --project=.")
        assert_file_contains(start_bat, r"--project=\.", "start.bat must use --project=.")
    end; bail=bail)
end

end # module
