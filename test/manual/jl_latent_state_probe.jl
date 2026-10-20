#!/usr/bin/env julia

"""
Probe the current JL Engine core as an external recurrent latent-state system.

No model, network, server, database, or tool call is used. Every scored sample
ends with the identical user message. Information is present only in earlier
user events or synthetic model-output feedback. A linear readout tests whether
that history remains recoverable from the engine state, while a reset control
checks that any signal is carried by mutable JL state rather than the probe.
"""

using JSON
using LinearAlgebra
using Random
using Statistics

const PROJECT_ROOT = normpath(joinpath(@__DIR__, "..", ".."))
include(joinpath(PROJECT_ROOT, "src", "JLEngine.jl"))
using .JLEngine

const SEED = 688
const HISTORY_LENGTH = 12
const SAMPLE_COUNT = 384
const PROBE_MESSAGE = "continue"
const POSITIVE_OUTPUT = "Great awesome yes love nice!"
const NEGATIVE_OUTPUT = "Sorry bad confused worry no?"
const NEUTRAL_OUTPUT = "Plain factual statement."
const POSITIVE_INPUT = "great yes exciting!"
const NEGATIVE_INPUT = "no confused why?"

function construct_engine()
    return JLEngineCore(EngineConfig(
        root_dir=joinpath(PROJECT_ROOT, "data"),
        master_file="JLframe_Engine_Framework.json",
        behavior_states_file="behavior_states.json",
        signal_lexicon_file="signal_lexicon.json",
        mpf_registry_file=joinpath("agents", "Agents.mpf.json"),
        agents_dir="agents",
        default_agent_name="SparkByte",
    ))
end

const ENGINE_TEMPLATE = construct_engine()
build_engine() = deepcopy(ENGINE_TEMPLATE)

function rhythm_code(value)
    value == "flop" && return -1.0
    value == "trot" && return 1.0
    return 0.0
end

function aperture_code(value)
    modes = Dict("CLOSED"=>0.0, "GUARDED"=>0.25, "BALANCED"=>0.5,
                 "OPEN"=>0.75, "WIDE_OPEN"=>1.0)
    return get(modes, String(value), 0.25)
end

function latent_vector(engine, snapshot)
    rhythm = snapshot["rhythm"]
    aperture = snapshot["aperture_state"]
    advisory = snapshot["advisory"]
    dynamic = export_snapshot(engine.state_manager)
    return Float64[
        rhythm["index"],
        rhythm["variability"],
        rhythm["momentum"],
        rhythm_code(rhythm["mode"]),
        rhythm_code(rhythm["attractor"]),
        aperture["score"],
        aperture["temp"],
        aperture["top_p"],
        aperture["drift_bias"],
        aperture["focus_level"],
        aperture["overload_level"],
        aperture_code(aperture["mode"]),
        advisory["emotional_drift"],
        advisory["rhythm_momentum"],
        advisory["gait_bias"],
        advisory["blend_weight"],
        advisory["attractor"],
        dynamic["emotional_drift"],
        dynamic["rhythm_momentum"],
        dynamic["gait_bias"],
        dynamic["behavior_blend"],
        dynamic["last_sentiment"],
        dynamic["attractor"],
        engine.stability_score,
        engine.agent_manager.dynamic_trait_weight,
        snapshot["behavior_intensity"],
        snapshot["behavior_state"]["expressiveness"],
        snapshot["drift"]["pressure"],
    ]
end

function reset_recurrent_state!(engine)
    engine.current_gait = "walk"
    engine.current_rhythm_mode = "flop"
    engine.stability_score = 0.5
    engine.rhythm_engine = RhythmEngine()
    reset!(engine.state_manager)
    reset!(engine.emotional_aperture)
    engine.agent_manager.dynamic_trait_weight = 0.5
    set_state_by_number!(engine.behavior_engine, 10)
    return engine
end

function output_feedback_sample(bits, washout; reset_before_probe=false)
    engine = build_engine()
    for bit in bits
        snapshot = analyze_turn!(engine, PROBE_MESSAGE)
        output = bit == 1 ? POSITIVE_OUTPUT : NEGATIVE_OUTPUT
        record_turn!(engine, PROBE_MESSAGE, output; snapshot=snapshot)
    end
    for _ in 1:washout
        snapshot = analyze_turn!(engine, PROBE_MESSAGE)
        record_turn!(engine, PROBE_MESSAGE, NEUTRAL_OUTPUT; snapshot=snapshot)
    end
    reset_before_probe && reset_recurrent_state!(engine)
    return latent_vector(engine, analyze_turn!(engine, PROBE_MESSAGE))
end

function failed_turn_sample(bits, washout; reset_before_probe=false)
    engine = build_engine()
    for bit in bits
        analyze_turn!(engine, bit == 1 ? POSITIVE_INPUT : NEGATIVE_INPUT)
    end
    for _ in 1:washout
        analyze_turn!(engine, PROBE_MESSAGE)
    end
    reset_before_probe && reset_recurrent_state!(engine)
    return latent_vector(engine, analyze_turn!(engine, PROBE_MESSAGE))
end

function standardize(train, test)
    mu = vec(mean(train; dims=1))
    sigma = vec(std(train; dims=1, corrected=false))
    sigma[sigma .< 1e-9] .= 1.0
    return (train .- mu') ./ sigma', (test .- mu') ./ sigma'
end

function linear_readout(train_x, train_y, test_x, test_y; ridge=1e-3)
    ztrain, ztest = standardize(train_x, test_x)
    xtrain = hcat(ones(size(ztrain, 1)), ztrain)
    xtest = hcat(ones(size(ztest, 1)), ztest)
    penalty = Matrix{Float64}(I, size(xtrain, 2), size(xtrain, 2))
    penalty[1, 1] = 0.0
    weights = (xtrain' * xtrain + ridge * penalty) \ (xtrain' * train_y)
    scores = xtest * weights
    predictions = scores .>= 0.5
    accuracy = mean(predictions .== (test_y .>= 0.5))
    majority = max(mean(test_y .>= 0.5), mean(test_y .< 0.5))
    return Dict(
        "accuracy"=>accuracy,
        "majority_baseline"=>majority,
        "margin_over_majority"=>accuracy-majority,
    )
end

function feature_set_readouts(features, labels, split)
    sets = Dict(
        "full_internal"=>collect(1:28),
        "active_recurrent"=>[3, 5, 9, 13, 14, 17, 18, 19, 22, 23, 24],
        "ui_model_channel"=>[4, 7, 8, 12, 26, 27, 28],
        "a2a_model_channel"=>[4, 7, 8, 12, 24, 26, 27, 28],
        "apparently_disconnected"=>[10, 11, 15, 16, 20, 21, 25],
    )
    results = Dict{String,Any}()
    for (set_name, indices) in sets
        matrix = features[:, indices]
        set_results = Dict{String,Any}()
        for (label_name, values) in labels
            set_results[label_name] = linear_readout(
                matrix[1:split, :], values[1:split],
                matrix[split+1:end, :], values[split+1:end]
            )
        end
        results[set_name] = Dict(
            "feature_count"=>length(indices),
            "feature_rank"=>rank(matrix .- mean(matrix; dims=1); atol=1e-8),
            "readouts"=>set_results,
        )
    end
    for digits in (3, 2, 1)
        matrix = round.(features; digits=digits)
        quantized = Dict{String,Any}()
        for (label_name, values) in labels
            quantized[label_name] = linear_readout(
                matrix[1:split, :], values[1:split],
                matrix[split+1:end, :], values[split+1:end]
            )
        end
        results["full_internal_rounded_$(digits)dp"] = Dict(
            "feature_count"=>size(matrix, 2),
            "feature_rank"=>rank(matrix .- mean(matrix; dims=1); atol=1e-8),
            "readouts"=>quantized,
        )
    end
    return results
end

function evaluate_carrier(sample_fn, histories, washout; reset_before_probe=false)
    features = reduce(vcat, [sample_fn(bits, washout;
        reset_before_probe=reset_before_probe)' for bits in histories])
    split = floor(Int, length(histories) * 0.7)
    train_x, test_x = features[1:split, :], features[split+1:end, :]
    labels = Dict(
        "last_bit"=>Float64[bits[end] for bits in histories],
        "lag_2"=>Float64[bits[end-1] for bits in histories],
        "lag_4"=>Float64[bits[end-3] for bits in histories],
        "lag_8"=>Float64[bits[end-7] for bits in histories],
        "xor_last_two"=>Float64[xor(bits[end] == 1, bits[end-1] == 1) for bits in histories],
        "order_last_two"=>Float64[(bits[end-1] == 1 && bits[end] == 0) for bits in histories],
    )
    return Dict(
        "washout_turns"=>washout,
        "reset_before_probe"=>reset_before_probe,
        "feature_dimension"=>size(features, 2),
        "feature_rank"=>rank(features .- mean(features; dims=1); atol=1e-8),
        "feature_sets"=>feature_set_readouts(features, labels, split),
    )
end

function polarity_hysteresis()
    positive = output_feedback_sample(fill(1, 16), 0)
    negative = output_feedback_sample(fill(0, 16), 0)
    positive_wash = output_feedback_sample(fill(1, 16), 8)
    negative_wash = output_feedback_sample(fill(0, 16), 8)
    return Dict(
        "distance_no_washout"=>norm(positive-negative),
        "distance_after_8_neutral_turns"=>norm(positive_wash-negative_wash),
        "distance_ratio_after_washout"=>(
            norm(positive_wash-negative_wash) / max(norm(positive-negative), 1e-12)
        ),
    )
end

function ema_baseline_features(bits, washout)
    states = zeros(Float64, 3)
    last_value = 0.0
    for bit in bits
        value = bit == 1 ? 1.0 : -1.0
        states .= (0.90, 0.85, 0.82) .* states .+ value
        last_value = value
    end
    for _ in 1:washout
        states .= (0.90, 0.85, 0.82) .* states
        last_value = 0.0
    end
    thresholds = Float64[]
    for state in states, threshold in (-1.0, -0.5, 0.0, 0.5, 1.0)
        push!(thresholds, state > threshold)
    end
    return vcat(states, last_value, thresholds)
end

function evaluate_ema_baseline(histories, washout)
    features = reduce(vcat, [ema_baseline_features(bits, washout)' for bits in histories])
    split = floor(Int, length(histories) * 0.7)
    labels = Dict(
        "last_bit"=>Float64[bits[end] for bits in histories],
        "lag_2"=>Float64[bits[end-1] for bits in histories],
        "lag_4"=>Float64[bits[end-3] for bits in histories],
        "lag_8"=>Float64[bits[end-7] for bits in histories],
        "xor_last_two"=>Float64[xor(bits[end] == 1, bits[end-1] == 1) for bits in histories],
        "order_last_two"=>Float64[(bits[end-1] == 1 && bits[end] == 0) for bits in histories],
    )
    results = Dict{String,Any}()
    for (name, indices) in ("linear_ema_bank"=>collect(1:4),
                            "thresholded_ema_bank"=>collect(1:size(features, 2)))
        matrix = features[:, indices]
        results[name] = Dict(
            "feature_count"=>length(indices),
            "feature_rank"=>rank(matrix .- mean(matrix; dims=1); atol=1e-8),
            "readouts"=>Dict(label=>linear_readout(
                matrix[1:split, :], values[1:split],
                matrix[split+1:end, :], values[split+1:end]
            ) for (label, values) in labels),
        )
    end
    return Dict("washout_turns"=>washout, "sets"=>results)
end

function main()
    rng = MersenneTwister(SEED)
    histories = [rand(rng, 0:1, HISTORY_LENGTH) for _ in 1:SAMPLE_COUNT]
    output_feedback = [
        evaluate_carrier(output_feedback_sample, histories, washout)
        for washout in (0, 2, 8, 16)
    ]
    failed_turns = [
        evaluate_carrier(failed_turn_sample, histories, washout)
        for washout in (0, 2, 8, 16)
    ]
    reset_control = Dict(
        "output_feedback"=>evaluate_carrier(
            output_feedback_sample, histories, 0; reset_before_probe=true
        ),
        "failed_turns"=>evaluate_carrier(
            failed_turn_sample, histories, 0; reset_before_probe=true
        ),
    )
    result = Dict(
        "schema"=>"jl-latent-state-probe/v1",
        "seed"=>SEED,
        "samples"=>SAMPLE_COUNT,
        "history_length"=>HISTORY_LENGTH,
        "identical_final_probe"=>PROBE_MESSAGE,
        "foundation_model_called"=>false,
        "output_feedback_carrier"=>output_feedback,
        "failed_turn_carrier"=>failed_turns,
        "matched_leaky_baseline"=>[
            evaluate_ema_baseline(histories, washout) for washout in (0, 2, 8, 16)
        ],
        "reset_control"=>reset_control,
        "polarity_hysteresis"=>polarity_hysteresis(),
        "claim_boundary"=>(
            "Recoverable history would establish an external recurrent state " *
            "carrier only, not language understanding or new capability."
        ),
    )
    if get(ENV, "JL_PROBE_COMPACT", "0") == "1"
        compact = Dict{String,Any}()
        for carrier_name in ("output_feedback_carrier", "failed_turn_carrier")
            compact[carrier_name] = [Dict(
                "washout_turns"=>entry["washout_turns"],
                "sets"=>Dict(
                    set_name=>Dict(
                        "rank"=>entry["feature_sets"][set_name]["feature_rank"],
                        "last_bit"=>entry["feature_sets"][set_name]["readouts"]["last_bit"]["accuracy"],
                        "lag_8"=>entry["feature_sets"][set_name]["readouts"]["lag_8"]["accuracy"],
                        "xor_last_two"=>entry["feature_sets"][set_name]["readouts"]["xor_last_two"]["accuracy"],
                    ) for set_name in (
                        "full_internal", "active_recurrent", "ui_model_channel",
                        "a2a_model_channel", "apparently_disconnected",
                        "full_internal_rounded_3dp"
                    )
                ),
            ) for entry in result[carrier_name]]
        end
        compact["reset_control"] = Dict(
            name=>Dict(
                "rank"=>entry["feature_sets"]["full_internal"]["feature_rank"],
                "last_bit"=>entry["feature_sets"]["full_internal"]["readouts"]["last_bit"]["accuracy"],
            ) for (name, entry) in result["reset_control"]
        )
        compact["polarity_hysteresis"] = result["polarity_hysteresis"]
        compact["matched_leaky_baseline"] = result["matched_leaky_baseline"]
        compact["majority_baselines"] = Dict(
            name=>result["output_feedback_carrier"][1]["feature_sets"]["full_internal"]["readouts"][name]["majority_baseline"]
            for name in ("last_bit", "lag_8", "xor_last_two")
        )
        println(JSON.json(compact, 2))
    else
        println(JSON.json(result, 2))
    end
end

abspath(PROGRAM_FILE) == abspath(@__FILE__) && main()
