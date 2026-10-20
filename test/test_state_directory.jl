using Test
using JLEngine
using SQLite

@testset "Runtime state directory" begin
    root = mktempdir()
    custom_state = mktempdir()
    try
        withenv("SPARKBYTE_STATE_DIR" => "") do
            @test JLEngine.state_root(root) == joinpath(root, "data")
        end

        withenv("SPARKBYTE_STATE_DIR" => custom_state) do
            @test JLEngine.state_root(root) == custom_state
            @test JLEngine.BYTE._runtime_state_path("sparkbyte_memory.db"; root=root) ==
                joinpath(custom_state, "sparkbyte_memory.db")
            db = JLEngine._open_memory_db(root)
            try
                @test isfile(joinpath(custom_state, "sparkbyte_memory.db"))
                @test !isfile(joinpath(root, "data", "sparkbyte_memory.db"))
            finally
                SQLite.close(db)
            end
        end
    finally
        rm(root; recursive=true, force=true)
        rm(custom_state; recursive=true, force=true)
    end
end
