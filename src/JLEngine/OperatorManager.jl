mutable struct OperatorManager
    root_dir::String
    operators_dir::String
    active_name::Union{Nothing, String}
    base_data::Dict{String, Any}
    secondary_data::Union{Nothing, Dict{String, Any}}
    dynamic_trait_weight::Float64
end

OperatorManager(root_dir::AbstractString=pwd(), operators_dir::AbstractString="operators") = OperatorManager(String(root_dir), String(operators_dir), nothing, Dict{String, Any}(), nothing, 0.5)

function set_active_operator!(manager::OperatorManager, name::AbstractString, data::AbstractDict, registry::Union{Nothing, Dict{String, MPFProfile}}=nothing)
    manager.active_name = String(name)
    manager.base_data = Dict{String, Any}(string(key) => value for (key, value) in pairs(data))
    # Tag-based operator blending was silently merging a random sibling
    # operator's traits into the active one whenever they shared ANY tag.
    # With generic tags like "imported"/"card-cruncher" or "creative"/"quirky",
    # this caused operators to behave like a chimera of themselves and a random
    # other agent — and the random pick changed boot-to-boot due to undefined
    # Dict iteration order. Off by default. Opt in via env var if you actually
    # want this trait-mixing behavior.
    blend_enabled = lowercase(strip(get(ENV, "JLENGINE_OPERATOR_BLENDING", "0"))) in ("1", "true", "yes", "on")
    manager.secondary_data = (blend_enabled && registry !== nothing) ? _find_related_operator(manager, String(name), registry) : nothing
    manager.dynamic_trait_weight = 0.5
    return manager
end

function _find_related_operator(manager::OperatorManager, name::String, registry::Dict{String, MPFProfile})
    base_tags = Set{String}()
    raw_tags = get(manager.base_data, "tags", get(get(manager.base_data, "identity", Dict{String, Any}()), "tags", Any[]))
    if raw_tags isa AbstractVector
        for tag in raw_tags
            tag isa AbstractString && push!(base_tags, String(tag))
        end
    end

    isempty(base_tags) && return

    # Sort registry keys so the pick is deterministic if blending is opted into.
    # Also require ≥2 overlapping tags to filter out generic-tag false positives.
    for display_name in sort!(collect(keys(registry)))
        display_name == name && continue
        profile = registry[display_name]
        tags = Set(profile.tags)
        length(intersect(base_tags, tags)) >= 2 || continue
        operator_path = resolve_path(manager.root_dir, joinpath(manager.operators_dir, profile.operator_file))
        isfile(operator_path) || continue
        candidate = load_operator_file(operator_path)
        candidate isa AbstractDict && return Dict{String, Any}(string(key) => value for (key, value) in pairs(candidate))
    end
    return
end

function apply_supervisor_bias!(manager::OperatorManager, bias::Real)
    manager.dynamic_trait_weight = clamp(manager.dynamic_trait_weight + Float64(bias) * 0.25, 0.0, 1.0)
    return manager
end

function update_dynamic_weight!(manager::OperatorManager, signals=nothing; rhythm_state=nothing, aperture_state=nothing)
    sentiment = signals isa TurnSignals ? signals.sentiment : 0.0
    variability = rhythm_state isa AbstractDict ? _float_or(get(rhythm_state, "variability", 0.0), 0.0) : rhythm_state isa RhythmState ? rhythm_state.variability : 0.0
    aperture_score = aperture_state isa AbstractDict ? _float_or(get(aperture_state, "score", 0.0), 0.0) : 0.0
    delta = sentiment * 0.15 + variability * 0.1 + (aperture_score - 0.5) * 0.2
    manager.dynamic_trait_weight = clamp(manager.dynamic_trait_weight * 0.9 + delta, 0.0, 1.0)
    return manager
end

function _merge_trait_list(base_traits, secondary_traits, key::AbstractString)
    merged = String[]
    seen = Set{String}()
    for source in (base_traits, secondary_traits)
        values = source isa AbstractDict ? get(source, key, Any[]) : Any[]
        values isa AbstractVector || continue
        for item in values
            item isa AbstractString || continue
            text = String(item)
            in(text, seen) && continue
            push!(seen, text)
            push!(merged, text)
        end
    end
    return merged
end

function get_projection(manager::OperatorManager)
    operator = deepcopy(manager.base_data)
    operator["dynamic_trait_weight"] = round(manager.dynamic_trait_weight; digits=3)
    if manager.secondary_data !== nothing && manager.dynamic_trait_weight > 0.05
        base_traits = get(manager.base_data, "operational_behavioral_traits", Dict{String, Any}())
        secondary_traits = get(manager.secondary_data, "operational_behavioral_traits", Dict{String, Any}())
        operator["operational_behavioral_traits"] = Dict{String, Any}(
            "positive" => _merge_trait_list(base_traits, secondary_traits, "positive"),
            "negative" => _merge_trait_list(base_traits, secondary_traits, "negative"),
            "boundaries" => _merge_trait_list(base_traits, secondary_traits, "boundaries"),
            "dynamic_weight" => round(manager.dynamic_trait_weight; digits=3),
        )
    end
    return operator
end
