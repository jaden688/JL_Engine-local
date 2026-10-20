module TestF03DestructiveRejection

using SQLite
using DataFrames
using ...TAPReporter
using ...TestHarness

export run_suite!

function run_suite!(report::TestRunReport, repo_root::String; bail::Bool=false)
    suite_name = "F03: Destructive Recovery Rejection"

    # T1-F03-01: Zero blind process kills (taskkill /f /im julia.exe) in startup scripts
    run_test_case!(report, suite_name, "T1-F03-01", "Startup scripts reject blind taskkill anti-pattern", () -> begin
        checked_files = [
            joinpath(repo_root, "Launch_SparkByte.bat"),
            joinpath(repo_root, "start.bat"),
            joinpath(repo_root, "sparkbyte.jl"),
            joinpath(repo_root, "sparkbyte.sh")
        ]
        for f in checked_files
            if isfile(f)
                content = read(f, String)
                # Check for destructive blind process kills on port 8081
                assert_true(!occursin(r"taskkill\s+/[Ff]\s+/[Ii][Mm]\s+julia\.exe", content),
                            "File $f must not contain blind taskkill command")
                assert_true(!occursin(r"findstr\s+:8081.*taskkill", content),
                            "File $f must not contain port-targeted taskkill pattern")
            end
        end
    end; bail=bail)

    # T1-F03-02: Zero automated deletion of SQLite WAL/SHM files
    run_test_case!(report, suite_name, "T1-F03-02", "Scripts reject manual SQLite WAL/SHM file deletion", () -> begin
        checked_files = [
            joinpath(repo_root, "Launch_SparkByte.bat"),
            joinpath(repo_root, "start.bat"),
            joinpath(repo_root, "sparkbyte.jl"),
            joinpath(repo_root, "sparkbyte.sh"),
            joinpath(repo_root, "src", "App.jl")
        ]
        for f in checked_files
            if isfile(f)
                content = read(f, String)
                assert_true(!occursin(r"rm\s+(-f\s+)?.*\.db-wal", content),
                            "File $f must not contain automated deletion of .db-wal files")
                assert_true(!occursin(r"del\s+(/f\s+)?.*\.db-wal", content),
                            "File $f must not contain automated deletion of .db-wal files")
                assert_true(!occursin(r"rm\s+(-f\s+)?.*\.db-shm", content),
                            "File $f must not contain automated deletion of .db-shm files")
                assert_true(!occursin(r"del\s+(/f\s+)?.*\.db-shm", content),
                            "File $f must not contain automated deletion of .db-shm files")
            end
        end
    end; bail=bail)

    # T1-F03-03: Non-destructive port conflict detection
    run_test_case!(report, suite_name, "T1-F03-03", "Port probing operates gracefully without process termination", () -> begin
        # Non-destructive port check does not kill anything
        is_open = is_tcp_port_open("127.0.0.1", 8081; timeout_sec=0.2)
        # Should return a boolean cleanly without throwing an exception or calling taskkill
        assert_true(is_open isa Bool, "Port probe must return boolean status")
    end; bail=bail)

    # T1-F03-04: SQLite native WAL recovery operates via PRAGMA wal_checkpoint
    run_test_case!(report, suite_name, "T1-F03-04", "SQLite recovery uses native PRAGMA wal_checkpoint without file deletion", () -> begin
        with_temp_sandbox((sandbox_dir) -> begin
            db_path = joinpath(sandbox_dir, "test_recovery.db")
            db = SQLite.DB(db_path)
            SQLite.execute(db, "PRAGMA journal_mode=WAL;")
            SQLite.execute(db, "CREATE TABLE test_kv (k TEXT PRIMARY KEY, v TEXT);")
            SQLite.execute(db, "INSERT INTO test_kv VALUES ('test_key', 'test_value');")
            
            # Execute native SQLite checkpoint
            SQLite.execute(db, "PRAGMA wal_checkpoint(PASSIVE);")
            SQLite.close(db)
            
            # Reopen and verify data integrity
            db2 = SQLite.DB(db_path)
            df = DataFrame(SQLite.DBInterface.execute(db2, "SELECT v FROM test_kv WHERE k='test_key'"))
            SQLite.close(db2)
            
            assert_equal(nrow(df), 1, "Record must persist across checkpoint")
            assert_equal(String(df.v[1]), "test_value", "Persisted value must match original")
        end)
    end; bail=bail)

    # T1-F03-05: Clean shutdown handlers exist in src/App.jl
    run_test_case!(report, suite_name, "T1-F03-05", "Clean resource de-allocation hooks exist via atexit", () -> begin
        app_file = joinpath(repo_root, "src", "App.jl")
        assert_file_exists(app_file, "src/App.jl must exist")
        assert_file_contains(app_file, r"atexit\(\)\s*do",
                             "src/App.jl must register atexit cleanup hooks")
    end; bail=bail)
end

end # module
