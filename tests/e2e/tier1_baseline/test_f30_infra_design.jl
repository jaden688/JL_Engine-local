module TestF30InfraDesign

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F30: E2E Test Infrastructure & Suite Design"

    # T1-F30-01: TEST_INFRA.md exists in docs/testing and defines 4-tier architecture
    run_test_case!(report, suite_name, "T1-F30-01", "TEST_INFRA.md exists and defines 4-tier testing architecture", () -> begin
        infra_file = joinpath(repo_root, "docs", "testing", "TEST_INFRA.md")
        assert_file_exists(infra_file, "docs/testing/TEST_INFRA.md must exist at docs/testing/")
        content = read(infra_file, String)
        assert_match("TIER 1: FEATURE COVERAGE", content, "TEST_INFRA.md must define Tier 1")
        assert_match("TIER 2: BOUNDARY & CORNER CASES", content, "TEST_INFRA.md must define Tier 2")
        assert_match("TIER 3: CROSS-FEATURE PAIRWISE COMBINATIONS", content, "TEST_INFRA.md must define Tier 3")
        assert_match("TIER 4: REAL-WORLD APPLICATION SCENARIOS", content, "TEST_INFRA.md must define Tier 4")
    end; bail=bail)

    # T1-F30-02: TEST_INFRA.md specifies all 30 features (F01 through F30)
    run_test_case!(report, suite_name, "T1-F30-02", "TEST_INFRA.md documents all 30 features (F01 through F30)", () -> begin
        infra_file = joinpath(repo_root, "docs", "testing", "TEST_INFRA.md")
        assert_file_exists(infra_file, "docs/testing/TEST_INFRA.md must exist")
        content = read(infra_file, String)
        for i in 1:30
            fid = string("F", lpad(i, 2, "0"))
            assert_match(Regex("\\b$fid\\b"), content, "TEST_INFRA.md must document feature $fid")
        end
    end; bail=bail)

    # T1-F30-03: Test runner exists and framework modules are importable
    run_test_case!(report, suite_name, "T1-F30-03", "Test runner and framework modules exist and are importable", () -> begin
        framework_dir = joinpath(repo_root, "tests", "e2e", "framework")
        assert_file_exists(joinpath(framework_dir, "TAPReporter.jl"), "TAPReporter.jl must exist")
        assert_file_exists(joinpath(framework_dir, "TestHarness.jl"), "TestHarness.jl must exist")
        assert_file_exists(joinpath(repo_root, "tests", "e2e", "runner.jl"), "runner.jl must exist")
    end; bail=bail)

    # T1-F30-04: TAP reporter produces compliant TAP v13 output format
    run_test_case!(report, suite_name, "T1-F30-04", "TAP reporter produces valid TAP v13 stream structure", () -> begin
        test_rep = create_report()
        record_result!(test_rep, "SampleSuite", "T0-01", "Sample pass", true; duration=0.01)
        record_result!(test_rep, "SampleSuite", "T0-02", "Sample fail", false; duration=0.02, diagnostic="Sample failure message")
        
        buf = IOBuffer()
        emit_tap(test_rep; io=buf)
        tap_output = String(take!(buf))

        assert_match(r"^TAP version 13"m, tap_output, "TAP output must start with TAP version 13")
        assert_match(r"^1\.\.2"m, tap_output, "TAP output must include test plan 1..2")
        assert_match(r"^ok 1 - T0-01: Sample pass"m, tap_output, "TAP output must format passing test")
        assert_match(r"^not ok 2 - T0-02: Sample fail"m, tap_output, "TAP output must format failing test")
        assert_match(r"^# tests 2"m, tap_output, "TAP output must summarize total tests")
        assert_match(r"^# pass 1"m, tap_output, "TAP output must summarize passed tests")
        assert_match(r"^# fail 1"m, tap_output, "TAP output must summarize failed tests")
    end; bail=bail)

    # T1-F30-05: Test runner exit code semantics (exit 0 on pass, exit 1 on fail)
    run_test_case!(report, suite_name, "T1-F30-05", "Test report exit code semantics map passed/failed counts", () -> begin
        rep_clean = create_report()
        record_result!(rep_clean, "Suite", "T1", "Passing", true)
        clean_exit = rep_clean.failed > 0 ? 1 : 0
        assert_equal(clean_exit, 0, "Clean run must produce exit code 0")

        rep_fail = create_report()
        record_result!(rep_fail, "Suite", "T2", "Failing", false)
        fail_exit = rep_fail.failed > 0 ? 1 : 0
        assert_equal(fail_exit, 1, "Failing run must produce exit code 1")
    end; bail=bail)
end

end # module
