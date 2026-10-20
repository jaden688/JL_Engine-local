Base.@kwdef struct ModulationState
    emotional_drift::Float64 = 0.0
    rhythm_momentum::Float64 = 0.0
    gait_bias::Float64 = 0.0
    behavior_blend::Float64 = 0.0
    last_sentiment::Float64 = 0.0
    attractor::Float64 = 0.5
    turn_count::Int = 0
end

mutable struct StateManager
    state::ModulationState
end

StateManager() = StateManager(ModulationState())

function reset!(manager::StateManager)
    manager.state = ModulationState()
    return manager
end

function _state_quick_sentiment(text::AbstractString)
    lowered = lowercase(text)
    positive_hits = count(token -> occursin(token, lowered), ("great", "awesome", "glad", "love", "nice", "!"))
    negative_hits = count(token -> occursin(token, lowered), ("sorry", "concern", "worry", "bad", "confused", "?"))
    return clamp((positive_hits - negative_hits) / 6.0, -1.0, 1.0)
end

function update_from_output!(manager::StateManager, output::AbstractString; rhythm_state=nothing, gait=nothing)
    sentiment = _state_quick_sentiment(output)
    variability = rhythm_state isa AbstractDict ? _float_or(get(rhythm_state, "variability", 0.0), 0.0) : rhythm_state isa RhythmState ? rhythm_state.variability : 0.0
    gait_bias = gait in ("trot", "gallop", "sprint") ? 0.05 : gait == "idle" ? -0.05 : 0.0
    drift_rate = 0.04 + variability * 0.12

    s = manager.state
    emotional_drift = clamp(s.emotional_drift * 0.9 + sentiment * drift_rate, -0.35, 0.35)
    rhythm_momentum = clamp(s.rhythm_momentum * 0.85 + (sentiment + gait_bias) * 0.25, -0.7, 0.7)
    gait_bias_val = clamp(s.gait_bias * 0.85 + gait_bias, -0.5, 0.5)
    behavior_blend = clamp(s.behavior_blend * 0.9 + sentiment * 0.2, -0.5, 0.7)
    attractor_target = 0.5 + (rhythm_momentum * 0.15) + (emotional_drift * 0.2)
    attractor = clamp(s.attractor * 0.85 + attractor_target * 0.15, 0.0, 1.0)

    manager.state = ModulationState(
        emotional_drift=emotional_drift,
        rhythm_momentum=rhythm_momentum,
        gait_bias=gait_bias_val,
        behavior_blend=behavior_blend,
        last_sentiment=sentiment,
        attractor=attractor,
        turn_count=s.turn_count + 1,
    )
    return manager
end

function advisory_payload(manager::StateManager, stability_score::Real, drift_pressure::Real)
    gating_bias = 0.0
    if stability_score < 0.25 || drift_pressure > 0.6
        gating_bias = 0.6
    elseif stability_score < 0.4 || drift_pressure > 0.4
        gating_bias = 0.3
    end

    blend_weight = 0.5 + manager.state.behavior_blend * 0.5
    return Dict{String, Any}(
        "gating_bias" => clamp(gating_bias, 0.0, 1.0),
        "blend_weight" => clamp(blend_weight, 0.0, 1.0),
        "emotional_drift" => manager.state.emotional_drift,
        "rhythm_momentum" => manager.state.rhythm_momentum,
        "gait_bias" => manager.state.gait_bias,
        "attractor" => manager.state.attractor,
    )
end

function export_snapshot(manager::StateManager)
    return Dict{String, Any}(
        "emotional_drift" => manager.state.emotional_drift,
        "rhythm_momentum" => manager.state.rhythm_momentum,
        "gait_bias" => manager.state.gait_bias,
        "behavior_blend" => manager.state.behavior_blend,
        "last_sentiment" => manager.state.last_sentiment,
        "attractor" => manager.state.attractor,
        "turn_count" => manager.state.turn_count,
    )
end
