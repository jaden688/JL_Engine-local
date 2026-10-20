const APERTURE_MODIFIERS = Dict(
    "CLOSED" => Dict("temperature" => 0.10, "top_p" => 0.20, "agent_amplitude" => 0.05, "creativity_bias" => 0.05, "expressiveness" => 0.06),
    "GUARDED" => Dict("temperature" => 0.25, "top_p" => 0.45, "agent_amplitude" => 0.20, "creativity_bias" => 0.18, "expressiveness" => 0.22),
    "BALANCED" => Dict("temperature" => 0.45, "top_p" => 0.70, "agent_amplitude" => 0.45, "creativity_bias" => 0.45, "expressiveness" => 0.50),
    "OPEN" => Dict("temperature" => 0.65, "top_p" => 0.85, "agent_amplitude" => 0.70, "creativity_bias" => 0.75, "expressiveness" => 0.78),
    "WIDE_OPEN" => Dict("temperature" => 0.85, "top_p" => 0.95, "agent_amplitude" => 0.95, "creativity_bias" => 0.98, "expressiveness" => 1.00),
)

mutable struct EmotionalAperture
    drive_type::String
    current_emotion::Union{Nothing, String}
    current_emotion_meta::Union{Nothing, Dict{String, Any}}
    agent_state::Union{Nothing, Dict{String, Any}}
    emotion_palette::Vector{Dict{String, Any}}
    focus_level::Float64
    overload_level::Float64
    drift_bias::Float64
    recent_sentiment::Float64
    last_state::Dict{String, Any}
end

function EmotionalAperture(; drive_type::AbstractString="spur", agent_state=nothing)
    return EmotionalAperture(
        String(drive_type),
        nothing,
        nothing,
        agent_state isa Dict{String, Any} ? agent_state : agent_state isa AbstractDict ? Dict{String, Any}(string(key) => value for (key, value) in pairs(agent_state)) : nothing,
        Dict{String, Any}[],
        0.0,
        0.0,
        0.0,
        0.0,
        _build_state(0.25, "GUARDED", Dict{String, Any}(APERTURE_MODIFIERS["GUARDED"]), 0.0, 0.0, nothing, nothing, 0.0),
    )
end

function set_drive_type!(aperture::EmotionalAperture, drive_type::AbstractString)
    aperture.drive_type = String(drive_type)
    return aperture
end

function set_emotion_palette!(aperture::EmotionalAperture, palette)
    if !(palette isa AbstractVector)
        aperture.emotion_palette = Dict{String, Any}[]
        aperture.current_emotion = nothing
        aperture.current_emotion_meta = nothing
        _write_agent_emotion!(aperture, nothing, nothing)
        return aperture
    end

    aperture.emotion_palette = [Dict{String, Any}(string(key) => value for (key, value) in pairs(entry)) for entry in palette if entry isa AbstractDict]
    return aperture
end

function set_agent_state!(aperture::EmotionalAperture, agent_state)
    aperture.agent_state = agent_state isa Dict{String, Any} ? agent_state : agent_state isa AbstractDict ? Dict{String, Any}(string(key) => value for (key, value) in pairs(agent_state)) : nothing
    return aperture
end

function reset!(aperture::EmotionalAperture)
    aperture.current_emotion = nothing
    aperture.current_emotion_meta = nothing
    aperture.focus_level = 0.0
    aperture.overload_level = 0.0
    aperture.drift_bias = 0.0
    aperture.recent_sentiment = 0.0
    aperture.last_state = _build_state(0.25, "GUARDED", Dict{String, Any}(APERTURE_MODIFIERS["GUARDED"]), 0.0, 0.0, nothing, nothing, 0.0)
    _write_agent_emotion!(aperture, nothing, nothing)
    return aperture
end

get_state(aperture::EmotionalAperture) = Dict{String, Any}(aperture.last_state)
get_focus_level(aperture::EmotionalAperture) = aperture.focus_level
get_overload_level(aperture::EmotionalAperture) = aperture.overload_level

function update_from_signals!(
    aperture::EmotionalAperture;
    behavior_state=nothing,
    gait::AbstractString="walk",
    rhythm::AbstractString="flop",
    agent_vividness::Real=0.6,
    safety_mode::Bool=true,
    drift_pressure::Real=0.0,
    drift_bias::Real=0.0,
    user_sentiment::Real=0.0,
    conversation_pacing::Real=0.5,
    memory_density::Real=0.0,
    aperture_bias::Real=0.0,
)
    behavior_intensity = behavior_state isa BehaviorState ? behavior_state.expressiveness : 0.5
    signal_payload = Dict{String, Any}(
        "behavior_intensity" => behavior_intensity,
        "agent_vividness" => Float64(agent_vividness),
        "safety_mode" => safety_mode,
        "drift_pressure" => Float64(drift_pressure),
        "drift_bias" => Float64(drift_bias),
        "user_sentiment" => Float64(user_sentiment),
        "conversation_pacing" => Float64(conversation_pacing),
        "memory_density" => Float64(memory_density),
        "gait_range" => _map_gait_to_range(gait),
        "rhythm_variability" => _map_rhythm_to_variability(rhythm),
        "aperture_bias" => Float64(aperture_bias),
    )

    computed = _compute(aperture, signal_payload)
    aperture.focus_level, aperture.overload_level = _derive_focus_overload(signal_payload)
    aperture.last_state = _build_state(
        get(computed, "score", 0.0),
        String(get(computed, "mode", "GUARDED")),
        Dict{String, Any}(get(computed, "modifiers", APERTURE_MODIFIERS["GUARDED"])),
        aperture.focus_level,
        aperture.overload_level,
        aperture.current_emotion,
        aperture.current_emotion_meta,
        aperture.drift_bias,
    )

    selected_emotion = _select_emotion(aperture, aperture.last_state["score"], signal_payload, behavior_state)
    _apply_selected_emotion!(aperture, selected_emotion)
    return Dict{String, Any}(aperture.last_state)
end

function update_from_signal!(aperture::EmotionalAperture; emotion=nothing, focus_delta::Real=0.0, overload_delta::Real=0.0)
    modifiers = gear_modifiers(aperture.drive_type)
    emotion !== nothing && (aperture.current_emotion = String(emotion))

    scaled_focus = Float64(focus_delta) * modifiers.reaction_speed
    scaled_overload = Float64(overload_delta) * modifiers.reaction_speed
    inertia = modifiers.mode_inertia
    inv_inertia = 1.0 - inertia

    aperture.focus_level = clamp(aperture.focus_level * inertia + scaled_focus * inv_inertia, 0.0, 1.0)
    aperture.overload_level = clamp(aperture.overload_level * inertia + scaled_overload * inv_inertia, 0.0, 1.0)
    aperture.last_state["focus_level"] = aperture.focus_level
    aperture.last_state["overload_level"] = aperture.overload_level
    aperture.last_state["emotion"] = aperture.current_emotion
    aperture.last_state["emotion_meta"] = aperture.current_emotion_meta
    _write_agent_emotion!(aperture, aperture.current_emotion, aperture.current_emotion_meta)
    return Dict{String, Any}(aperture.last_state)
end

function apply_output_feedback!(aperture::EmotionalAperture, output_text::AbstractString; rhythm_state=nothing, gait=nothing)
    sentiment = _quick_sentiment(output_text)
    variability = rhythm_state isa AbstractDict ? _float_or(get(rhythm_state, "variability", 0.0), 0.0) : 0.0
    gait_push = 0.0

    if gait isa AbstractString
        gait_lower = lowercase(gait)
        gait_lower in ("trot", "gallop", "sprint") && (gait_push = 0.05)
        gait_lower == "idle" && (gait_push = -0.05)
    end

    drift_rate = 0.015 + variability * 0.08 + abs(gait_push) * 0.5
    aperture.drift_bias = clamp(aperture.drift_bias * 0.9 + sentiment * drift_rate, -0.25, 0.25)
    aperture.recent_sentiment = sentiment
    aperture.focus_level = clamp(aperture.focus_level + max(0.0, sentiment) * 0.05, 0.0, 1.0)
    aperture.overload_level = clamp(aperture.overload_level + max(0.0, -sentiment) * 0.05, 0.0, 1.0)
    aperture.last_state["drift_bias"] = aperture.drift_bias
    return aperture
end

function inject_drift_bias!(aperture::EmotionalAperture, bias::Real)
    aperture.drift_bias = clamp(Float64(bias), -0.35, 0.35)
    return aperture
end

function _compute(aperture::EmotionalAperture, signals::AbstractDict)
    required = (
        "behavior_intensity",
        "agent_vividness",
        "safety_mode",
        "drift_pressure",
        "user_sentiment",
        "conversation_pacing",
        "memory_density",
        "gait_range",
        "rhythm_variability",
    )
    any(key -> get(signals, key, nothing) === nothing, required) && return Dict{String, Any}(
        "score" => 0.25,
        "mode" => "GUARDED",
        "modifiers" => APERTURE_MODIFIERS["GUARDED"],
    )

    score = (
        _float_or(get(signals, "behavior_intensity", 0.5), 0.5) * 0.18 +
        _float_or(get(signals, "agent_vividness", 0.5), 0.5) * 0.16 +
        _float_or(get(signals, "user_sentiment", 0.0), 0.0) * 0.22 +
        _float_or(get(signals, "conversation_pacing", 0.5), 0.5) * 0.08 +
        _float_or(get(signals, "memory_density", 0.0), 0.0) * 0.12 +
        _float_or(get(signals, "gait_range", 0.3), 0.3) * 0.06 +
        _float_or(get(signals, "rhythm_variability", 0.5), 0.5) * 0.08 -
        _float_or(get(signals, "drift_pressure", 0.0), 0.0) * 0.20
    )

    score += _float_or(get(signals, "aperture_bias", 0.0), 0.0)
    score += _float_or(get(signals, "drift_bias", 0.0), 0.0)
    score += aperture.drift_bias
    score = clamp(score, 0.0, 1.0)

    safety_mode = Bool(get(signals, "safety_mode", true))
    # Safety mode is a brake for actual drift, not a permanent ceiling on
    # personality. Nominal turns may use the full aperture range.
    safety_mode && _float_or(get(signals, "drift_pressure", 0.0), 0.0) >= 0.50 &&
        (score = min(score, 0.60))

    mode = _mode_from_score(score)
    return Dict{String, Any}(
        "score" => score,
        "mode" => mode,
        "modifiers" => APERTURE_MODIFIERS[mode],
    )
end

function _derive_focus_overload(signals::AbstractDict)
    focus = (
        _float_or(get(signals, "behavior_intensity", 0.5), 0.5) * 0.45 +
        (1.0 - _float_or(get(signals, "rhythm_variability", 0.5), 0.5)) * 0.20 +
        max(0.0, _float_or(get(signals, "conversation_pacing", 0.5), 0.5) - 0.4) * 0.15 +
        max(0.0, _float_or(get(signals, "agent_vividness", 0.5), 0.5) - 0.3) * 0.10 +
        max(0.0, _float_or(get(signals, "user_sentiment", 0.0), 0.0)) * 0.10 -
        _float_or(get(signals, "drift_pressure", 0.0), 0.0) * 0.20
    )

    overload = (
        _float_or(get(signals, "drift_pressure", 0.0), 0.0) * 0.35 +
        _float_or(get(signals, "memory_density", 0.0), 0.0) * 0.25 +
        _float_or(get(signals, "gait_range", 0.3), 0.3) * 0.10 +
        _float_or(get(signals, "rhythm_variability", 0.5), 0.5) * 0.10 +
        max(0.0, -_float_or(get(signals, "user_sentiment", 0.0), 0.0)) * 0.12 +
        max(0.0, 0.5 - _float_or(get(signals, "conversation_pacing", 0.5), 0.5)) * 0.08
    )

    return clamp(focus, 0.0, 1.0), clamp(overload, 0.0, 1.0)
end

function _quick_sentiment(text::AbstractString)
    lowered = lowercase(text)
    positives = count(token -> occursin(token, lowered), ("great", "glad", "yes", "sure", "love", "!"))
    negatives = count(token -> occursin(token, lowered), ("sorry", "no", "cannot", "frustrated", "confused", "?"))
    return clamp((positives - negatives) / 6.0, -1.0, 1.0)
end

function _build_state(score, mode, modifiers, focus_level, overload_level, emotion, emotion_meta, drift_bias)
    return Dict{String, Any}(
        "score" => Float64(score),
        "mode" => String(mode),
        "modifiers" => modifiers,
        "temp" => _float_or(get(modifiers, "temperature", 0.45), 0.45),
        "top_p" => _float_or(get(modifiers, "top_p", 0.70), 0.70),
        "focus_level" => Float64(focus_level),
        "overload_level" => Float64(overload_level),
        "emotion" => emotion,
        "emotion_meta" => emotion_meta,
        "drift_bias" => Float64(drift_bias),
    )
end

function _mode_from_score(score::Real)
    score <= 0.12 && return "CLOSED"
    score <= 0.28 && return "GUARDED"
    score <= 0.55 && return "BALANCED"
    score <= 0.78 && return "OPEN"
    return "WIDE_OPEN"
end

function _map_gait_to_range(gait::AbstractString)
    gait_lower = lowercase(gait)
    if gait_lower == "idle"
        return 0.1
    elseif gait_lower == "trot"
        return 0.55
    elseif gait_lower == "gallop"
        return 0.75
    elseif gait_lower == "sprint"
        return 0.9
    end
    return 0.3
end

function _map_rhythm_to_variability(rhythm::AbstractString)
    rhythm_lower = lowercase(rhythm)
    if rhythm_lower == "flop"
        return 0.2
    elseif rhythm_lower == "flip"
        return 0.35
    elseif rhythm_lower == "twitch"
        return 0.55
    elseif rhythm_lower == "cascade"
        return 0.45
    elseif rhythm_lower == "stutter"
        return 0.3
    elseif rhythm_lower == "burst"
        return 0.65
    end
    return 0.4
end

function _select_emotion(aperture::EmotionalAperture, score::Real, signals::AbstractDict, behavior_state)
    isempty(aperture.emotion_palette) && return nothing
    sentiment = _float_or(get(signals, "user_sentiment", 0.0), 0.0)
    behavior_intensity = get(signals, "behavior_intensity", nothing)
    behavior_intensity === nothing && behavior_state isa BehaviorState && (behavior_intensity = behavior_state.expressiveness)
    behavior_intensity === nothing && (behavior_intensity = 0.5)
    best_entry = nothing
    best_score = -1.0

    for entry in aperture.emotion_palette
        range_values = get(entry, "score_range", Any[0.0, 1.0])
        if !(range_values isa AbstractVector) || length(range_values) < 2
            range_values = Any[0.0, 1.0]
        end

        min_score = _float_or(range_values[1], 0.0)
        max_score = _float_or(range_values[2], 1.0)
        min_score > max_score && ((min_score, max_score) = (max_score, min_score))
        span = max(0.1, max_score - min_score)
        center = min_score + span / 2.0
        score_fit = max(0.0, 1.0 - abs(Float64(score) - center) / (span / 2.0))

        target_intensity = _float_or(get(entry, "intensity", 0.5), 0.5)
        intensity_fit = max(0.0, 1.0 - abs(_float_or(behavior_intensity, 0.5) - target_intensity))

        sentiment_pref = lowercase(String(get(entry, "sentiment", "any")))
        sentiment_fit = 1.0
        if sentiment_pref != "any"
            if sentiment_pref == "positive"
                sentiment_fit = sentiment >= 0.1 ? 1.0 : 0.55
            elseif sentiment_pref == "negative"
                sentiment_fit = sentiment <= -0.1 ? 1.0 : 0.55
            elseif sentiment_pref == "neutral"
                sentiment_fit = abs(sentiment) < 0.25 ? 1.0 : 0.55
            end
        end

        combined = (score_fit * 0.5) + (intensity_fit * 0.3) + (sentiment_fit * 0.2)
        if combined > best_score
            best_score = combined
            best_entry = entry
        end
    end

    return best_entry
end

function _apply_selected_emotion!(aperture::EmotionalAperture, entry)
    if entry === nothing
        aperture.current_emotion = nothing
        aperture.current_emotion_meta = nothing
        aperture.last_state["emotion"] = nothing
        aperture.last_state["emotion_meta"] = nothing
        _write_agent_emotion!(aperture, nothing, nothing)
        return aperture
    end

    label = get(entry, "label", get(entry, "id", nothing))
    meta = Dict{String, Any}(
        "id" => get(entry, "id", nothing),
        "label" => label,
        "style" => get(entry, "style", nothing),
        "sampling_bias" => get(entry, "sampling_bias", nothing),
        "intensity" => get(entry, "intensity", nothing),
        "sentiment" => get(entry, "sentiment", nothing),
        "score_range" => get(entry, "score_range", nothing),
    )
    aperture.current_emotion = label === nothing ? nothing : String(label)
    aperture.current_emotion_meta = meta
    aperture.last_state["emotion"] = aperture.current_emotion
    aperture.last_state["emotion_meta"] = meta
    _write_agent_emotion!(aperture, aperture.current_emotion, meta)
    return aperture
end

function _write_agent_emotion!(aperture::EmotionalAperture, label, meta)
    aperture.agent_state isa AbstractDict || return
    aperture.agent_state["emotion"] = label
    aperture.agent_state["emotion_meta"] = meta
end
