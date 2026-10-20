function _float_or(value, default::Float64)
    value isa Real && return Float64(value)
    try
        return parse(Float64, string(value))
    catch
        return default
    end
end

function _int_or(value, default::Int)
    value isa Integer && return Int(value)
    try
        return parse(Int, string(value))
    catch
        return default
    end
end

function _behavior_state_from_dict(data, fallback_number::Int)
    data isa AbstractDict || return BehaviorState(number=fallback_number)
    return BehaviorState(
        number=_int_or(get(data, "number", fallback_number), fallback_number),
        id=String(get(data, "id", "0,0")),
        name=String(get(data, "name", "Unknown")),
        expressiveness=_float_or(get(data, "expressiveness", 0.5), 0.5),
        pacing=String(get(data, "pacing", "normal")),
        tone_bias=String(get(data, "tone_bias", "neutral")),
        memory_strictness=String(get(data, "memory_strictness", "medium")),
    )
end

mutable struct BehaviorStateMachine
    states::Vector{Vector{BehaviorState}}
    trigger_mappings::Dict{String, Tuple{Int, Int}}
    rows::Int
    columns::Int
    current_row::Int
    current_col::Int
    gating_advice::Dict{String, Any}
    blend_weight::Float64
    last_blend::Union{Nothing, Dict{String, Any}}
end

function BehaviorStateMachine(config_path::AbstractString)
    config = load_json_safely(config_path)
    raw_rows = get(config, "states", Any[])
    states = Vector{Vector{BehaviorState}}()

    if raw_rows isa AbstractVector
        for (row_index, row) in enumerate(raw_rows)
            row isa AbstractVector || continue
            parsed_row = BehaviorState[]
            for (col_index, item) in enumerate(row)
                fallback_number = (row_index - 1) * length(row) + col_index
                push!(parsed_row, _behavior_state_from_dict(item, fallback_number))
            end
            isempty(parsed_row) || push!(states, parsed_row)
        end
    end

    if isempty(states)
        states = [
            [
                BehaviorState(
                    number=row * 4 + col + 1,
                    id="$(row),$(col)",
                    name="Cell $(lpad(string(row * 4 + col + 1), 2, '0'))",
                )
                for col in 0:3
            ]
            for row in 0:4
        ]
    end

    trigger_mappings = Dict{String, Tuple{Int, Int}}()
    raw_mappings = get(config, "trigger_mappings", Dict{String, Any}())
    if raw_mappings isa AbstractDict
        for (trigger, target) in raw_mappings
            coords = nothing
            if target isa AbstractVector && length(target) >= 2
                coords = (_int_or(target[1], 2), _int_or(target[2], 1))
            elseif target isa Real || target isa AbstractString
                number = _int_or(target, 10)
                coords = _coords_for_number(states, number)
            end
            coords === nothing || (trigger_mappings[String(trigger)] = coords)
        end
    end

    dims = get(config, "grid_dimensions", Dict{String, Any}())
    configured_rows = dims isa AbstractDict ? _int_or(get(dims, "rows", length(states)), length(states)) : length(states)
    configured_cols = dims isa AbstractDict ? _int_or(get(dims, "columns", length(first(states))), length(first(states))) : length(first(states))
    rows = min(configured_rows, length(states))
    cols = min(configured_cols, minimum(length.(states)))
    default_coords = _coords_for_number(states, _int_or(get(config, "default_state", 10), 10))
    default_row, default_col = default_coords === nothing ? (min(2, rows - 1), min(1, cols - 1)) : default_coords

    machine = BehaviorStateMachine(
        states,
        trigger_mappings,
        rows,
        cols,
        default_row,
        default_col,
        Dict{String, Any}("level" => "allow", "weight" => 0.0, "reason" => nothing),
        0.0,
        nothing,
    )
    _compute_blend!(machine)
    return machine
end

current_state(machine::BehaviorStateMachine) = machine.states[machine.current_row + 1][machine.current_col + 1]
current_blend(machine::BehaviorStateMachine) = machine.last_blend

function _coords_for_number(states::Vector{Vector{BehaviorState}}, number::Integer)
    for (row_index, row) in enumerate(states)
        for (col_index, state) in enumerate(row)
            state.number == Int(number) && return (row_index - 1, col_index - 1)
        end
    end
    nothing
end

function set_state_by_coords!(machine::BehaviorStateMachine, row::Integer, col::Integer)
    machine.current_row = clamp(Int(row), 0, machine.rows - 1)
    machine.current_col = clamp(Int(col), 0, machine.columns - 1)
    _compute_blend!(machine)
    return current_state(machine)
end

function set_state_by_number!(machine::BehaviorStateMachine, number::Integer)
    coords = _coords_for_number(machine.states, number)
    coords === nothing && return false
    set_state_by_coords!(machine, coords...)
    return true
end

function set_state_by_label!(machine::BehaviorStateMachine, label::AbstractString)
    target = lowercase(strip(label))
    isempty(target) && return false
    numeric_target = tryparse(Int, replace(target, r"^(?:cell|#)\s*" => ""))

    for (r, row) in enumerate(machine.states)
        for (c, state) in enumerate(row)
            if lowercase(state.name) == target ||
               lowercase(state.id) == target ||
               (numeric_target !== nothing && state.number == numeric_target)
                set_state_by_coords!(machine, r - 1, c - 1)
                return true
            end
        end
    end
    return false
end

function transition_by_trigger!(
    machine::BehaviorStateMachine,
    trigger::Union{Nothing, AbstractString},
    gait::AbstractString;
    gating_advice=nothing,
    intensity_hint=nothing,
)
    advice = _normalize_advice(gating_advice === nothing ? machine.gating_advice : gating_advice)
    if get(advice, "level", "allow") == "weak_block"
        machine.gating_advice = advice
    else
        machine.gating_advice = Dict{String, Any}("level" => "allow", "weight" => 0.0, "reason" => get(advice, "reason", nothing))
    end

    if trigger !== nothing && haskey(machine.trigger_mappings, String(trigger))
        target_row, target_col = machine.trigger_mappings[String(trigger)]
        gait_lower = lowercase(strip(gait))

        if intensity_hint isa Real
            # Signal intensity owns the row; trigger semantics select the column.
            # Five equal bands make every grid row reachable.
            target_row = clamp(floor(Int, clamp(Float64(intensity_hint), 0.0, 1.0) * machine.rows), 0, machine.rows - 1)
        else
            if gait_lower in ("trot", "gallop")
                target_row = min(machine.rows - 1, target_row + 1)
            elseif gait_lower == "sprint"
                target_row = min(machine.rows - 1, target_row + 2)
            elseif gait_lower == "idle"
                target_row = max(0, target_row - 1)
            end
        end

        if get(advice, "level", "allow") == "weak_block"
            pull = _float_or(get(advice, "weight", 0.3), 0.3)
            target_row = round(Int, target_row * (1 - pull) + 2 * pull)
        end

        if Bool(get(advice, "safety", false))
            target_row = 1
            target_col = 0
        end

        set_state_by_coords!(machine, target_row, target_col)
    else
        set_state_by_coords!(machine, 2, 1)
    end

    machine.blend_weight = _float_or(get(advice, "weight", 0.0), 0.0)
    _compute_blend!(machine)
    return current_state(machine)
end

function _normalize_advice(advice)
    advice isa AbstractDict || return Dict{String, Any}("level" => "allow", "weight" => 0.0, "safety" => false, "reason" => nothing)

    level = lowercase(String(get(advice, "level", "allow")))
    level == "block" && (level = "weak_block")
    safety = level == "safety_block" || Bool(get(advice, "safety", false))
    weight = clamp(_float_or(get(advice, "weight", 0.0), 0.0), 0.0, 1.0)

    return Dict{String, Any}(
        "level" => level,
        "weight" => weight,
        "safety" => safety,
        "reason" => get(advice, "reason", nothing),
    )
end

function _state_summary(state::BehaviorState)
    return Dict{String, Any}("number" => state.number, "id" => state.id, "name" => state.name)
end

function _compute_blend!(machine::BehaviorStateMachine)
    primary = current_state(machine)
    stabilizer = machine.states[3][2]
    weight = clamp(machine.blend_weight, 0.0, 1.0)

    if weight <= 0.05 || (primary.id == stabilizer.id && primary.name == stabilizer.name)
        machine.last_blend = Dict{String, Any}(
            "primary" => _state_summary(primary),
            "secondary" => nothing,
            "weights" => (1.0, 0.0),
        )
        return machine.last_blend
    end

    secondary = machine.current_col > 0 ? machine.states[machine.current_row + 1][machine.current_col] : stabilizer
    machine.last_blend = Dict{String, Any}(
        "primary" => _state_summary(primary),
        "secondary" => _state_summary(secondary),
        "weights" => (round(1.0 - weight; digits=2), round(weight; digits=2)),
    )
    return machine.last_blend
end
