mutable struct HybridMemorySystem
    shared::Dict{String, Any}
    agent_store::Dict{String, Dict{String, Any}}
end

function HybridMemorySystem()
    return HybridMemorySystem(
        Dict{String, Any}(
            "last_active_agent" => nothing,
            "recent_events" => Any[],
            "engine_flags" => Dict{String, Any}(),
            "user_profile" => Dict{String, Any}(),
            "breadcrumbs" => Any[],
        ),
        Dict{String, Dict{String, Any}}(),
    )
end

function _normalize_intent(value)
    value === nothing && return "general"
    normalized = lowercase(strip(String(value)))
    return isempty(normalized) ? "general" : normalized
end

function _ensure_agent!(memory::HybridMemorySystem, agent_id::AbstractString)
    haskey(memory.agent_store, agent_id) && return memory.agent_store[agent_id]
    memory.agent_store[agent_id] = Dict{String, Any}(
        "recent_interactions" => Any[],
        "mood" => "neutral",
        "notes" => Dict{String, Any}(),
        "dynamic_state" => Dict{String, Any}(),
    )
    return memory.agent_store[agent_id]
end

function get_context(memory::HybridMemorySystem, agent_id::AbstractString)
    agent_memory = _ensure_agent!(memory, agent_id)
    return Dict{String, Any}(
        "shared_memory" => memory.shared,
        "agent_memory" => agent_memory,
    )
end

function note_event!(memory::HybridMemorySystem, agent_id::AbstractString, event_type::AbstractString, payload::Union{Nothing, AbstractDict}=nothing)
    _ensure_agent!(memory, agent_id)
    events = memory.shared["recent_events"]
    push!(events, Dict{String, Any}("agent" => String(agent_id), "event_type" => String(event_type), "payload" => payload === nothing ? Dict{String, Any}() : Dict{String, Any}(string(key) => value for (key, value) in pairs(payload))))
    length(events) > 32 && deleteat!(events, 1:(length(events) - 32))
    return memory
end

function add_breadcrumb!(memory::HybridMemorySystem, agent_id::AbstractString, intent, kind::AbstractString, payload::Union{Nothing, AbstractDict}=nothing)
    _ensure_agent!(memory, agent_id)
    breadcrumbs = memory.shared["breadcrumbs"]
    push!(breadcrumbs, Dict{String, Any}(
        "agent" => String(agent_id),
        "intent" => _normalize_intent(intent),
        "kind" => String(kind),
        "payload" => payload === nothing ? Dict{String, Any}() : Dict{String, Any}(string(key) => value for (key, value) in pairs(payload)),
    ))
    length(breadcrumbs) > 200 && deleteat!(breadcrumbs, 1:(length(breadcrumbs) - 200))
    return memory
end

function get_breadcrumbs(memory::HybridMemorySystem; intent=nothing, limit::Integer=40)
    items = memory.shared["breadcrumbs"]
    filtered = intent === nothing ? items : [item for item in items if get(item, "intent", nothing) == _normalize_intent(intent)]
    limit <= 0 && return filtered
    start_index = max(1, length(filtered) - limit + 1)
    return filtered[start_index:end]
end

function get_intent_context(memory::HybridMemorySystem; intent=nothing, limit::Integer=24)
    return Dict{String, Any}(
        "intent" => _normalize_intent(intent),
        "breadcrumbs" => get_breadcrumbs(memory; intent=intent, limit=limit),
    )
end

function update_after_turn!(
    memory::HybridMemorySystem,
    agent_id::AbstractString,
    user_message::AbstractString,
    output::AbstractString,
    engine_state::AbstractDict,
)
    agent_memory = _ensure_agent!(memory, agent_id)
    interactions = agent_memory["recent_interactions"]
    push!(interactions, Dict{String, Any}(
        "user_message" => user_message[1:min(end, 400)],
        "output" => output[1:min(end, 400)],
        "engine_snapshot" => Dict{String, Any}(
            "gait" => get(engine_state, "gait", nothing),
            "rhythm" => get(engine_state, "rhythm", nothing),
            "aperture" => get(engine_state, "aperture_mode", nothing),
            "dynamic" => get(engine_state, "dynamic", nothing),
        ),
    ))
    length(interactions) > 20 && deleteat!(interactions, 1:(length(interactions) - 20))

    memory.shared["last_active_agent"] = String(agent_id)
    flags = get(engine_state, "flags", nothing)
    if flags isa AbstractDict
        merge!(memory.shared["engine_flags"], Dict{String, Any}(string(key) => value for (key, value) in pairs(flags)))
    end

    dynamic_state = get(engine_state, "dynamic", nothing)
    dynamic_state isa AbstractDict && (agent_memory["dynamic_state"] = Dict{String, Any}(string(key) => value for (key, value) in pairs(dynamic_state)))
    return memory
end
