using Test
using DataFrames
using SQLite
using HTTP

isdefined(Main, :_a2a_public_url) || include(joinpath(@__DIR__, "..", "a2a_server.jl"))

@testset "A2A billing" begin
    db = SQLite.DB(":memory:")
    _billing_init_db!(db)

    @test _a2a_auth_scheme() == (_a2a_public_mode() ? "none" : "bearer")

    status = _a2a_billing_status_payload(db, "")
    @test haskey(status, "billing_enforced")
    @test status["auth_scheme"] == _a2a_auth_scheme()

    created = _a2a_create_key_payload(db, Dict{String,Any}(
        "create_checkout" => false,
        "label" => "Launch customer",
        "plan" => "starter",
    ))
    @test length(created["api_key"]) >= 16
    @test created["account"]["label"] == "Launch customer"

    updated = _a2a_update_key_payload(db, Dict{String,Any}(
        "api_key" => created["api_key"],
        "subscription_status" => "active",
        "notes" => "paid",
    ))
    @test updated["account"]["subscription_status"] == "active"
    @test updated["account"]["notes"] == "paid"
end

@testset "A2A public listener requires credentials" begin
    withenv("A2A_API_KEY" => "", "A2A_ADMIN_KEY" => "") do
        @test isnothing(_a2a_validate_public_bindings!("127.0.0.1", "localhost"))
        @test_throws ErrorException _a2a_validate_public_bindings!("0.0.0.0", "127.0.0.1")
        @test_throws ErrorException _a2a_validate_public_bindings!("127.0.0.1", "::")
    end

    withenv("A2A_API_KEY" => "test-key", "A2A_ADMIN_KEY" => "") do
        @test isnothing(_a2a_validate_public_bindings!("0.0.0.0", "127.0.0.1"))
    end
end
