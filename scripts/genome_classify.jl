#!/usr/bin/env julia
# genome_classify.jl — Classify genome records into JulianMetaMorph capability objects.
#
# Reads data/genome/hf_*.jsonl, runs multi-signal detection per-row,
# and writes data/genome/classified/*.jsonl with capability annotations.
#
# Usage:
#   julia --project=. scripts/genome_classify.jl [--kind models|all] [--out-dir path]
#
# Each output record = original genome row + "julian_metamorph" capability block.

using JSON3, Dates

const GENOME_DIR   = joinpath(@__DIR__, "..", "data", "genome")
const OUT_DIR_DEFAULT = joinpath(GENOME_DIR, "classified")

# ── Detection signals ──────────────────────────────────────────────────────────

const PIPELINE_DIRECT   = Set(["feature-extraction", "image-feature-extraction"])
const PIPELINE_ADJACENT = Set(["sentence-similarity"])

const TAG_SIGNALS = Set([
    "feature-extraction",
    "embedding",
    "multimodal embedding",
    "text-embeddings-inference",
])

# Pipeline → subtype
const PIPELINE_SUBTYPE = Dict(
    "feature-extraction"       => "text_embedding",
    "sentence-similarity"      => "text_embedding",
    "image-feature-extraction" => "image_embedding",
)

# Tag → subtype (checked after pipeline)
const TAG_SUBTYPE = Dict(
    "multimodal embedding"       => "multimodal_embedding",
    "text-embeddings-inference"  => "text_embedding",
    "embedding"                  => "text_embedding",
    "feature-extraction"         => "text_embedding",
)

# Subtype → output type
const SUBTYPE_OUTPUT = Dict(
    "text_embedding"        => "vector",
    "image_embedding"       => "vector",
    "multimodal_embedding"  => "vector",
    "latent_feature_encoder"=> "vector",
)

# Subtype → semantic memory role
const SUBTYPE_VECTOR_ROLE = Dict(
    "text_embedding"        => "semantic_memory",
    "image_embedding"       => "visual_memory",
    "multimodal_embedding"  => "multimodal_memory",
    "latent_feature_encoder"=> "latent_state",
)

# Known role overrides — ground truth from JulianMetaMorph spec
const KNOWN_ROLES = Dict(
    "Xenova/all-MiniLM-L6-v2"                          => "edge_text_encoder",
    "sentence-transformers/all-MiniLM-L6-v2"           => "edge_text_encoder",
    "Qwen/Qwen3-Embedding-8B"                           => "high_power_text_encoder",
    "Qwen/Qwen3-Embedding-4B"                           => "balanced_text_encoder",
    "BAAI/bge-small-zh-v1.5"                            => "chinese_text_encoder",
    "facebook/dinov2-base"                              => "image_feature_encoder",
    "Qwen/Qwen3-VL-Embedding-2B"                        => "multimodal_embedding_encoder",
    "sentence-transformers/paraphrase-mpnet-base-v2"    => "semantic_similarity_encoder",
    "deepseek-ai/DeepSeek-OCR"                          => "vision_text_feature_bridge",
    "openvla/openvla-7b"                                => "robotics_multimodal_feature_bridge",
)

# Subtype → default role label when not in KNOWN_ROLES
const SUBTYPE_DEFAULT_ROLE = Dict(
    "text_embedding"        => "text_encoder",
    "image_embedding"       => "image_feature_encoder",
    "multimodal_embedding"  => "multimodal_encoder",
    "latent_feature_encoder"=> "latent_feature_bridge",
)

# ── Core detector ──────────────────────────────────────────────────────────────

function detect_feature_extractor(row::Dict)
    pipeline = get(row, "pipeline", nothing)
    pipeline_s = pipeline isa AbstractString ? lowercase(strip(pipeline)) : ""
    tags_raw = get(row, "tags", String[])
    tags = Set(lowercase(strip(string(t))) for t in tags_raw)
    id = get(row, "id", "")

    is_fe = false
    subtype = ""
    confidence = 0.0
    source_signal = Dict{String,Any}()

    # Direct pipeline hit — highest confidence
    if pipeline_s in PIPELINE_DIRECT
        is_fe = true
        subtype = get(PIPELINE_SUBTYPE, pipeline_s, "text_embedding")
        confidence = 1.0
        source_signal["pipeline"] = pipeline_s

    # Adjacent pipeline (sentence-similarity) — high confidence
    elseif pipeline_s in PIPELINE_ADJACENT
        is_fe = true
        subtype = get(PIPELINE_SUBTYPE, pipeline_s, "text_embedding")
        confidence = 0.9
        source_signal["pipeline"] = pipeline_s

    # Tag-only detection — medium confidence (the "fake mustache" case)
    else
        matched_tags = filter(t -> t in TAG_SIGNALS, tags)
        if !isempty(matched_tags)
            is_fe = true
            # Pick the most specific subtype from matched tags
            for t in ["multimodal embedding", "text-embeddings-inference", "embedding", "feature-extraction"]
                if t in matched_tags
                    subtype = get(TAG_SUBTYPE, t, "text_embedding")
                    break
                end
            end
            isempty(subtype) && (subtype = "text_embedding")
            confidence = 0.75
            source_signal["tags"] = collect(matched_tags)
            # Bump confidence if main pipeline is multimodal/vision — it's intentional
            pipeline_s in ["image-text-to-text", "visual-question-answering"] && (confidence = 0.85)
        end
    end

    is_fe || return nothing

    # Refine subtype for multimodal signals
    if "multimodal embedding" in tags
        subtype = "multimodal_embedding"
    elseif pipeline_s in ["image-text-to-text", "visual-question-answering"] && is_fe
        subtype = "multimodal_embedding"
    end

    # Robotics latent encoder override
    if any(t -> occursin("robotics", t) || occursin("openvla", t), tags)
        subtype = "latent_feature_encoder"
    end

    # Azure candidate
    azure_candidate = "deploy:azure" in tags

    # Input modalities
    input_modalities = if subtype == "image_embedding"
        ["image"]
    elseif subtype == "multimodal_embedding"
        ["text", "image"]
    elseif subtype == "latent_feature_encoder"
        ["image", "text", "sensor"]
    else
        ["text"]
    end

    # JulianMetaMorph role
    jm_role = get(KNOWN_ROLES, string(id), get(SUBTYPE_DEFAULT_ROLE, subtype, "text_encoder"))

    return Dict{String,Any}(
        "capability"             => "feature_extraction",
        "subtype"                => subtype,
        "input_modalities"       => input_modalities,
        "output_type"            => get(SUBTYPE_OUTPUT, subtype, "vector"),
        "vector_role"            => get(SUBTYPE_VECTOR_ROLE, subtype, "semantic_memory"),
        "azure_candidate"        => azure_candidate,
        "julian_metamorph_role"  => jm_role,
        "confidence"             => confidence,
        "source_signal"          => source_signal,
    )
end

# ── JSONL processing ───────────────────────────────────────────────────────────

function classify_file(in_path::String, out_path::String)
    mkpath(dirname(out_path))
    total = 0; classified = 0; bad_lines = 0

    open(out_path, "w") do out_io
        open(in_path, "r") do in_io
            for (lineno, raw_line) in enumerate(eachline(in_io))
                line = strip(raw_line)
                isempty(line) && continue

                # Victorian candle protection — skip bad JSON without dying
                obj = try
                    JSON3.read(line)
                catch
                    bad_lines += 1
                    continue
                end

                total += 1

                # Build mutable Dict; normalize tags to Vector{String} for set ops
                row = Dict{String,Any}(string(k) => v for (k, v) in pairs(obj))
                raw_tags = get(row, "tags", nothing)
                if raw_tags !== nothing && !(raw_tags isa Vector{String})
                    row["tags"] = [string(t) for t in raw_tags]
                end

                cap = detect_feature_extractor(row)
                cap === nothing && continue

                row["julian_metamorph"] = cap
                row["classified_at"] = string(now(UTC))
                println(out_io, JSON3.write(row))
                classified += 1
            end
        end
    end

    println("✓ $(basename(in_path)) → $(out_path)")
    println("  classified: $(classified) / $(total)  (skipped bad lines: $(bad_lines))")
    return (classified=classified, total=total, bad_lines=bad_lines)
end

# ── Main ───────────────────────────────────────────────────────────────────────

function main()
    args = ARGS
    kind = "all"
    out_dir = OUT_DIR_DEFAULT
    i = 1
    while i <= length(args)
        a = args[i]
        if a == "--kind";    kind    = args[i+1]; i += 2
        elseif a == "--out-dir"; out_dir = args[i+1]; i += 2
        else; i += 1
        end
    end

    kinds = kind == "all" ? ["models", "datasets", "spaces"] : [kind]
    summary = Dict{String,Any}()

    for k in kinds
        in_path = joinpath(GENOME_DIR, "hf_$(k).jsonl")
        isfile(in_path) || (println("  skip $(in_path) (not found)"); continue)
        out_path = joinpath(out_dir, "hf_$(k)_feature_extractors.jsonl")
        try
            r = classify_file(in_path, out_path)
            summary[k] = Dict("classified"=>r.classified, "total"=>r.total, "bad_lines"=>r.bad_lines, "path"=>out_path)
        catch e
            @warn "classify failed" kind=k exception=(e, catch_backtrace())
            summary[k] = Dict("error"=>string(e))
        end
    end

    println("\nSUMMARY:"); println(JSON3.write(summary))
end

abspath(PROGRAM_FILE) == abspath(@__FILE__) && main()
