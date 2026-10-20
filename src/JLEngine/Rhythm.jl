const RHYTHM_MODES = Dict(
    "flip" => Dict(
        "index" => 0.25,
        "modifiers" => Dict(
            "pace_multiplier" => 1.0,
            "punctuation_bias" => 0.0,
            "energy_bias" => 0.1,
            "stutter_likelihood" => 0.0,
            "burst_likelihood" => 0.0,
        ),
    ),
    "flop" => Dict(
        "index" => 0.45,
        "modifiers" => Dict(
            "pace_multiplier" => 0.9,
            "punctuation_bias" => -0.05,
            "energy_bias" => -0.05,
            "stutter_likelihood" => 0.0,
            "burst_likelihood" => 0.0,
        ),
    ),
    "trot" => Dict(
        "index" => 0.75,
        "modifiers" => Dict(
            "pace_multiplier" => 1.15,
            "punctuation_bias" => 0.1,
            "energy_bias" => 0.2,
            "stutter_likelihood" => 0.0,
            "burst_likelihood" => 0.0,
        ),
    ),
)

const TRIGGER_TO_RHYTHM = Dict(
    "user_hyped" => "trot",
    "user_joking" => "flip",
    "user_frustrated" => "flop",
    "user_confused" => "flop",
    "user_overwhelmed" => "flop",
    "user_anxious" => "flop",
    "user_distressed" => "flop",
    "user_serious_or_tired" => "flop",
    "user_engaged" => "flip",
    "user_directive" => "flip",
    "neutral" => "flip",
)

mutable struct RhythmEngine
    default_mode::String
    momentum::Float64
    attractor::String
    last_state::Union{Nothing, Dict{String, Any}}
end

function RhythmEngine(default_mode::AbstractString="flip")
    normalized = _normalize_mode(default_mode)
    return RhythmEngine(normalized, 0.0, normalized, nothing)
end

function compute(
    engine::RhythmEngine;
    last_mode::Union{Nothing, AbstractString}=nothing,
    trigger::AbstractString="neutral",
    gait::AbstractString="walk",
    behavior_state::Union{Nothing, BehaviorState}=nothing,
    drift_pressure::Real=0.0,
    safety_on::Bool=true,
    modulation_hint=nothing,
)
    last_mode_norm = _normalize_mode(last_mode === nothing ? engine.default_mode : String(last_mode))
    trigger_norm = lowercase(strip(trigger))
    gait_norm = lowercase(strip(gait))

    base_mode = _base_mode_from_trigger(trigger_norm)
    mode_after_behavior = _apply_behavior_bias(base_mode, behavior_state)
    mode_after_gait = _apply_gait_bias(mode_after_behavior, gait_norm)
    mode_after_drift = _apply_drift_correction(mode_after_gait, Float64(drift_pressure))
    mode_after_safety = _apply_safety_rules(mode_after_drift, trigger_norm, safety_on)

    _update_internal_momentum!(engine, last_mode_norm, mode_after_safety, modulation_hint)
    final_mode = _apply_attractor(engine, mode_after_safety, modulation_hint)
    mode_info = RHYTHM_MODES[final_mode]
    current_index = _float_or(mode_info["index"], 0.25)
    last_index = _float_or(RHYTHM_MODES[last_mode_norm]["index"], 0.25)
    variability = abs(current_index - last_index) + abs(engine.momentum) * 0.15
    modifiers = Dict{String, Float64}(String(key) => _float_or(value, 0.0) for (key, value) in pairs(mode_info["modifiers"]))

    state = RhythmState(
        final_mode,
        current_index,
        variability,
        engine.momentum,
        engine.attractor,
        modifiers,
        Dict{String, Any}(
            "input" => Dict{String, Any}(
                "last_mode" => last_mode,
                "trigger" => trigger,
                "gait" => gait,
                "drift_pressure" => drift_pressure,
                "safety_on" => safety_on,
                "behavior_state" => behavior_state === nothing ? nothing : behavior_state.number,
                "modulation_hint" => modulation_hint,
            ),
            "stages" => Dict{String, Any}(
                "base_mode" => base_mode,
                "after_behavior" => mode_after_behavior,
                "after_gait" => mode_after_gait,
                "after_drift" => mode_after_drift,
                "after_safety" => mode_after_safety,
            ),
        ),
    )

    engine.last_state = Dict{String, Any}(
        "mode" => state.mode,
        "index" => state.index,
        "variability" => state.variability,
        "momentum" => state.momentum,
        "attractor" => state.attractor,
        "modifiers" => state.modifiers,
        "debug" => state.debug,
    )
    return state
end

function _normalize_mode(mode::AbstractString)
    m = lowercase(strip(mode))
    haskey(RHYTHM_MODES, m) && return m
    occursin("flip", m) && return "flip"
    occursin("flop", m) && return "flop"
    occursin("trot", m) && return "trot"
    occursin("twitch", m) && return "trot"
    occursin("burst", m) && return "trot"
    occursin("cascade", m) && return "flip"
    occursin("stutter", m) && return "flop"
    return "flip"
end

_base_mode_from_trigger(trigger::AbstractString) = _normalize_mode(get(TRIGGER_TO_RHYTHM, trigger, "flip"))

function _apply_behavior_bias(current_mode::AbstractString, behavior_state::Union{Nothing, BehaviorState})
    behavior_state === nothing && return String(current_mode)
    row = max(0, (behavior_state.number - 1) ÷ 4)
    row >= 4 && return "trot"
    row <= 1 && current_mode == "trot" && return "flip"
    return String(current_mode)
end

function _apply_gait_bias(current_mode::AbstractString, gait::AbstractString)
    gait == "idle" && current_mode == "trot" && return "flop"
    gait in ("trot", "sprint") && return "trot"
    return String(current_mode)
end

function _apply_drift_correction(current_mode::AbstractString, drift_pressure::Float64)
    d = clamp(drift_pressure, 0.0, 1.0)
    d >= 0.75 && return "flop"
    d >= 0.50 && return "flip"
    return String(current_mode)
end

function _apply_safety_rules(current_mode::AbstractString, trigger::AbstractString, safety_on::Bool)
    !safety_on && return _normalize_mode(current_mode)
    mode = _normalize_mode(current_mode)
    trigger in ("user_anxious", "user_distressed", "user_overwhelmed") && mode == "trot" && (mode = "flop")
    trigger in ("user_distressed", "user_overwhelmed") && (mode = "flop")
    return mode
end

function _update_internal_momentum!(engine::RhythmEngine, last_mode::AbstractString, new_mode::AbstractString, hint)
    last_idx = _float_or(RHYTHM_MODES[last_mode]["index"], 0.25)
    new_idx = _float_or(RHYTHM_MODES[new_mode]["index"], 0.25)
    delta = new_idx - last_idx
    engine.momentum = clamp(engine.momentum * 0.82 + delta * 0.4, -1.0, 1.0)

    if hint isa AbstractDict
        engine.momentum = clamp(engine.momentum + _float_or(get(hint, "rhythm_momentum", 0.0), 0.0) * 0.25, -1.0, 1.0)
        attractor_hint = get(hint, "attractor", nothing)
        if attractor_hint isa Real
            engine.attractor = attractor_hint > 0.6 ? "trot" : attractor_hint < 0.3 ? "flop" : "flip"
        end
    end

    abs(engine.momentum) < 0.12 && (engine.attractor = _normalize_mode(new_mode))
    return engine
end

function _apply_attractor(engine::RhythmEngine, candidate_mode::AbstractString, hint)
    mode = _normalize_mode(candidate_mode)
    if hint isa AbstractDict && abs(_float_or(get(hint, "gating_bias", 0.0), 0.0)) > 0.6
        return _normalize_mode(engine.attractor)
    end
    engine.momentum > 0.25 && mode == "flip" && return "trot"
    engine.momentum < -0.25 && mode == "trot" && return "flip"
    return mode
end
