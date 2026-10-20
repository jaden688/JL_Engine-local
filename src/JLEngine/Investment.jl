mutable struct InvestmentSystem
    level::Float64
    target::Float64
end

InvestmentSystem() = InvestmentSystem(0.0, 0.5)

function _signal_value(signals, key::Symbol, fallback::Float64=0.0)
    if signals isa AbstractDict
        return get(signals, String(key), fallback)
    end
    try
        return Float64(getproperty(signals, key))
    catch
        return fallback
    end
end

function investment_target(system::InvestmentSystem)
    return system.target
end

function update_investment!(system::InvestmentSystem, signals; momentum::Real=0.0, drift_pressure::Real=0.0)
    arousal = _signal_value(signals, :arousal, 0.0)
    memory_density = _signal_value(signals, :memory_density, 0.0)
    pace = _signal_value(signals, :pace, 0.0)

    engagement = clamp(
        0.35 * arousal +
        0.25 * memory_density +
        0.20 * pace +
        0.20 * float(momentum),
        0.0,
        1.0,
    )
    pressure_penalty = clamp(float(drift_pressure) * 0.15, 0.0, 0.35)
    level = clamp(engagement - pressure_penalty, 0.0, 1.0)
    system.level = level
    system.target = level
    return level
end

function investment_gear(level::Real)
    level_f = clamp(float(level), 0.0, 1.0)
    if level_f < 0.25
        return "low"
    elseif level_f < 0.6
        return "medium"
    elseif level_f < 0.85
        return "high"
    else
        return "max"
    end
end
