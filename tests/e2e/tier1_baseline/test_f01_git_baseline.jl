module TestF01GitBaseline

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F01: Git Baseline & Branch Setup"

    # T1-F01-01: Git repository tracking root points to primary remote
    run_test_case!(report, suite_name, "T1-F01-01", "Git repository tracking root points to primary remote", () -> begin
        git_dir = joinpath(repo_root, ".git")
        assert_file_exists(git_dir, ".git directory must exist in repository root")
        res = run_cli_command(["git", "remote", "-v"]; cwd=repo_root)
        assert_equal(res.exit_code, 0, "git remote -v must succeed")
        assert_match(r"github\.com[/:].*JL_Engine-SB\.Omni(\.git)?", res.stdout,
                     "Remote tracking must reference JL_Engine-SB.Omni")
    end; bail=bail)

    # T1-F01-02: Active development branch is feature/omni-ascension
    run_test_case!(report, suite_name, "T1-F01-02", "Active development branch is feature/omni-ascension", () -> begin
        res = run_cli_command(["git", "branch", "--show-current"]; cwd=repo_root)
        assert_equal(res.exit_code, 0, "git branch --show-current must succeed")
        branch = strip(res.stdout)
        assert_equal(branch, "feature/omni-ascension", "Current git branch must be feature/omni-ascension")
    end; bail=bail)

    # T1-F01-03: Baseline commit history reflects upstream HEAD ancestry
    run_test_case!(report, suite_name, "T1-F01-03", "Baseline commit history reflects upstream HEAD ancestry", () -> begin
        res = run_cli_command(["git", "log", "-n", "10", "--oneline"]; cwd=repo_root)
        assert_equal(res.exit_code, 0, "git log must execute successfully")
        assert_true(length(strip(res.stdout)) > 0, "Git commit history must not be empty")
    end; bail=bail)

    # T1-F01-04: .gitignore excludes sensitive files (.env, *.db)
    run_test_case!(report, suite_name, "T1-F01-04", ".gitignore excludes sensitive files (.env, *.db)", () -> begin
        gitignore_path = joinpath(repo_root, ".gitignore")
        assert_file_exists(gitignore_path, ".gitignore must exist")
        assert_file_contains(gitignore_path, r"^\.env\b"m, ".gitignore must ignore .env")
        assert_file_contains(gitignore_path, r"\*\.db\b"m, ".gitignore must ignore *.db")
    end; bail=bail)

    # T1-F01-05: Reference remotes are queryable without overwriting origin
    run_test_case!(report, suite_name, "T1-F01-05", "Reference remotes are queryable without overwriting origin", () -> begin
        res = run_cli_command(["git", "remote"]; cwd=repo_root)
        assert_equal(res.exit_code, 0, "git remote must succeed")
        remotes = split(strip(res.stdout))
        assert_true("origin" in remotes, "origin remote must be present")
    end; bail=bail)
end

end # module
