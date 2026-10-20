using Test, SQLite, JLEngine
const RegressionBYTE = JLEngine.BYTE
@testset "saved history order and budget" begin
    previous = RegressionBYTE._state[:db]
    db = SQLite.DB()
    SQLite.execute(db, "CREATE TABLE conversation_turns (id INTEGER PRIMARY KEY, user_text TEXT, assistant_text TEXT)")
    SQLite.execute(db, "INSERT INTO conversation_turns VALUES (1, 'question-one', 'answer-one'), (2, 'question-two', 'answer-two')")
    RegressionBYTE._state[:db] = db
    try
        h = RegressionBYTE._load_recent_conversation_history()
        @test [x["role"] for x in h] == ["user", "model", "user", "model"]
        @test [x["parts"][1]["text"] for x in h] == ["question-one", "answer-one", "question-two", "answer-two"]
        @test isempty(RegressionBYTE._load_recent_conversation_history(char_budget=1))
    finally
        RegressionBYTE._state[:db] = previous
        SQLite.close(db)
    end
end
@testset "WebSocket diagnostic follows payloads" begin
    if isdefined(RegressionBYTE, :_ws_emitted_types)
        fixture = raw"""
        function dependency_payload()
            return Dict("type"=>"builder_dependencies", "links"=>[])
        end
        function mind_payload()
            nodes = [Dict("id"=>"x", "type"=>"concept")]
            return Dict("type"=>"mind_graph", "nodes"=>nodes)
        end
        function send_messages(ws)
            schema = Dict("type"=>"object", "properties"=>Dict("x"=>Dict("type"=>"string")))
            payload = dependency_payload()
            _ws_send(ws, JSON.json(payload))
            _broadcast(mind_payload())
            _ws_send(ws, Dict("type"=>"new_unhandled", "nested"=>Dict("type"=>"memory")))
        end
        """
        @test RegressionBYTE._ws_emitted_types([fixture]) == Set(["builder_dependencies", "mind_graph", "new_unhandled"])
        src = joinpath(@__DIR__, "..", "BYTE", "src")
        types = RegressionBYTE._ws_emitted_types([read(joinpath(src, f), String) for f in readdir(src) if endswith(f, ".jl")])
        @test "builder_dependencies" in types
        @test "backend_state" in types
        @test "mind_graph" in types
        @test isempty(intersect(types, Set(["concept", "goal", "memory", "object", "state", "string"])))
    else
        @test false
    end
end

@testset "runtime prompt uses observed paths" begin
    b = RegressionBYTE
    oldroot, oldurl = b._project_root[], b._runtime_ui_url[]
    b._project_root[] = "runtime-project-fixture"
    b._runtime_ui_url[] = "http://127.0.0.1:9876/"
    try
        engine = (current_agent_data=Dict("identity"=>Dict("name"=>"SparkByte")),
                  current_agent_name="SparkByte", current_agent_file="fixture.json")
        prompt = b._compose_authoritative_agent_prompt(engine, "", "", "")
        @test occursin("Project root: runtime-project-fixture", prompt)
        @test occursin("UI URL: http://127.0.0.1:9876/", prompt)
    finally
        b._project_root[], b._runtime_ui_url[] = oldroot, oldurl
    end
end
module StartupHealthRegression
using Test
include(joinpath(@__DIR__, "..", "health_check.jl"))
@testset "startup checker excludes schema and normal returns" begin
    root = normpath(joinpath(@__DIR__, ".."))
    issues = _scan_ws_types(joinpath(root, "BYTE", "src", "BYTE.jl"))
    @test Set(x.msg for x in issues) == Set(
        "Server sends WS type $t but ui.html has no handler for it"
        for t in ["julian_curiosity", "speech", "speech_error"])
    mktemp() do path, io
        write(io, "function done()\n    return nothing\nend\n")
        close(io)
        @test all(x -> x.code != :return_nothing, _scan_file(path))
    end
end
end
