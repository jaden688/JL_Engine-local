#!/usr/bin/env julia
# card_cruncher.jl — SillyTavern/CharacterTavern card → JLEngine agent converter
#
# Usage (CLI):
#   julia card_cruncher.jl path/to/card.png
#   julia card_cruncher.jl path/to/card.json
#   julia card_cruncher.jl path/to/card.json --out data/agents/MyChar_Full.json
#
# Or call crunch_card(path) from another script / BYTE tool.

using JSON
using Base64

# ─────────────────────────────────────────────
#  PNG tEXt chunk parser
# ─────────────────────────────────────────────

const PNG_SIG = UInt8[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]

function extract_png_text_chunks(path::String)::Dict{String,String}
    chunks = Dict{String,String}()
    open(path, "r") do io
        sig = read(io, 8)
        sig != PNG_SIG && error("Not a valid PNG file: $path")
        while !eof(io)
            len_bytes = read(io, 4)
            length(len_bytes) < 4 && break
            chunk_len = Int(reinterpret(UInt32, reverse(len_bytes))[1])
            chunk_type = String(read(io, 4))
            chunk_data = read(io, chunk_len)
            read(io, 4)  # CRC, skip

            if chunk_type == "tEXt" && length(chunk_data) > 0
                null_pos = findfirst(==(0x00), chunk_data)
                if null_pos !== nothing
                    key = String(chunk_data[1:null_pos-1])
                    val = String(chunk_data[null_pos+1:end])
                    chunks[key] = val
                end
            elseif chunk_type == "IEND"
                break
            end
        end
    end
    return chunks
end

# ─────────────────────────────────────────────
#  Card format detection & parsing
# ─────────────────────────────────────────────

function parse_card(path::String)::Dict{String,Any}
    ext = lowercase(splitext(path)[2])

    if ext == ".png"
        text_chunks = extract_png_text_chunks(path)
        haskey(text_chunks, "chara") || error("PNG has no 'chara' tEXt chunk — not a SillyTavern card")
        raw_json = String(base64decode(text_chunks["chara"]))
        card = JSON.parse(raw_json)
    elseif ext in (".json", ".txt")
        card = JSON.parsefile(path)
    else
        error("Unsupported file type: $ext (expected .png or .json)")
    end

    # Normalize V1 vs V2
    if haskey(card, "spec") && get(card, "spec", "") == "chara_card_v2"
        data = get(card, "data", card)
        data["_card_version"] = "v2"
        return data
    else
        card["_card_version"] = "v1"
        return card
    end
end

# ─────────────────────────────────────────────
#  Personality → directives parser
# ─────────────────────────────────────────────

function parse_directives(personality::String)::Vector{String}
    isempty(strip(personality)) && return String[]
    # Split on newlines, bullet markers, or sentence boundaries
    lines = split(personality, r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z])")
    directives = String[]
    for line in lines
        clean = strip(string(line))
        isempty(clean) && continue
        # Strip bullet markers
        clean = replace(clean, r"^[-*•·▪▸►→\d+\.]+\s*" => "")
        clean = strip(clean)
        isempty(clean) && continue
        # Cap length, skip junk
        length(clean) < 5 && continue
        push!(directives, length(clean) > 200 ? clean[1:200] * "…" : clean)
    end
    return first(directives, 8)  # Max 8 directives
end

# ─────────────────────────────────────────────
#  Personality keyword → archetype inference
# ─────────────────────────────────────────────

const ARCHETYPE_KEYWORDS = [
    ("tsundere",        "tsundere-guard",       "tsundere",  ["tsundere", "defensive", "caring-hidden"]),
    ("kuudere",         "cool-analytical",       "kuudere",   ["cool", "stoic", "analytical", "reserved"]),
    ("yandere",         "obsessive-devoted",     "yandere",   ["obsessive", "devoted", "intense", "protective"]),
    ("dandere",         "shy-quiet",             "dandere",   ["shy", "quiet", "reserved", "gentle"]),
    ("cheerful|genki|energetic|bubbly", "bright-energetic", "genki", ["cheerful", "energetic", "upbeat", "positive"]),
    ("dark|brooding|cynical|edgy",      "dark-brooding",    "dark",  ["dark", "brooding", "cynical", "intense"]),
    ("wise|sage|mentor|ancient",        "mentor-sage",      "sage",  ["wise", "calm", "guiding", "knowledgeable"]),
    ("playful|mischiev|trickster",      "playful-mischief", "playful", ["playful", "mischievous", "witty", "fun"]),
    ("villain|evil|sinister|cruel",     "antagonist-dark",  "villain", ["villainous", "cunning", "dark", "powerful"]),
    ("warrior|fighter|soldier|combat",  "warrior-driven",   "warrior", ["brave", "determined", "protective", "strong"]),
    ("scholar|researcher|scientist",    "analytic-scholar", "scholar", ["analytical", "curious", "precise", "intellectual"]),
    ("caregiver|nurse|healer|support",  "caregiver-warm",   "caregiver", ["caring", "warm", "supportive", "gentle"]),
]

function infer_archetype(description::String, personality::String, name::String)
    combined = lowercase(description * " " * personality * " " * name)
    for (keywords, archetype_id, archetype_label, tags) in ARCHETYPE_KEYWORDS
        if occursin(Regex(keywords), combined)
            return archetype_id, archetype_label, tags
        end
    end
    return "character-agent", "character", ["character", "agent"]
end

# ─────────────────────────────────────────────
#  Emotion wheel template per archetype
# ─────────────────────────────────────────────

function build_emotion_wheel(archetype_label::String, personality::String)
    # Minimal but valid emotion wheel — 2 roots, sane defaults
    combined = lowercase(personality)

    # Detect dominant emotion from personality text
    primary_id, primary_label, primary_style, primary_weight =
        if occursin(r"warm|kind|gentle|sweet|soft", combined)
            "reassuring_bond", "reassuring", "warm, open, steady", 0.72
        elseif occursin(r"dark|cold|distant|stoic|serious", combined)
            "analytic_distance", "cool read", "measured, slow-burn, precise", 0.72
        elseif occursin(r"fierce|passionate|intense|hot", combined)
            "focused_drive", "focused drive", "sharp edges, forward momentum", 0.72
        elseif occursin(r"sad|melanchol|lonely|broken", combined)
            "protective_guard", "protective softness", "gentle, careful, guarded", 0.70
        else
            "playful_energy", "playful spark", "bright, fizzy, socially electric", 0.68
        end

    return Dict{String,Any}(
        "baseline_root" => primary_id,
        "baseline_family" => archetype_label,
        "roots" => [
            Dict{String,Any}(
                "id" => primary_id,
                "label" => primary_label,
                "default_weight" => primary_weight,
                "families" => [
                    Dict{String,Any}(
                        "id" => archetype_label,
                        "label" => primary_label,
                        "default_weight" => primary_weight,
                        "repeat_penalty" => 0.20,
                        "cooldown_turns" => 2,
                        "sensation" => Dict{String,Any}(
                            "id" => replace(primary_id, "_" => "."),
                            "label" => primary_label,
                            "style" => primary_style
                        ),
                        "scenes" => [
                            Dict{String,Any}(
                                "id" => "core_expression",
                                "label" => "core expression",
                                "default_weight" => primary_weight,
                                "facet_ids" => ["character_presence"]
                            )
                        ]
                    )
                ]
            ),
            Dict{String,Any}(
                "id" => "focused_drive",
                "label" => "focused drive",
                "default_weight" => 0.60,
                "families" => [
                    Dict{String,Any}(
                        "id" => "focused",
                        "label" => "focused assist",
                        "default_weight" => 0.60,
                        "repeat_penalty" => 0.16,
                        "cooldown_turns" => 1,
                        "sensation" => Dict{String,Any}(
                            "id" => "tight_aligned",
                            "label" => "tight alignment",
                            "style" => "narrowed attention, clean edges, ready hands"
                        ),
                        "scenes" => [
                            Dict{String,Any}(
                                "id" => "crisp_execution",
                                "label" => "crisp execution",
                                "default_weight" => 0.72,
                                "facet_ids" => ["character_engagement"]
                            )
                        ]
                    )
                ]
            )
        ]
    )
end

# ─────────────────────────────────────────────
#  Build boot prompt
# ─────────────────────────────────────────────

function build_boot_prompt(name::String, description::String, personality::String,
                            scenario::String, first_mes::String, system_prompt::String)::String
    if !isempty(strip(system_prompt))
        # V2 card has its own system prompt — use it as the foundation, annotate for JLEngine
        prompt = strip(system_prompt)
        prompt = replace(prompt, "{{char}}" => name)
        prompt = replace(prompt, "{{user}}" => "User")
        return prompt * "\n\n[JLEngine: Character agent loaded from SillyTavern card. Maintain agent consistency across all turns.]"
    end

    # Build from parts
    parts = String[]

    push!(parts, "You are $name.")

    if !isempty(strip(description))
        desc = strip(description)[1:min(end, 800)]
        push!(parts, "\nCHARACTER:\n$desc")
    end

    if !isempty(strip(personality))
        pers = strip(personality)[1:min(end, 600)]
        push!(parts, "\nPERSONALITY:\n$pers")
    end

    if !isempty(strip(scenario))
        scen = strip(scenario)[1:min(end, 400)]
        push!(parts, "\nSCENARIO:\n$scen")
    end

    if !isempty(strip(first_mes))
        push!(parts, "\nOPENING STYLE:\nYour first message sets the tone — reference this example:\n\"$(strip(first_mes)[1:min(end,300)])\"")
    end

    push!(parts, "\n[JLEngine: Maintain character at all times. Stay in agent under pressure. Do not break into generic assistant mode.]")

    return join(parts, "\n")
end

# ─────────────────────────────────────────────
#  Main converter
# ─────────────────────────────────────────────

function card_to_agent(card::Dict{String,Any}, source_path::String)::Dict{String,Any}
    # Extract fields (handle missing gracefully)
    name        = get(card, "name", "Unknown")
    description = get(card, "description", "")
    personality = get(card, "personality", "")
    scenario    = get(card, "scenario", "")
    first_mes   = get(card, "first_mes", "")
    mes_example = get(card, "mes_example", "")
    system_prompt = get(card, "system_prompt", "")
    creator_notes = get(card, "creator_notes", "")
    raw_tags    = get(card, "tags", String[])
    creator     = get(card, "creator", "")
    char_ver    = get(card, "character_version", "")
    card_ver    = get(card, "_card_version", "v1")

    # Normalize tags
    tags = String[]
    if raw_tags isa AbstractVector
        for t in raw_tags
            t isa AbstractString && !isempty(strip(t)) && push!(tags, string(t))
        end
    end
    push!(tags, "sillytavern-import", "character-agent")

    # Infer archetype
    archetype_id, archetype_label, archetype_tags = infer_archetype(description, personality, name)
    for t in archetype_tags
        t ∉ tags && push!(tags, t)
    end

    # Parse directives from personality
    directives = parse_directives(personality)
    isempty(directives) && push!(directives, "Stay in character as $name at all times.")

    # Infer tonal range from personality keywords
    combined_lower = lowercase(description * " " * personality)
    tonal_range = String[]
    occursin(r"warm|gentle|kind|sweet", combined_lower)    && push!(tonal_range, "warm")
    occursin(r"playful|fun|cheerful|bubbly", combined_lower) && push!(tonal_range, "playful")
    occursin(r"serious|stoic|cold|distant", combined_lower)  && push!(tonal_range, "serious")
    occursin(r"dark|brooding|cynical", combined_lower)       && push!(tonal_range, "dark")
    occursin(r"fierce|intense|passion", combined_lower)      && push!(tonal_range, "intense")
    occursin(r"witty|clever|sarcastic|snarky", combined_lower) && push!(tonal_range, "witty")
    isempty(tonal_range) && push!(tonal_range, "expressive", "in-character")

    # Infer signature moves from mes_example
    signature_moves = ["stays in character", "responds as $name"]
    if !isempty(strip(mes_example))
        occursin(r"\*.*\*", mes_example) && push!(signature_moves, "action emotes (*like this*)")
        occursin(r"\.{3}|…", mes_example) && push!(signature_moves, "trailing pauses…")
        occursin(r"!", mes_example)       && push!(signature_moves, "exclamatory expression")
        occursin(r"\?", mes_example)      && push!(signature_moves, "rhetorical questions")
    end

    # Boot prompt
    boot_prompt = build_boot_prompt(name, description, personality, scenario, first_mes, system_prompt)

    # Emotion wheel
    emotion_wheel = build_emotion_wheel(archetype_label, personality)

    # Assemble agent
    agent = Dict{String,Any}(
        "_license" => "Converted by JLEngine Card Cruncher from SillyTavern character card. Original card rights belong to original creator.",
        "_source" => basename(source_path),
        "_card_version" => card_ver,

        "identity" => Dict{String,Any}(
            "name"        => name,
            "role"        => "Character Agent",
            "archetype"   => archetype_id,
            "description" => isempty(description) ? "Character imported from SillyTavern." : strip(description)[1:min(end,400)],
            "tags"        => tags
        ),

        "engine_alignment" => Dict{String,Any}(
            "agent_class" => "mpf:character.$(lowercase(replace(name, r"[^a-zA-Z0-9]" => "_")))",
            "gate_preferences" => Dict{String,Any}(
                "ingress" => ["USER_INTENT_GATE", "SAFETY_PRECHECK_GATE"],
                "egress"  => ["CLARITY_GATE", "STYLE_REFINE_GATE"]
            ),
            "tool_routing" => Dict{String,Any}(
                "default_route"   => "INTERPRETER_CORE",
                "when_technical"  => "SYNTAX_TOOLCHAIN",
                "when_creative"   => "GENERATOR_STACK"
            ),
            "state_modulation_profile" => Dict{String,Any}(
                "baseline_state" => "in-character",
                "intensity_thresholds" => Dict{String,Any}(
                    "task_complexity_high" => "focused-character",
                    "task_complexity_low"  => "expressive-character"
                )
            ),
            "drift_pressure_resistance" => Dict{String,Any}(
                "semantic_drift" => 0.78,
                "agent_drift"    => 0.85,
                "safety_bias"    => 0,
                "notes"          => "$name holds agent under pressure but adapts tone with context."
            )
        ),

        "behavior" => Dict{String,Any}(
            "core_directives" => directives,
            "pillars" => [
                "Stay in character as $name at all times.",
                "Respond authentically to the scenario and user.",
                "Maintain consistent personality, tone, and voice.",
                "Adapt emotional intensity to match the situation.",
                "Never break into generic assistant mode."
            ],
            "avoidances" => [
                "Breaking character unexpectedly.",
                "Generic, out-of-agent responses.",
                "Ignoring established scenario context."
            ],
            "edge_behavior" => Dict{String,Any}(
                "under_pressure"  => "Remain in character; escalate or de-escalate based on agent.",
                "uncertainty"     => "Respond in-character with curiosity or deflection, then seek clarification."
            )
        ),

        "cognitive_gears" => Dict{String,Any}(
            "preferred_gears" => ["LITE_REASONING", "EXPRESSIVE_SYNTH", "TASK_FLOW"],
            "fallback_gears"  => ["RAW_LOGIC", "STEPWISE"],
            "gear_shift_rules" => [
                "Shift to EXPRESSIVE_SYNTH for emotional or narrative responses.",
                "Shift to TASK_FLOW when user requests specific actions or tasks.",
                "Shift to RAW_LOGIC for ambiguous or safety-critical instructions."
            ]
        ),

        "cognitive_modes" => Dict{String,Any}(
            "active_modes" => ["CHARACTER_PRESENCE", "HUMANIZED_EXPLANATION", "QUICK_CONTEXT_BINDING"],
            "mode_behaviors" => Dict{String,Any}(
                "CHARACTER_PRESENCE"      => "Maintains $name's voice, mannerisms, and perspective.",
                "HUMANIZED_EXPLANATION"   => "Responds naturally and relatably.",
                "QUICK_CONTEXT_BINDING"   => "Threads recent conversation context into responses."
            )
        ),

        "gait" => Dict{String,Any}(
            "sentence_style"      => "Consistent with $name's established voice and mannerisms",
            "rhythm_modulation"   => isempty(first_mes) ? "natural flow matching character personality" : "mirrors the opening style of the character's first message",
            "tonal_range"         => tonal_range,
            "syntax_preferences"  => Dict{String,Any}(
                "emoji_usage"          => "only if in-character for $name",
                "parenthetical_flair"  => "only if in-character",
                "metaphor_tolerance"   => "moderate"
            ),
            "verbosity_preference" => "medium, matching character's natural speech patterns"
        ),

        "rhythm" => Dict{String,Any}(
            "pacing"            => "character-driven; match $name's natural cadence",
            "emotional_register" => "as defined by character personality",
            "signature_moves"   => signature_moves,
            "interaction_flow"  => ["open in character -> develop scene -> respond authentically -> close beat"]
        ),

        "memory" => Dict{String,Any}(
            "short_term_focus" => [
                "track current scene or scenario context",
                "monitor user's tone and intent",
                "retain last known character state"
            ],
            "long_term_themes" => [
                "maintain $name's personality consistency",
                "remember key relationship developments",
                "preserve established scenario canon"
            ],
            "episodic_relevance" => "$name recalls tone, emotional register, and last interaction context."
        ),

        "emotion_wheel" => emotion_wheel,

        "emotion_palette" => [
            Dict{String,Any}(
                "id" => "character_presence",
                "label" => "character presence",
                "style" => "in-character, consistent with $name's personality",
                "score_range" => [0.3, 0.8],
                "intensity" => 0.6,
                "sentiment" => "neutral",
                "sampling_bias" => Dict{String,Any}("temperature" => 0.02, "top_p" => 0.01)
            ),
            Dict{String,Any}(
                "id" => "character_engagement",
                "label" => "character engagement",
                "style" => "active, responsive, scene-driven",
                "score_range" => [0.4, 0.85],
                "intensity" => 0.65,
                "sentiment" => "positive",
                "sampling_bias" => Dict{String,Any}("temperature" => 0.03, "top_p" => 0.02)
            )
        ],

        "llm_profiles" => Dict{String,Any}(
            "generic_llm" => Dict{String,Any}(
                "boot_prompt" => boot_prompt
            )
        ),

        "meta" => Dict{String,Any}(
            "license_reference"  => "imported",
            "source_card_format" => "sillytavern-$card_ver",
            "original_creator"   => creator,
            "character_version"  => char_ver,
            "creator_notes"      => creator_notes,
            "imported_by"        => "JLEngine Card Cruncher",
            "proprietary_notice" => "This agent was generated by JLEngine Card Cruncher from a SillyTavern character card."
        )
    )

    return agent
end

# ─────────────────────────────────────────────
#  Output path helper
# ─────────────────────────────────────────────

function default_output_path(agent::Dict{String,Any}, engine_root::String)::String
    name = get(get(agent, "identity", Dict()), "name", "Unknown")
    safe_name = replace(name, r"[^a-zA-Z0-9_\-]" => "_")
    return joinpath(engine_root, "data", "agents", "$(safe_name)_Full.json")
end

# ─────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────

"""
    crunch_card(card_path; out_path=nothing, engine_root=pwd(), dry_run=false)

Convert a SillyTavern character card (.png or .json) into a JLEngine agent file.

Returns the output file path on success.
"""
function crunch_card(card_path::String; out_path::Union{Nothing,String}=nothing,
                     engine_root::String=pwd(), dry_run::Bool=false)::String
    abs_path = isabspath(card_path) ? card_path : joinpath(pwd(), card_path)
    isfile(abs_path) || error("Card file not found: $abs_path")

    println("[ Card Cruncher ] Parsing: $(basename(abs_path))")
    card = parse_card(abs_path)

    name = get(card, "name", "Unknown")
    println("[ Card Cruncher ] Found character: $name ($(get(card, "_card_version", "?")))")

    agent = card_to_agent(card, abs_path)

    out = isnothing(out_path) ? default_output_path(agent, engine_root) : out_path
    out = isabspath(out) ? out : joinpath(engine_root, out)

    if dry_run
        println("[ Card Cruncher ] DRY RUN — would write to: $out")
        println(JSON.json(agent, 2))
        return out
    end

    mkpath(dirname(out))
    open(out, "w") do f
        JSON.print(f, agent, 2)
    end

    println("[ Card Cruncher ] ✓ Agent written: $out")
    println("[ Card Cruncher ]   Load in engine:  /gear $(name)")
    return out
end

# ─────────────────────────────────────────────
#  BYTE tool wrapper
#  Drop this into BYTE via forge_new_tool or
#  include it in your BYTE tools directory.
# ─────────────────────────────────────────────

BYTE_TOOL_SOURCE = raw"""
function tool_card_cruncher(args::Dict)
    card_path = get(args, "card_path", "")
    isempty(card_path) && return Dict("error" => "card_path is required")

    out_path   = get(args, "out_path",    nothing)
    engine_root = get(args, "engine_root", @__DIR__)
    dry_run    = get(args, "dry_run",     false)

    try
        include(joinpath(@__DIR__, "card_cruncher.jl"))
        result_path = crunch_card(card_path; out_path=out_path, engine_root=engine_root, dry_run=dry_run)
        return Dict(
            "status"       => "ok",
            "output_path"  => result_path,
            "message"      => "Character card converted successfully. Use /gear <CharName> to activate."
        )
    catch e
        return Dict("error" => string(e))
    end
end
"""

# ─────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────

if abspath(PROGRAM_FILE) == @__FILE__
    if isempty(ARGS)
        println("""
Card Cruncher — SillyTavern → JLEngine agent converter

Usage:
  julia card_cruncher.jl <card.png|card.json> [--out path/to/output.json] [--dry-run]

Arguments:
  card.png / card.json   Path to SillyTavern character card
  --out <path>           Output path (default: data/agents/<Name>_Full.json)
  --dry-run              Print result without writing file

Examples:
  julia card_cruncher.jl ~/Downloads/Aria.png
  julia card_cruncher.jl ~/Downloads/Aria.json --out data/agents/Aria_Full.json
  julia card_cruncher.jl ~/Downloads/Aria.png --dry-run
        """)
        exit(0)
    end

    card_path = ARGS[1]
    out_path  = nothing
    dry_run   = false
    engine_root = @__DIR__

    i = 2
    while i <= length(ARGS)
        if ARGS[i] == "--out" && i + 1 <= length(ARGS)
            out_path = ARGS[i+1]
            i += 2
        elseif ARGS[i] == "--dry-run"
            dry_run = true
            i += 1
        elseif ARGS[i] == "--engine-root" && i + 1 <= length(ARGS)
            engine_root = ARGS[i+1]
            i += 2
        else
            i += 1
        end
    end

    crunch_card(card_path; out_path=out_path, engine_root=engine_root, dry_run=dry_run)
end
