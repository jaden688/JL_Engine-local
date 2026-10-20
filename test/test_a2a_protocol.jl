using Test
using HTTP
using JSON
using SQLite
using JLEngine

isdefined(Main, :handle_public_a2a_request) || include(joinpath(@__DIR__, "..", "a2a_server.jl"))

if !isdefined(Main, :BYTE)
    @eval Main const BYTE = JLEngine.BYTE
end

function _a2a_test_auth_headers()
    !_a2a_auth_required() && return Pair{String,String}[]
    key = _a2a_admin_key()
    isempty(key) && (key = _a2a_api_key())
    isempty(key) && return nothing
    return ["Authorization" => "Bearer $(key)"]
end

function _a2a_rpc_request(db::SQLite.DB, method::AbstractString, params::AbstractDict; headers=Pair{String,String}[])
    request_headers = Pair{String,String}[
        "Host" => "agent.example.com",
        "X-Forwarded-Proto" => "https",
        "Content-Type" => "application/json",
    ]
    append!(request_headers, headers)
    body = JSON.json(Dict(
        "jsonrpc" => "2.0",
        "id" => "test-1",
        "method" => String(method),
        "params" => params,
    ))
    req = HTTP.Messages.Request("POST", "/", request_headers, body)
    return handle_public_a2a_request(req, db)
end

@testset "A2A protocol" begin
    db = SQLite.DB(":memory:")
    _a2a_init_db!(db)
    auth_headers = _a2a_test_auth_headers()

    @test _a2a_proto_role("user") == "ROLE_USER"
    @test _a2a_proto_task_state("completed") == "TASK_STATE_COMPLETED"
    @test _a2a_status_update_payload(Dict(
        "id" => "task-1",
        "contextId" => "ctx-1",
        "status" => Dict("state" => "TASK_STATE_WORKING", "timestamp" => "2026-04-14T00:00:00Z"),
        "metadata" => Dict("tool" => "chat"),
    ))["taskId"] == "task-1"

    cfg = _a2a_upsert_push_notification_config!(
        db,
        "task-123",
        "api-key-123",
        Dict{String,Any}(
            "id" => "cfg-1",
            "url" => "https://example.com/webhook",
            "token" => "hook-token",
            "authentication" => Dict("scheme" => "bearer", "credentials" => "secret"),
            "metadata" => Dict("channel" => "alerts"),
        ),
    )
    @test cfg["id"] == "cfg-1"
    @test cfg["taskId"] == "task-123"
    @test cfg["url"] == "https://example.com/webhook"
    @test cfg["authentication"]["scheme"] == "bearer"
    @test !haskey(cfg, "apiKey")
    @test _a2a_extract_push_config(Dict{String,Any}()) === nothing
    @test _a2a_extract_push_config(Dict("taskPushNotificationConfig" => Dict("url" => "https://example.com/push")) )["url"] == "https://example.com/push"
    @test length(_a2a_list_push_notification_configs(db; task_id="task-123")) == 1
    @test _a2a_delete_push_notification_config!(db, "cfg-1") == true
    @test isempty(_a2a_list_push_notification_configs(db; task_id="task-123"))

    if auth_headers === nothing
        @test_skip "A2A auth is enabled but no test key is configured"
    else
        send_resp = _a2a_rpc_request(
            db,
            "message/send",
            Dict(
                "message" => Dict(
                    "parts" => [
                        Dict("text" => "hello from the test bench", "mediaType" => "text/plain"),
                    ],
                ),
            ),
            headers=auth_headers,
        )
        send_payload = JSON.parse(String(send_resp.body))
        @test send_resp.status == 200
        @test haskey(send_payload, "result")
        @test haskey(send_payload["result"], "task")

        task = send_payload["result"]["task"]
        @test !haskey(task, "kind")
        @test task["status"]["state"] == "TASK_STATE_FAILED"
        @test task["history"][1]["role"] == "ROLE_USER"
        @test task["history"][2]["role"] == "ROLE_AGENT"
        @test task["status"]["message"]["role"] == "ROLE_AGENT"

        get_resp = _a2a_rpc_request(
            db,
            "tasks/get",
            Dict(
                "id" => task["id"],
                "historyLength" => 1,
            ),
            headers=auth_headers,
        )
        get_payload = JSON.parse(String(get_resp.body))
        task_get = get_payload["result"]
        @test task_get["status"]["state"] == "TASK_STATE_FAILED"
        @test length(task_get["history"]) == 1
        @test !haskey(task_get, "kind")

        stream_resp = _a2a_rpc_request(
            db,
            "message/stream",
            Dict(
                "message" => Dict(
                    "parts" => [
                        Dict("text" => "stream me", "mediaType" => "text/plain"),
                    ],
                ),
            ),
            headers=auth_headers,
        )
        stream_body = String(stream_resp.body)
        @test stream_resp.status == 200
        @test any(h -> lowercase(String(h[1])) == "content-type" && occursin("text/event-stream", lowercase(String(h[2]))), stream_resp.headers)
        @test occursin("event: task", stream_body)
        @test occursin("\"task\":", stream_body)
        @test !occursin("\"jsonrpc\"", stream_body)
    end
end
