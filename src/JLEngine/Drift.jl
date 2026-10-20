function _clamp_alignment(value::Real)
    return max(0.0, min(1.0, Float64(value)))
end

struct DriftPressureSystem end

function calculate(::DriftPressureSystem, signals::DriftPressureInput)
    pressure = 1.0 - (
        0.30 * _clamp_alignment(signals.agent_alignment_score) +
        0.25 * _clamp_alignment(signals.behavior_grid_alignment_score) +
        0.20 * _clamp_alignment(signals.safety_alignment_score) +
        0.15 * _clamp_alignment(signals.memory_alignment_score) +
        0.10 * _clamp_alignment(signals.conversational_coherence_score)
    )
    return clamp(pressure, 0.0, 1.0)
end

function get_response_action(::DriftPressureSystem, pressure::Real)
    p = clamp(Float64(pressure), 0.0, 1.0)
    if p < 0.10
        return DriftResponse(p, "Nominal", 0.0, nothing, nothing, nothing, false)
    elseif p < 0.50
        return DriftResponse(p, "Soft Drift", -0.05, nothing, nothing, nothing, true)
    elseif p < 0.75
        return DriftResponse(
            p,
            "Moderate Drift",
            -0.10,
            nothing,
            nothing,
            "FIRM: Treat this like a growing drift fluctuation; slow down and re-check alignment.",
            false,
        )
    end

    return DriftResponse(
        p,
        "Hard Drift",
        -0.20,
        "lockstep",
        "strict",
        "HARD_LOCK: Containment protocols engaged. This is your safety line, not a suggestion.",
        false,
    )
end
