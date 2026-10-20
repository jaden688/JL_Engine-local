module TAPReporter

using Dates
using JSON

export TestCaseResult, TestSuite, TestRunReport,
       create_report, record_result!, emit_tap, emit_junit, emit_summary_json, print_console_summary

struct TestCaseResult
    id          :: String
    name        :: String
    passed      :: Bool
    duration    :: Float64
    diagnostic  :: Union{String, Nothing}
end

mutable struct TestSuite
    name        :: String
    results     :: Vector{TestCaseResult}
end

mutable struct TestRunReport
    suites      :: Vector{TestSuite}
    start_time  :: DateTime
    end_time    :: Union{DateTime, Nothing}
    total       :: Int
    passed      :: Int
    failed      :: Int
end

function create_report()
    return TestRunReport(
        TestSuite[],
        now(),
        nothing,
        0,
        0,
        0
    )
end

function get_or_create_suite!(report::TestRunReport, suite_name::String)
    for s in report.suites
        if s.name == suite_name
            return s
        end
    end
    new_suite = TestSuite(suite_name, TestCaseResult[])
    push!(report.suites, new_suite)
    return new_suite
end

function record_result!(report::TestRunReport, suite_name::String, id::String, name::String, passed::Bool;
                        duration::Float64=0.0, diagnostic::Union{String, Nothing}=nothing)
    suite = get_or_create_suite!(report, suite_name)
    res = TestCaseResult(id, name, passed, duration, diagnostic)
    push!(suite.results, res)
    report.total += 1
    if passed
        report.passed += 1
    else
        report.failed += 1
    end
    return res
end

function emit_tap(report::TestRunReport; io::IO=stdout)
    report.end_time = now()
    all_results = TestCaseResult[]
    for suite in report.suites
        append!(all_results, suite.results)
    end
    n = length(all_results)

    println(io, "TAP version 13")
    println(io, "1..$n")

    for (idx, res) in enumerate(all_results)
        status_str = res.passed ? "ok" : "not ok"
        println(io, "$status_str $idx - $(res.id): $(res.name) ($(round(res.duration, digits=3))s)")
        if !res.passed && res.diagnostic !== nothing
            println(io, "  ---")
            println(io, "  severity: fail")
            println(io, "  message: \"$(replace(res.diagnostic, '\"' => "\\\""))\"")
            println(io, "  ...")
        end
    end

    elapsed = round((report.end_time - report.start_time).value / 1000.0, digits=3)
    println(io, "# tests $(report.total)")
    println(io, "# pass $(report.passed)")
    println(io, "# fail $(report.failed)")
    println(io, "# duration $(elapsed)s")
end

function emit_junit(report::TestRunReport, filepath::String)
    report.end_time = now()
    elapsed = round((report.end_time - report.start_time).value / 1000.0, digits=3)
    
    mkpath(dirname(filepath))
    open(filepath, "w") do io
        println(io, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
        println(io, "<testsuites name=\"OmniAscension_E2E\" tests=\"$(report.total)\" failures=\"$(report.failed)\" time=\"$elapsed\">")
        for suite in report.suites
            suite_duration = sum(r.duration for r in suite.results; init=0.0)
            suite_fails = count(r -> !r.passed, suite.results)
            println(io, "  <testsuite name=\"$(escape_xml(suite.name))\" tests=\"$(length(suite.results))\" failures=\"$suite_fails\" time=\"$(round(suite_duration, digits=3))\">")
            for res in suite.results
                println(io, "    <testcase classname=\"$(escape_xml(suite.name))\" name=\"$(escape_xml(res.id)): $(escape_xml(res.name))\" time=\"$(round(res.duration, digits=3))\">")
                if !res.passed
                    diag = res.diagnostic === nothing ? "Test assertion failed" : res.diagnostic
                    println(io, "      <failure message=\"$(escape_xml(diag))\">$(escape_xml(diag))</failure>")
                end
                println(io, "    </testcase>")
            end
            println(io, "  </testsuite>")
        end
        println(io, "</testsuites>")
    end
end

function escape_xml(s::AbstractString)
    s1 = replace(s, '&' => "&amp;")
    s2 = replace(s1, '<' => "&lt;")
    s3 = replace(s2, '>' => "&gt;")
    s4 = replace(s3, '"' => "&quot;")
    return replace(s4, '\'' => "&apos;")
end

function emit_summary_json(report::TestRunReport, filepath::String)
    report.end_time = now()
    elapsed = round((report.end_time - report.start_time).value / 1000.0, digits=3)
    data = Dict(
        "timestamp" => string(report.start_time),
        "duration_seconds" => elapsed,
        "total" => report.total,
        "passed" => report.passed,
        "failed" => report.failed,
        "pass_rate_percent" => report.total == 0 ? 0.0 : round((report.passed / report.total) * 100.0, digits=2),
        "suites" => [
            Dict(
                "name" => s.name,
                "total" => length(s.results),
                "passed" => count(r -> r.passed, s.results),
                "failed" => count(r -> !r.passed, s.results),
                "tests" => [
                    Dict(
                        "id" => r.id,
                        "name" => r.name,
                        "passed" => r.passed,
                        "duration" => r.duration,
                        "diagnostic" => r.diagnostic
                    ) for r in s.results
                ]
            ) for s in report.suites
        ]
    )
    mkpath(dirname(filepath))
    open(filepath, "w") do f
        JSON.print(f, data, 2)
    end
end

function print_console_summary(report::TestRunReport)
    println("\n" * "="^70)
    println("  OPERATION OMNI ASCENSION — E2E TEST EXECUTION SUMMARY")
    println("="^70)
    for suite in report.suites
        s_total = length(suite.results)
        s_pass = count(r -> r.passed, suite.results)
        s_fail = s_total - s_pass
        badge = s_fail == 0 ? "✓ PASS" : "✗ FAIL"
        println("  [$badge] $(rpad(suite.name, 45)) $s_pass / $s_total passed")
    end
    println("-"^70)
    total_badge = report.failed == 0 ? "ALL PASSED" : "FAILURES DETECTED"
    rate = report.total == 0 ? 0.0 : round((report.passed / report.total) * 100.0, digits=1)
    println("  Result: $total_badge ($rate% pass rate)")
    println("  Total: $(report.total) | Passed: $(report.passed) | Failed: $(report.failed)")
    println("="^70 * "\n")
end

end # module
