module TestF05ReferencePorts

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F05: Canonical Runtime Entrypoint"

    run_test_case!(report, suite_name, "T1-F05-01", ".env.example documents runtime settings", () -> begin
        env_example = joinpath(repo_root, ".env.example")
        assert_file_exists(env_example, ".env.example must exist at repository root")
        content = read(env_example, String)
        assert_match("OPENROUTER_API_KEY", content, ".env.example must document OPENROUTER_API_KEY")
        assert_match("SPARKBYTE_PORT=8081", content, ".env.example must specify default SPARKBYTE_PORT=8081")
    end; bail=bail)

    run_test_case!(report, suite_name, "T1-F05-02", "Canonical Julia entrypoint uses package runtime", () -> begin
        entry = joinpath(repo_root, "start.jl")
        assert_file_exists(entry, "start.jl must exist")
        content = read(entry, String)
        assert_match(r"Pkg\.activate\(@__DIR__\)", content, "start.jl must activate the project")
        assert_match(r"JLEngine\.julia_main\(\)", content, "start.jl must call JLEngine.julia_main")
    end; bail=bail)

    run_test_case!(report, suite_name, "T1-F05-03", "Docker uses the same canonical entrypoint", () -> begin
        dockerfile = joinpath(repo_root, "Dockerfile")
        assert_file_exists(dockerfile, "Dockerfile must exist")
        assert_file_contains(dockerfile, r"CMD\s+\[\"julia\",\s*\"--project=\.\",\s*\"start\.jl\"\]",
                             "Docker must launch start.jl")
    end; bail=bail)
end

end # module
