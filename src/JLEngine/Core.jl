mutable struct JLEngineCore
    config::EngineConfig
    master_blob::Dict{String, Any}
    master_config::Dict{String, Any}
    core_rules::Vector{String}
    mpf_profiles::Dict{String, MPFProfile}
    agent_state::Dict{String, Any}
    behavior_engine::BehaviorStateMachine
    emotional_aperture::EmotionalAperture
    signal_scorer::SignalScorer
    drift_system::DriftPressureSystem
    rhythm_engine::RhythmEngine
    memory_system::HybridMemorySystem
    state_manager::StateManager
    agent_manager::AgentManager
    current_agent_name::String
    current_agent_data::Dict{String, Any}
    current_agent_file::Union{Nothing, String}
    current_gait::String
    current_rhythm_mode::String
    stability_score::Float64
    # Cognitive callback — set by BYTE.init() to push live engine state to UI terminal.
    # Signature: fn(snapshot::Dict, event::Symbol) -> nothing
    cognitive_callback::Any
end

function JLEngineCore(config::EngineConfig=EngineConfig())
    master_path = resolve_path(config.root_dir, config.master_file)
    master_blob = load_json_safely(master_path)
    master_config = load_engine_config(master_path)
    core_rules = [String(rule) for rule in get(master_config, "core_rules", Any[]) if rule isa AbstractString]
    mpf_profiles = load_mpf_registry(resolve_path(config.root_dir, config.mpf_registry_file))
    agent_state = Dict{String, Any}("emotion" => nothing, "emotion_meta" => nothing)

    engine = JLEngineCore(
        config,
        master_blob,
        master_config,
        core_rules,
        mpf_profiles,
        agent_state,
        BehaviorStateMachine(resolve_path(config.root_dir, config.behavior_states_file)),
        EmotionalAperture(agent_state=agent_state),
        SignalScorer(resolve_path(config.root_dir, config.signal_lexicon_file)),
        DriftPressureSystem(),
        RhythmEngine(),
        HybridMemorySystem(),
        StateManager(),
        AgentManager(config.root_dir, config.agents_dir),
        config.default_agent_name,
        Dict{String, Any}(),
        nothing,
        "walk",
        "flop",
        0.5,
        nothing,    # cognitive_callback — installed by BYTE.init()
    )
    set_agent!(engine, config.default_agent_name)
    return engine
end

"""
    set_cognitive_callback!(engine, fn)

Install a hook called on every engine tick. `fn` receives `(snapshot, event_symbol)` where
event_symbol is one of :analyze_start, :analyze_done, :record_turn, :run_turn, :gait_change.
"""
function set_cognitive_callback!(engine::JLEngineCore, fn)
    engine.cognitive_callback = fn
    return
end

function set_agent!(engine::JLEngineCore, agent_name::AbstractString)
    # Never silently fall back to SparkByte when an explicit agent is unknown.
    selected_name = String(agent_name)
    profile = get(engine.mpf_profiles, selected_name, nothing)
    profile === nothing && return false

    agent_path = resolve_path(engine.config.root_dir, joinpath(engine.config.agents_dir, profile.agent_file))
    isfile(agent_path) || return false
    loaded_profile = load_agent_file(agent_path)
    isempty(loaded_profile) && return false

    engine.current_agent_name = selected_name
    engine.current_agent_file = profile.agent_file
    engine.agent_state["emotion"] = nothing
    engine.agent_state["emotion_meta"] = nothing
    engine.current_agent_data = loaded_profile
    set_agent_state!(engine.emotional_aperture, engine.agent_state)
    set_emotion_palette!(engine.emotional_aperture, get(engine.current_agent_data, "emotion_palette", Any[]))
    profile.drive_type !== nothing && set_drive_type!(engine.emotional_aperture, profile.drive_type)
    set_active_agent!(engine.agent_manager, selected_name, engine.current_agent_data, engine.mpf_profiles)

    engine.current_gait = "walk"
    engine.current_rhythm_mode = "flop"
    engine.stability_score = 0.5
    return true
end

function analyze_turn!(engine::JLEngineCore, user_message::AbstractString; agent_name=nothing, safety_on::Bool=engine.config.safety_on)
    # Preserve MPF emotional/rhythm/stability continuity across turns.
    # Loading an agent is an explicit switch, not a per-turn reinitialization.
    if agent_name !== nothing && String(agent_name) != engine.current_agent_name
        set_agent!(engine, String(agent_name)) || error("Unknown agent: $(agent_name)")
    end

    signals = score(engine.signal_scorer, user_message)
    trigger = derive_trigger(signals)
    prev_gait = engine.current_gait
    engine.current_gait = infer_gait(signals)

    # ── Cognitive hook: gait change detected ─────────────────────────────
    if engine.cognitive_callback !== nothing
        try
            engine.cognitive_callback(Dict("event"=>"gait_change", "from"=>prev_gait, "to"=>engine.current_gait), :gait_change)
        catch
        end
    end

    drift_input = DriftPressureInput(
        agent_alignment_score=1.0 - min(0.25, signals.confusion * 0.2),
        behavior_grid_alignment_score=1.0 - min(0.35, signals.arousal * 0.15),
        safety_alignment_score=safety_on ? 1.0 : 0.9,
        memory_alignment_score=1.0 - min(0.40, signals.memory_density * 0.25),
        conversational_coherence_score=1.0 - min(0.60, signals.confusion * 0.8),
    )
    pressure = calculate(engine.drift_system, drift_input)
    drift_response = get_response_action(engine.drift_system, pressure)
    advisory = advisory_payload(engine.state_manager, engine.stability_score, pressure)
    gating_advice = advisory["gating_bias"] > 0 ? Dict{String, Any}("level" => "weak_block", "weight" => advisory["gating_bias"]) : Dict{String, Any}("level" => "allow", "weight" => 0.0)
    grid_intensity = behavior_intensity(signals)
    behavior_state = transition_by_trigger!(
        engine.behavior_engine,
        trigger,
        engine.current_gait;
        gating_advice=gating_advice,
        intensity_hint=grid_intensity,
    )
    mpf_profile = resolve_mpf_state_profile(engine.current_agent_data, behavior_state)
    mpf_bias = mpf_sampling_bias(mpf_profile)

    rhythm_state = compute(
        engine.rhythm_engine;
        last_mode=engine.current_rhythm_mode,
        trigger=trigger,
        gait=engine.current_gait,
        behavior_state=behavior_state,
        drift_pressure=pressure,
        safety_on=safety_on,
        modulation_hint=advisory,
    )
    engine.current_rhythm_mode = rhythm_state.mode

    inject_drift_bias!(engine.emotional_aperture, advisory["emotional_drift"])
    aperture_state = update_from_signals!(
        engine.emotional_aperture;
        behavior_state=behavior_state,
        gait=engine.current_gait,
        rhythm=rhythm_state.mode,
        agent_vividness=0.6,
        safety_mode=safety_on,
        drift_pressure=pressure,
        user_sentiment=signals.sentiment,
        conversation_pacing=signals.pace,
        memory_density=signals.memory_density,
    )
    update_dynamic_weight!(engine.agent_manager, signals; rhythm_state=_rhythm_state_dict(rhythm_state), aperture_state=aperture_state)
    agent_projection = get_projection(engine.agent_manager)
    mpf_directive = mpf_state_instructions(
        behavior_state,
        mpf_profile;
        engine_context=Dict{String, Any}(
            "trigger" => trigger,
            "gait" => engine.current_gait,
            "rhythm" => rhythm_state.mode,
            "aperture" => get(aperture_state, "mode", "BALANCED"),
            "drift_pressure" => pressure,
            "advisory" => get(advisory, "msg", ""),
        ),
    )

    snapshot = Dict{String, Any}(
        "agent" => engine.current_agent_name,
        "agent_file" => engine.current_agent_file,
        "agent_projection" => agent_projection,
        "trigger" => trigger,
        "gait" => engine.current_gait,
        "signals" => _signals_dict(signals),
        "behavior_intensity" => grid_intensity,
        "behavior_state" => _behavior_state_dict(behavior_state),
        "mpf_state_profile" => mpf_profile,
        "mpf_state_directive" => mpf_directive,
        "mpf_sampling_bias" => mpf_bias,
        "behavior_blend" => current_blend(engine.behavior_engine),
        "rhythm" => _rhythm_state_dict(rhythm_state),
        "drift" => _drift_response_dict(drift_response),
        "aperture_state" => aperture_state,
        "advisory" => advisory,
        "core_rules" => engine.core_rules,
        "memory_context" => get_context(engine.memory_system, engine.current_agent_name),
    )

    # ── Cognitive hook: analyze done ────────────────────────────────────
    if engine.cognitive_callback !== nothing
        try
            engine.cognitive_callback(snapshot, :analyze_done)
        catch
        end
    end

    return snapshot
end

function record_turn!(engine::JLEngineCore, user_message::AbstractString, output::AbstractString; snapshot=nothing)
    engine_state = snapshot isa AbstractDict ? get(snapshot, "engine_state", nothing) : nothing
    if !(engine_state isa AbstractDict)
        engine_state = Dict{String, Any}(
            "gait" => engine.current_gait,
            "rhythm" => engine.current_rhythm_mode,
            "aperture_mode" => get(engine.emotional_aperture.last_state, "mode", nothing),
            "dynamic" => export_snapshot(engine.state_manager),
            "flags" => Dict{String, Any}(),
        )
    end
    update_after_turn!(engine.memory_system, engine.current_agent_name, user_message, output, engine_state)
    rhythm_snapshot = snapshot isa AbstractDict ? get(snapshot, "rhythm", nothing) : nothing
    drift_snapshot = snapshot isa AbstractDict ? get(snapshot, "drift", Dict{String, Any}()) : Dict{String, Any}()
    update_from_output!(engine.state_manager, output; rhythm_state=rhythm_snapshot, gait=engine.current_gait)
    apply_output_feedback!(engine.emotional_aperture, output; rhythm_state=rhythm_snapshot, gait=engine.current_gait)
    engine.stability_score = clamp(0.55 - get(drift_snapshot, "pressure", 0.0) * 0.25 + export_snapshot(engine.state_manager)["last_sentiment"] * 0.05, 0.1, 0.95)

    # ── Cognitive hook: turn recorded ───────────────────────────────────
    if engine.cognitive_callback !== nothing
        try
            engine.cognitive_callback(Dict("stability"=>engine.stability_score, "reply_len"=>length(output)), :record_turn)
        catch
        end
    end

    return get_context(engine.memory_system, engine.current_agent_name)
end

get_llm_boot_prompt(engine::JLEngineCore, target::AbstractString="generic_llm") = get_llm_boot_prompt(engine.current_agent_data, target)

function run_turn!(engine::JLEngineCore, user_message::AbstractString; agent_name=nothing, backend_id=nothing, backend_overrides=nothing)
    snapshot = analyze_turn!(engine, user_message; agent_name=agent_name)
    messages = _build_messages(engine, user_message, snapshot)
    sampling_bias = get(snapshot, "mpf_sampling_bias", Dict{String, Any}())
    options = Dict{String, Any}(
        "temperature" => clamp(
            get(snapshot["aperture_state"], "temp", 0.45) +
            get(snapshot["drift"], "temperature_delta", 0.0) +
            get(sampling_bias, "temperature", 0.0),
            0.1,
            1.5,
        ),
        "top_p" => clamp(
            get(snapshot["aperture_state"], "top_p", 0.7) +
            get(sampling_bias, "top_p", 0.0),
            0.1,
            1.0,
        ),
    )
    backend = backend_id === nothing ? get_brain_backend() : get_backend(String(backend_id); overrides=backend_overrides)
    reply, backend_meta = generate(backend, messages; options=options)
    context = record_turn!(engine, user_message, reply; snapshot=snapshot)

    # ── Cognitive hook: full turn complete ─────────────────────────────
    if engine.cognitive_callback !== nothing
        try
            engine.cognitive_callback(Dict("reply_len"=>length(reply), "stability"=>engine.stability_score), :run_turn)
        catch
        end
    end

    return Dict{String, Any}(
        "ok" => true,
        "reply" => reply,
        "telemetry" => merge(snapshot, Dict{String, Any}("backend_meta" => backend_meta, "messages" => messages)),
        "memory_context" => context,
    )
end

function _signals_dict(signals::TurnSignals)
    return Dict{String, Any}(
        "sentiment" => signals.sentiment,
        "arousal" => signals.arousal,
        "directive" => signals.directive,
        "confusion" => signals.confusion,
        "pace" => signals.pace,
        "memory_density" => signals.memory_density,
        "playfulness" => signals.playfulness,
        "distress" => signals.distress,
    )
end

function _behavior_state_dict(state::BehaviorState)
    return Dict{String, Any}(
        "number" => state.number,
        "id" => state.id,
        "name" => state.name,
        "expressiveness" => state.expressiveness,
        "pacing" => state.pacing,
        "tone_bias" => state.tone_bias,
        "memory_strictness" => state.memory_strictness,
    )
end

function _rhythm_state_dict(state::RhythmState)
    return Dict{String, Any}(
        "mode" => state.mode,
        "index" => state.index,
        "variability" => state.variability,
        "momentum" => state.momentum,
        "attractor" => state.attractor,
        "modifiers" => state.modifiers,
        "debug" => state.debug,
    )
end

function _drift_response_dict(response::DriftResponse)
    return Dict{String, Any}(
        "pressure" => response.pressure,
        "action_level" => response.action_level,
        "temperature_delta" => response.temperature_delta,
        "force_gait" => response.force_gait,
        "force_rhythm" => response.force_rhythm,
        "supervisor_warning" => response.supervisor_warning,
        "reinforce_gait" => response.reinforce_gait,
    )
end

function _build_messages(engine::JLEngineCore, user_text::AbstractString, snapshot::AbstractDict)
    projection = get(snapshot, "agent_projection", engine.current_agent_data)
    lines = String[]
    !isempty(engine.core_rules) && begin
        push!(lines, "CORE RULES:")
        append!(lines, ["- $(rule)" for rule in engine.core_rules])
    end
    push!(lines, "")
    push!(lines, "ACTIVE AGENT: $(get(projection, "name", engine.current_agent_name))")
    boot_prompt = get_llm_boot_prompt(engine)
    !isempty(boot_prompt) && push!(lines, boot_prompt)
    base_prompt = get(projection, "base_prompt", "")
    base_prompt isa AbstractString && !isempty(base_prompt) && base_prompt != boot_prompt && push!(lines, String(base_prompt))
    push!(lines, "")
    if isdefined(Main, :BYTE)
        push!(lines, Main.BYTE._build_self_context(engine))
        push!(lines, "")
    end
    push!(lines, "ENGINE STATE SNAPSHOT:")
    push!(lines, "- Gait: $(get(snapshot, "gait", engine.current_gait))")
    push!(lines, "- Rhythm mode: $(get(get(snapshot, "rhythm", Dict{String, Any}()), "mode", engine.current_rhythm_mode))")
    push!(lines, "- Aperture mode: $(get(get(snapshot, "aperture_state", Dict{String, Any}()), "mode", "GUARDED"))")
    push!(lines, "- Drift pressure: $(round(get(get(snapshot, "drift", Dict{String, Any}()), "pressure", 0.0); digits=3))")
    push!(lines, "- Stability score: $(round(engine.stability_score; digits=3))")
    behavior = get(snapshot, "behavior_state", Dict{String, Any}())
    profile = get(snapshot, "mpf_state_profile", Dict{String, Any}())
    push!(lines, "- Behavior cell: #$(get(behavior, "number", "?")) ($(get(profile, "label", get(behavior, "name", "Unknown"))))")
    directive = get(snapshot, "mpf_state_directive", "")
    directive isa AbstractString && !isempty(directive) && begin
        push!(lines, "")
        push!(lines, String(directive))
    end

    history = Any[]
    memory_context = get(snapshot, "memory_context", Dict{String, Any}())
    agent_memory = get(memory_context, "agent_memory", Dict{String, Any}())
    recent = get(agent_memory, "recent_interactions", Any[])
    if recent isa AbstractVector
        for interaction in recent[max(1, length(recent)-2):end]
            interaction isa AbstractDict || continue
            push!(history, Dict{String, Any}("role" => "user", "content" => get(interaction, "user_message", "")))
            push!(history, Dict{String, Any}("role" => "assistant", "content" => get(interaction, "output", "")))
        end
    end

    messages = Any[Dict{String, Any}("role" => "system", "content" => join(lines, "\n"))]
    append!(messages, history)
    push!(messages, Dict{String, Any}("role" => "user", "content" => user_text))
    return messages
end
