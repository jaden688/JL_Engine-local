const DEFAULT_GEAR = "spur"

struct GearModifiers
    reaction_speed::Float64
    mode_inertia::Float64
    multi_mode::Bool
end

function gear_modifiers(gear::AbstractString=DEFAULT_GEAR)
    key = isempty(gear) ? DEFAULT_GEAR : lowercase(gear)
    if key == "worm"
        return GearModifiers(0.6, 0.78, false)
    elseif key == "cvt"
        return GearModifiers(0.9, 0.55, true)
    elseif key == "planetary"
        return GearModifiers(1.0, 0.5, true)
    end
    return GearModifiers(0.8, 0.65, false)
end

"""
    EngineConfig

Authoritative typed configuration for JLEngine runtime, provider routing,
cognitive lattice, and persistence.
"""
Base.@kwdef struct EngineConfig
    # ── 1. Model Roles & Assignments ─────────────────────────────────
    current_model::String                  = "deepseek/deepseek-v4-flash"
    brain_model::String                    = "deepseek/deepseek-v4-flash"
    tool_model::String                     = "deepseek/deepseek-v4-flash"
    reviewer_model::String                 = "deepseek/deepseek-v4-flash"
    fallback_models::Vector{String}        = String[
        "anthropic/claude-3.7-sonnet",
        "openai/gpt-4o",
        "meta-llama/llama-3.3-70b-instruct"
    ]

    # ── 2. Provider Settings ─────────────────────────────────────────
    active_provider::String                = "openrouter"
    openrouter_endpoint::String            = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_timeout::Int                = 120
    ollama_endpoint::String                = "http://127.0.0.1:11434"
    gemini_endpoint::String                = "https://generativelanguage.googleapis.com/v1beta"

    # ── 3. Sampling & Generation Parameters ──────────────────────────
    default_temperature::Float64           = 0.7
    default_top_p::Float64                 = 0.95
    max_tokens::Int                        = 4096
    reasoning_effort::String               = "medium"  # "none", "low", "medium", "high"

    # ── 4. Network & Runtime Settings ────────────────────────────────
    host::String                           = "127.0.0.1"
    port::Int                              = 8081
    debug_mode::Bool                       = false
    log_level::String                      = "info"    # "debug", "info", "warn", "error"

    # ── 5. Engine File & Legacy Paths (Backward Compatibility) ───────
    root_dir::String                       = pwd()
    master_file::String                    = "JLframe_Engine_Framework.json"
    behavior_states_file::String           = "behavior_states.json"
    signal_lexicon_file::String            = "signal_lexicon.json"
    mpf_registry_file::String              = joinpath("agents", "Agents.mpf.json")
    agents_dir::String                     = "agents"
    safety_on::Bool                        = true
    default_agent_name::String             = "SparkByte"
    history_length::Int                    = 20
end

Base.@kwdef struct MPFProfile
    agent_file::String
    default_memory_mode::Union{Nothing, String} = nothing
    default_backend_id::Union{Nothing, String} = nothing
    drive_type::Union{Nothing, String} = nothing
    tags::Vector{String} = String[]
end

Base.@kwdef struct BehaviorState
    number::Int = 1
    id::String = "0,0"
    name::String = "Unknown"
    expressiveness::Float64 = 0.5
    pacing::String = "normal"
    tone_bias::String = "neutral"
    memory_strictness::String = "medium"
end

Base.string(state::BehaviorState) = "[#$(state.number) / $(state.id)] $(state.name)"

function instructions(state::BehaviorState)
    return join(
        [
            "Current Behavior Cell: #$(state.number) ($(state.id)).",
            "- Diagnostic Label: $(state.name)",
            "- Expressiveness Level: $(round(state.expressiveness * 100; digits=1))%",
            "- Conversational Pacing: $(state.pacing)",
            "- Dominant Tone: $(state.tone_bias)",
            "- Adherence to Memory: $(state.memory_strictness)",
        ],
        "\n",
    )
end

struct TurnSignals
    sentiment::Float64
    arousal::Float64
    directive::Bool
    confusion::Float64
    pace::Float64
    memory_density::Float64
    playfulness::Float64
    distress::Float64
end

# Compatibility for extensions that still construct the original six-signal shape.
TurnSignals(sentiment, arousal, directive, confusion, pace, memory_density) =
    TurnSignals(sentiment, arousal, directive, confusion, pace, memory_density, 0.0, 0.0)

struct RhythmState
    mode::String
    index::Float64
    variability::Float64
    momentum::Float64
    attractor::String
    modifiers::Dict{String, Float64}
    debug::Dict{String, Any}
end

Base.@kwdef struct DriftPressureInput
    agent_alignment_score::Float64 = 1.0
    behavior_grid_alignment_score::Float64 = 1.0
    safety_alignment_score::Float64 = 1.0
    memory_alignment_score::Float64 = 1.0
    conversational_coherence_score::Float64 = 1.0
end

struct DriftResponse
    pressure::Float64
    action_level::String
    temperature_delta::Float64
    force_gait::Union{Nothing, String}
    force_rhythm::Union{Nothing, String}
    supervisor_warning::Union{Nothing, String}
    reinforce_gait::Bool
end
