#!/usr/bin/env julia
# ==============================================================================
# OPERATION OMNI ASCENSION: END-TO-END TEST RUNNER (runner.jl)
# ==============================================================================
# Usage:
#   julia --project=. tests/e2e/runner.jl [options]
#
# Options:
#   --tier=<1|2|3|4|all>        Run specific test tier (default: 1)
#   --feature=<F01..F30|all>    Run tests for specific feature (default: all)
#   --format=<tap|junit|summary> Output format (default: tap)
#   --out=<filepath>            Write report to file
#   --bail                      Stop immediately on first failure
#   --help                      Display usage and exit
# ==============================================================================

import Pkg
repo_root = normpath(joinpath(@__DIR__, "..", ".."))

# Include Framework
include(joinpath(@__DIR__, "framework", "TAPReporter.jl"))
using .TAPReporter

include(joinpath(@__DIR__, "framework", "TestHarness.jl"))
using .TestHarness

# Include Baseline Tier 1 Test Suites
include(joinpath(@__DIR__, "tier1_baseline", "test_f01_git_baseline.jl"))
using .TestF01GitBaseline

include(joinpath(@__DIR__, "tier1_baseline", "test_f02_port_binding.jl"))
using .TestF02PortBinding

include(joinpath(@__DIR__, "tier1_baseline", "test_f03_destructive_rejection.jl"))
using .TestF03DestructiveRejection

include(joinpath(@__DIR__, "tier1_baseline", "test_f04_port_matrix.jl"))
using .TestF04PortMatrix

include(joinpath(@__DIR__, "tier1_baseline", "test_f05_reference_ports.jl"))
using .TestF05ReferencePorts

include(joinpath(@__DIR__, "tier1_baseline", "test_f30_infra_design.jl"))
using .TestF30InfraDesign

function print_usage()
    println("""
Operation Omni Ascension: E2E Test Runner
Usage: julia --project=. tests/e2e/runner.jl [options]

Options:
  --tier=<1|2|3|4|all>        Test tier to execute (default: 1)
  --feature=<F01..F30|all>    Filter by feature ID (default: all)
  --format=<tap|junit|summary> Output format (default: tap)
  --out=<filepath>            Output file destination
  --bail                      Halt execution on first test failure
  --help                      Show this help message
""")
end

function parse_cli_args(args::Vector{String})
    opts = Dict{Symbol, Any}(
        :tier => "1",
        :feature => "ALL",
        :format => "tap",
        :out => nothing,
        :bail => false
    )

    for arg in args
        if arg == "--help" || arg == "-h"
            print_usage()
            exit(0)
        elseif startswith(arg, "--tier=")
            opts[:tier] = split(arg, "=", limit=2)[2]
        elseif startswith(arg, "--feature=")
            opts[:feature] = uppercase(split(arg, "=", limit=2)[2])
        elseif startswith(arg, "--format=")
            opts[:format] = lowercase(split(arg, "=", limit=2)[2])
        elseif startswith(arg, "--out=")
            opts[:out] = split(arg, "=", limit=2)[2]
        elseif arg == "--bail"
            opts[:bail] = true
        else
            @warn "Unknown CLI argument: $arg"
        end
    end
    return opts
end

function main()
    opts = parse_cli_args(ARGS)
    report = create_report()

    # Define registered baseline suites
    baseline_suites = [
        ("F01", (rep) -> TestF01GitBaseline.run_suite!(rep, repo_root; bail=opts[:bail])),
        ("F02", (rep) -> TestF02PortBinding.run_suite!(rep, repo_root; bail=opts[:bail])),
        ("F03", (rep) -> TestF03DestructiveRejection.run_suite!(rep, repo_root; bail=opts[:bail])),
        ("F04", (rep) -> TestF04PortMatrix.run_suite!(rep, repo_root; bail=opts[:bail])),
        ("F05", (rep) -> TestF05ReferencePorts.run_suite!(rep, repo_root; bail=opts[:bail])),
        ("F30", (rep) -> TestF30InfraDesign.run_suite!(rep, repo_root; bail=opts[:bail]))
    ]

    # Filter suites by requested feature
    selected_feature = opts[:feature]
    suites_to_run = if selected_feature == "ALL"
        baseline_suites
    else
        filter(s -> s[1] == selected_feature, baseline_suites)
    end

    if isempty(suites_to_run)
        println("⚠️ No matching test suites for feature: $selected_feature")
        exit(0)
    end

    # Run selected suites
    for (fid, run_fn) in suites_to_run
        try
            run_fn(report)
        catch err
            if opts[:bail]
                @error "Bailed out on error in suite $fid: $(err)"
                break
            else
                @error "Error executing suite $fid: $(err)"
            end
        end
    end

    # Always persist JSON summary artifact
    results_dir = joinpath(repo_root, "tests", "e2e", "results")
    mkpath(results_dir)
    summary_path = joinpath(results_dir, "summary.json")
    emit_summary_json(report, summary_path)

    # Format output
    out_target = opts[:out]
    if opts[:format] == "tap"
        if out_target !== nothing
            open(out_target, "w") do f
                emit_tap(report; io=f)
            end
            println("TAP report written to: $out_target")
        else
            emit_tap(report; io=stdout)
        end
    elseif opts[:format] == "junit"
        junit_path = out_target !== nothing ? out_target : joinpath(results_dir, "junit.xml")
        emit_junit(report, junit_path)
        println("JUnit XML report written to: $junit_path")
        print_console_summary(report)
    elseif opts[:format] == "summary"
        print_console_summary(report)
    end

    # Exit code semantics: 0 for all pass, 1 for any failure
    exit(report.failed > 0 ? 1 : 0)
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
