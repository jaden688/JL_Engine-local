module TestHarness

using Sockets
using Dates
using SQLite
using ..TAPReporter

export with_temp_sandbox, with_isolated_env, is_tcp_port_open,
       run_cli_command, verify_sqlite_integrity,
       assert_true, assert_equal, assert_match, assert_file_exists,
       assert_file_contains, assert_file_not_contains,
       run_test_case!

struct AssertionFailure <: Exception
    message::String
end

function assert_true(condition::Bool, message::String="Expected condition to be true")
    if !condition
        throw(AssertionFailure(message))
    end
    return true
end

function assert_equal(actual, expected, message::String="")
    if !isequal(actual, expected)
        prefix = isempty(message) ? "Assertion failed" : message
        throw(AssertionFailure("$prefix: expected $(repr(expected)), got $(repr(actual))"))
    end
    return true
end

function assert_match(pattern::Union{Regex, AbstractString}, text::AbstractString, message::String="")
    if !occursin(pattern, text)
        prefix = isempty(message) ? "Pattern match failed" : message
        throw(AssertionFailure("$prefix: pattern $(repr(pattern)) not found in text:\n$text"))
    end
    return true
end

function assert_file_exists(path::AbstractString, message::String="")
    if !ispath(path)
        prefix = isempty(message) ? "File existence assertion failed" : message
        throw(AssertionFailure("$prefix: file does not exist at path: $path"))
    end
    return true
end

function assert_file_contains(path::AbstractString, pattern::Union{Regex, AbstractString}, message::String="")
    assert_file_exists(path, "Cannot check content of non-existent file")
    content = read(path, String)
    if !occursin(pattern, content)
        prefix = isempty(message) ? "File content match failed" : message
        throw(AssertionFailure("$prefix: file $path does not contain pattern $(repr(pattern))"))
    end
    return true
end

function assert_file_not_contains(path::AbstractString, pattern::Union{Regex, AbstractString}, message::String="")
    assert_file_exists(path, "Cannot check content of non-existent file")
    content = read(path, String)
    if occursin(pattern, content)
        prefix = isempty(message) ? "File content violation" : message
        throw(AssertionFailure("$prefix: file $path contains forbidden pattern $(repr(pattern))"))
    end
    return true
end

function with_temp_sandbox(fn::Function)
    tmp_dir = mktempdir()
    try
        return fn(tmp_dir)
    finally
        try
            rm(tmp_dir; recursive=true, force=true)
        catch
            # Best-effort cleanup on Windows file lock delays
        end
    end
end

function with_isolated_env(overrides::Dict{String, String}, fn::Function)
    # Save original ENV values
    original = Dict{String, Union{String, Nothing}}()
    for (k, v) in overrides
        original[k] = get(ENV, k, nothing)
        ENV[k] = v
    end
    try
        return fn()
    finally
        for (k, orig_val) in original
            if orig_val === nothing
                delete!(ENV, k)
            else
                ENV[k] = orig_val
            end
        end
    end
end

function is_tcp_port_open(host::String, port::Int; timeout_sec::Float64=1.0)::Bool
    try
        sock = connect(host, port)
        close(sock)
        return true
    catch
        return false
    end
end

function run_cli_command(cmd_args::Vector{String}; cwd::String="", timeout_sec::Float64=30.0)
    stdout_buf = IOBuffer()
    stderr_buf = IOBuffer()
    
    cmd = Cmd(cmd_args)
    if !isempty(cwd)
        cmd = setenv(cmd; dir=cwd)
    end

    proc = run(pipeline(ignorestatus(cmd), stdout=stdout_buf, stderr=stderr_buf); wait=false)
    
    # Wait with timeout
    start_t = time()
    while process_running(proc)
        if time() - start_t > timeout_sec
            try
                kill(proc)
            catch
            end
            return (exit_code=-1, stdout=String(take!(stdout_buf)), stderr="Command timed out after $(timeout_sec)s")
        end
        sleep(0.05)
    end

    exit_code = proc.exitcode
    return (
        exit_code = exit_code,
        stdout = String(take!(stdout_buf)),
        stderr = String(take!(stderr_buf))
    )
end

function verify_sqlite_integrity(db_path::String)
    assert_file_exists(db_path, "SQLite database file not found")
    db = SQLite.DB(db_path)
    try
        res = SQLite.DBInterface.execute(db, "PRAGMA integrity_check;")
        rows = collect(res)
        if isempty(rows) || rows[1][1] != "ok"
            throw(AssertionFailure("SQLite integrity check failed on $db_path"))
        end
        return true
    finally
        SQLite.close(db)
    end
end

function run_test_case!(report::TestRunReport, suite_name::String, id::String, name::String, test_fn::Function; bail::Bool=false)
    t0 = time()
    passed = false
    diagnostic = nothing
    try
        test_fn()
        passed = true
    catch err
        passed = false
        if err isa AssertionFailure
            diagnostic = err.message
        else
            diagnostic = "Unexpected exception: $(sprint(showerror, err, catch_backtrace()))"
        end
    end
    duration = time() - t0
    record_result!(report, suite_name, id, name, passed; duration=duration, diagnostic=diagnostic)
    
    if !passed && bail
        throw(AssertionFailure("Bailing out on first failure: $id: $diagnostic"))
    end
    return passed
end

end # module
