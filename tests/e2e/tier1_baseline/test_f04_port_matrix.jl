module TestF04PortMatrix

using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F04: Port Matrix & Architecture Baseline"

    # T1-F04-01: Baseline documentation docs/ascension/ARCHITECTURE_BASELINE.md exists
    run_test_case!(report, suite_name, "T1-F04-01", "docs/ascension/ARCHITECTURE_BASELINE.md exists and is documented", () -> begin
        arch_file = joinpath(repo_root, "docs", "ascension", "ARCHITECTURE_BASELINE.md")
        assert_file_exists(arch_file, "ARCHITECTURE_BASELINE.md must exist in docs/ascension/")
        assert_file_contains(arch_file, r"# Architecture Baseline & System Specification",
                             "ARCHITECTURE_BASELINE.md must contain title heading")
        assert_file_contains(arch_file, r"Wave 0 Technical Architecture Baseline",
                             "ARCHITECTURE_BASELINE.md must state Wave 0 scope")
    end; bail=bail)

    # T1-F04-02: Port matrix docs/ascension/PORT_MATRIX.md exists and catalogs 29 candidates
    run_test_case!(report, suite_name, "T1-F04-02", "docs/ascension/PORT_MATRIX.md catalogs 29 reference candidates", () -> begin
        matrix_file = joinpath(repo_root, "docs", "ascension", "PORT_MATRIX.md")
        assert_file_exists(matrix_file, "PORT_MATRIX.md must exist in docs/ascension/")
        content = read(matrix_file, String)
        # Verify candidate count
        assert_match(r"\b29\b", content, "PORT_MATRIX.md must document 29 candidates")
        for i in 1:29
            cid = string("C-", lpad(i, 2, "0"))
            assert_match(cid, content, "PORT_MATRIX.md must contain candidate $cid")
        end
    end; bail=bail)

    # T1-F04-03: Port matrix decisions are explicit across all categories
    run_test_case!(report, suite_name, "T1-F04-03", "Port matrix decisions contain explicit categories", () -> begin
        matrix_file = joinpath(repo_root, "docs", "ascension", "PORT_MATRIX.md")
        assert_file_exists(matrix_file, "PORT_MATRIX.md must exist")
        content = read(matrix_file, String)
        categories = ["ALREADY PRESENT", "PORT", "ADAPT", "DEFER", "REJECT"]
        for cat in categories
            assert_match(cat, content, "PORT_MATRIX.md must categorize decisions with $cat")
        end
    end; bail=bail)

    # T1-F04-04: Verified commit hashes are documented for all source repositories
    run_test_case!(report, suite_name, "T1-F04-04", "Verified commit hashes are documented for all reference remotes", () -> begin
        arch_file = joinpath(repo_root, "docs", "ascension", "ARCHITECTURE_BASELINE.md")
        assert_file_exists(arch_file, "ARCHITECTURE_BASELINE.md must exist")
        content = read(arch_file, String)
        assert_match(r"9bd604e1fcee7eb40f462734d2e8d492e5ad3886", content, "Origin commit SHA must be documented")
        assert_match(r"5198053f5426db1cb17a085dd5376290ef9e3373", content, "VRP commit SHA must be documented")
        assert_match(r"625e760d489ad948efeceb0a21fe94db4f870132", content, "Omni-old commit SHA must be documented")
        assert_match(r"631e2c83f1fd9f0b13fc0bdd475d75fe2e505830", content, "Sparkbyte-SB commit SHA must be documented")
    end; bail=bail)

    # T1-F04-05: Reference remote URLs match authoritative repository endpoints
    run_test_case!(report, suite_name, "T1-F04-05", "Reference remote URLs match authoritative repository endpoints", () -> begin
        arch_file = joinpath(repo_root, "docs", "ascension", "ARCHITECTURE_BASELINE.md")
        assert_file_exists(arch_file, "ARCHITECTURE_BASELINE.md must exist")
        content = read(arch_file, String)
        assert_match(r"github\.com/jaden688/JL_Engine-SB\.Omni", content, "Origin repository URL must match")
        assert_match(r"github\.com/jaden688/jl-engine-vrp", content, "VRP repository URL must match")
        assert_match(r"github\.com/jaden688/JL_Engine-SB\.Omni-20260702", content, "Omni-old repository URL must match")
        assert_match(r"github\.com/jaden688/JL-Engine-SB", content, "Sparkbyte-SB repository URL must match")
    end; bail=bail)
end

end # module
