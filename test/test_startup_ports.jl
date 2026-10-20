using Test, Sockets, JLEngine
@testset "startup checks both listeners before initialization" begin
    listener = Sockets.listen(ip"127.0.0.1", 0)
    occupied = Int(Sockets.getsockname(listener)[2])
    free = Sockets.listen(ip"127.0.0.1", 0)
    other = Int(Sockets.getsockname(free)[2])
    close(free)
    try
        @test_throws JLEngine.RuntimePortConflict JLEngine._validate_runtime_ports("127.0.0.1", occupied, "127.0.0.1", other)
        @test_throws JLEngine.RuntimePortConflict JLEngine._validate_runtime_ports("127.0.0.1", other, "127.0.0.1", occupied)
        @test_throws ArgumentError JLEngine._validate_runtime_ports("127.0.0.1", other, "127.0.0.1", other)
    finally
        close(listener)
    end
    @test isnothing(JLEngine._validate_runtime_ports("127.0.0.1", occupied, "127.0.0.1", other))
end
