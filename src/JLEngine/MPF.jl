function load_mpf_registry(registry_path::AbstractString)
    raw_registry = load_json_safely(registry_path)
    profiles = Dict{String, MPFProfile}()

    for (display_name, entry) in raw_registry
        entry isa AbstractDict || continue
        agent_file = get(entry, "agent_file", nothing)
        agent_file isa AbstractString || continue
        tags = [String(tag) for tag in get(entry, "tags", Any[]) if tag isa AbstractString]
        profiles[String(display_name)] = MPFProfile(
            agent_file=String(agent_file),
            default_memory_mode=get(entry, "default_memory_mode", nothing),
            default_backend_id=get(entry, "default_backend_id", nothing),
            drive_type=get(entry, "drive_type", nothing),
            tags=tags,
        )
    end

    return profiles
end

load_agent_file(path::AbstractString) = load_json_safely(path)

function get_llm_boot_prompt(agent_config::AbstractDict, target::AbstractString="generic_llm")
    profiles = get(agent_config, "llm_profiles", nothing)
    profiles isa AbstractDict || return ""

    profile = get(profiles, target, nothing)
    if profile isa AbstractDict
        prompt = get(profile, "boot_prompt", nothing)
        prompt isa AbstractString && return String(prompt)
    end

    generic = get(profiles, "generic_llm", nothing)
    if generic isa AbstractDict
        prompt = get(generic, "boot_prompt", nothing)
        prompt isa AbstractString && return String(prompt)
    end

    return ""
end

function _mpf_dict(value)
    value isa AbstractDict || return Dict{String, Any}()
    return Dict{String, Any}(string(key) => item for (key, item) in pairs(value))
end

function _mpf_strings(value)
    value isa AbstractVector && return [String(item) for item in value if item isa AbstractString]
    value isa AbstractString && return [String(value)]
    return String[]
end

function _mpf_float_or(value, default::Float64)
    value isa Real && return Float64(value)
    try
        return parse(Float64, string(value))
    catch
        return default
    end
end

"""
    resolve_mpf_state_profile(agent_data, state)

Resolve the active MPF operator's semantic payload by stable behavior-cell
number. The behavior engine supplies a model-neutral control coordinate; MPF
owns what that coordinate means for the selected operator.
"""
function resolve_mpf_state_profile(agent_data::AbstractDict, state::BehaviorState)
    # Accept the pre-MPF key as a migration fallback for third-party profiles.
    raw_root = get(
        agent_data,
        "mpf_state_profile",
        get(agent_data, "behavior_grid_profile", Dict{String, Any}()),
    )
    root = _mpf_dict(raw_root)
    defaults = _mpf_dict(get(root, "default", Dict{String, Any}()))
    entries = get(root, "states", Dict{String, Any}())
    entries = entries isa AbstractDict ? entries : Dict{String, Any}()

    raw = Dict{String, Any}()
    for key in (string(state.number), lpad(string(state.number), 2, '0'), state.id)
        candidate = get(entries, key, nothing)
        if candidate isa AbstractDict
            raw = _mpf_dict(candidate)
            break
        end
    end

    identity = get(agent_data, "identity", Dict{String, Any}())
    identity_name = identity isa AbstractDict ? get(identity, "name", "Operator") : "Operator"
    resolved = merge(defaults, raw)
    # The global grid selects the control cell only. Agent-authored values
    # must exist before instructions can claim MPF authority.
    resolved["source"] = !isempty(raw) ? "mpf_operator" :
                         !isempty(defaults) ? "mpf_operator_default" :
                         "mpf_fallback"
    resolved["profile_name"] = String(get(root, "name", identity_name))
    resolved["state_number"] = state.number
    resolved["state_id"] = state.id
    resolved["diagnostic_name"] = state.name
    resolved["label"] = String(get(resolved, "label", state.name))
    resolved["stance"] = String(get(resolved, "stance", ""))
    resolved["delivery"] = _mpf_strings(get(resolved, "delivery", String[]))
    resolved["lexical_palette"] = _mpf_strings(get(resolved, "lexical_palette", String[]))
    resolved["avoid"] = _mpf_strings(get(resolved, "avoid", String[]))
    resolved["lexical_rule"] = String(get(resolved, "lexical_rule", get(root, "lexical_rule", "Treat palette items as optional color; never force or repeat them mechanically.")))
    resolved["coding_style"] = String(get(resolved, "coding_style", get(root, "coding_signature", "")))
    return resolved
end

function mpf_sampling_bias(profile::AbstractDict)
    raw = get(profile, "sampling_bias", Dict{String, Any}())
    raw isa AbstractDict || (raw = Dict{String, Any}())
    return Dict{String, Float64}(
        "temperature" => clamp(_mpf_float_or(get(raw, "temperature", 0.0), 0.0), -0.35, 0.35),
        "top_p" => clamp(_mpf_float_or(get(raw, "top_p", 0.0), 0.0), -0.25, 0.25),
    )
end

function mpf_state_instructions(
    state::BehaviorState,
    profile::AbstractDict;
    engine_context=nothing,
)
    # Do NOT turn global behavior-grid defaults into a second set of agent
    # instructions. Unmapped grid coordinates belong in engine telemetry only.
    get(profile, "source", "mpf_fallback") == "mpf_fallback" && return ""
    lines = String[
        "--- ACTIVE MPF OPERATOR STATE ---",
        "Behavior control cell: #$(state.number) [$(state.id)]. The number is authoritative; its generic behavior-grid name is diagnostic only.",
        "MPF profile: $(get(profile, "profile_name", "Operator"))",
        "MPF state: $(get(profile, "label", state.name))",
    ]
    # No generic expressiveness, pacing or tone directives in the agent
    # system message. Only authored agent text can specify delivery.
    stance = strip(string(get(profile, "stance", "")))
    isempty(stance) || push!(lines, "Agent-authored stance: " * stance)

    if engine_context isa AbstractDict
        push!(
            lines,
            "JL lattice: trigger=$(get(engine_context, "trigger", "neutral")); " *
            "gait=$(get(engine_context, "gait", "walk")); " *
            "rhythm=$(get(engine_context, "rhythm", "trot")); " *
            "aperture=$(get(engine_context, "aperture", "BALANCED")); " *
            "drift=$(round(_mpf_float_or(get(engine_context, "drift_pressure", 0.0), 0.0); digits=3)).",
        )
        advisory = strip(string(get(engine_context, "advisory", "")))
        isempty(advisory) || push!(lines, "Engine advisory: $advisory")
    end

    delivery = _mpf_strings(get(profile, "delivery", String[]))
    isempty(delivery) || push!(lines, "Delivery: " * join(delivery, " | "))

    palette = _mpf_strings(get(profile, "lexical_palette", String[]))
    if !isempty(palette)
        push!(lines, "Optional lexical palette: " * join(palette, " · "))
        push!(lines, "Palette rule: $(get(profile, "lexical_rule", "Use naturally and sparingly."))")
    end

    coding_style = strip(String(get(profile, "coding_style", "")))
    isempty(coding_style) || push!(lines, "Code-generation signature: $coding_style")

    avoid = _mpf_strings(get(profile, "avoid", String[]))
    isempty(avoid) || push!(lines, "Avoid in this cell: " * join(avoid, " | "))
    return join(lines, "\n")
end

# Compatibility aliases for existing third-party JL integrations.
resolve_behavior_profile(agent_data::AbstractDict, state::BehaviorState) =
    resolve_mpf_state_profile(agent_data, state)
behavior_sampling_bias(profile::AbstractDict) = mpf_sampling_bias(profile)
behavior_instructions(state::BehaviorState, profile::AbstractDict; kwargs...) =
    mpf_state_instructions(state, profile; kwargs...)
