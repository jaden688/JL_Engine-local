function _default_signal_config()
    return Dict{String, Any}(
        "sentiment" => Dict{String, Any}(
            "words" => Dict{String, Any}(
                "awesome" => 0.8, "great" => 0.6, "good" => 0.35, "love" => 0.8,
                "brilliant" => 0.9, "thanks" => 0.45, "hate" => -0.9,
                "awful" => -0.8, "terrible" => -0.8, "broken" => -0.55,
                "frustrated" => -0.75, "annoyed" => -0.55,
            ),
            "phrases" => Dict{String, Any}(
                "thank you so much" => 0.9, "this is awesome" => 0.8,
                "makes no sense" => -0.65, "fucking hate" => -1.1,
            ),
            "negators" => Any["not", "never", "no", "hardly"],
        ),
        "arousal" => Dict{String, Any}(
            "words" => Dict{String, Any}(
                "fuck" => 0.16, "fucking" => 0.18, "urgent" => 0.30,
                "now" => 0.12, "amazing" => 0.18, "broken" => 0.12,
            ),
            "phrases" => Dict{String, Any}(
                "right now" => 0.22, "oh my god" => 0.22,
            ),
        ),
        "confusion" => Dict{String, Any}(
            "words" => Dict{String, Any}(
                "confused" => 0.9, "unclear" => 0.7, "lost" => 0.65,
                "stuck" => 0.65, "huh" => 0.55,
            ),
            "phrases" => Dict{String, Any}(
                "don't get it" => 1.0, "doesn't make sense" => 1.0,
                "makes no sense" => 1.0, "what do you mean" => 0.9,
            ),
        ),
        "distress" => Dict{String, Any}(
            "words" => Dict{String, Any}(
                "panic" => 0.9, "scared" => 0.8, "afraid" => 0.8,
                "overwhelmed" => 0.9, "hurt" => 0.7, "depressed" => 0.8,
            ),
            "phrases" => Dict{String, Any}(
                "can't handle" => 0.9, "freaking out" => 1.0,
            ),
        ),
        "playfulness" => Dict{String, Any}(
            "words" => Dict{String, Any}(
                "lol" => 0.8, "lmao" => 1.0, "haha" => 0.8,
                "joking" => 0.75, "hilarious" => 0.7,
            ),
            "phrases" => Dict{String, Any}(
                ":3" => 0.8, "😈" => 0.65, "😂" => 0.8,
            ),
        ),
        "directive" => Dict{String, Any}(
            "phrases" => Any[
                "can you", "could you", "would you", "please", "i need you to",
                "tell me", "show me", "go ahead", "just answer", "check this",
            ],
            "leading_verbs" => Any[
                "analyze", "build", "check", "create", "explain", "find", "fix",
                "inspect", "look", "make", "read", "run", "show", "tell", "write",
            ],
        ),
        "memory_markers" => Any[
            "before", "earlier", "remember", "again", "previous", "still",
            "already", "continue", "database", "telemetry", "context",
        ],
    )
end

struct SignalScorer
    config::Dict{String, Any}
end

SignalScorer() = SignalScorer(_default_signal_config())

function SignalScorer(config_path::AbstractString)
    loaded = load_json_safely(config_path)
    config = isempty(loaded) ? _default_signal_config() : loaded
    return SignalScorer(Dict{String, Any}(string(key) => value for (key, value) in pairs(config)))
end

_clamp_unit(value::Real) = clamp(Float64(value), 0.0, 1.0)

function _signal_section(scorer::SignalScorer, name::AbstractString)
    raw = get(scorer.config, String(name), Dict{String, Any}())
    return raw isa AbstractDict ? raw : Dict{String, Any}()
end

function _signal_weights(section, key::AbstractString)
    raw = section isa AbstractDict ? get(section, String(key), Dict{String, Any}()) : Dict{String, Any}()
    raw isa AbstractDict || return Dict{String, Float64}()
    weights = Dict{String, Float64}()
    for (token, value) in pairs(raw)
        parsed = value isa Real ? Float64(value) : tryparse(Float64, string(value))
        parsed === nothing || (weights[lowercase(String(token))] = parsed)
    end
    return weights
end

function _signal_strings(section, key::AbstractString)
    raw = section isa AbstractDict ? get(section, String(key), Any[]) : Any[]
    raw isa AbstractVector || return String[]
    return [lowercase(String(value)) for value in raw if value isa AbstractString]
end

function _phrase_score(text::AbstractString, weights::Dict{String, Float64})
    total = 0.0
    for (phrase, weight) in weights
        occursin(phrase, text) && (total += weight)
    end
    return total
end

function _word_score(words::Vector{String}, weights::Dict{String, Float64}; negators=Set{String}())
    total = 0.0
    for (index, word) in pairs(words)
        weight = get(weights, word, 0.0)
        if weight != 0.0 && index > 1 && words[index - 1] in negators
            weight *= -0.85
        end
        total += weight
    end
    return total
end

function _dimension_score(scorer::SignalScorer, name::AbstractString, lowered::AbstractString, words::Vector{String}; negate=false)
    section = _signal_section(scorer, name)
    word_weights = _signal_weights(section, "words")
    phrase_weights = _signal_weights(section, "phrases")
    negators = negate ? Set(_signal_strings(section, "negators")) : Set{String}()
    return _phrase_score(lowered, phrase_weights) + _word_score(words, word_weights; negators=negators)
end

function _is_directive(scorer::SignalScorer, lowered::AbstractString, words::Vector{String})
    section = _signal_section(scorer, "directive")
    phrases = _signal_strings(section, "phrases")
    any(phrase -> occursin(phrase, lowered), phrases) && return true
    isempty(words) && return false
    return first(words) in Set(_signal_strings(section, "leading_verbs"))
end

function score(scorer::SignalScorer, text::AbstractString)
    lowered = lowercase(text)
    words = [String(match.match) for match in eachmatch(r"[a-z']+", lowered)]
    word_count = length(words)

    sentiment_raw = _dimension_score(scorer, "sentiment", lowered, words; negate=true)
    sentiment = clamp(tanh(sentiment_raw / 1.15), -1.0, 1.0)

    confusion_raw = _dimension_score(scorer, "confusion", lowered, words)
    question_count = count(==('?'), text)
    confusion = _clamp_unit(confusion_raw + min(question_count, 3) * 0.06)

    distress_raw = _dimension_score(scorer, "distress", lowered, words)
    distress = _clamp_unit(distress_raw)

    playfulness_raw = _dimension_score(scorer, "playfulness", lowered, words)
    playfulness = _clamp_unit(playfulness_raw)

    arousal_lexical = max(0.0, _dimension_score(scorer, "arousal", lowered, words))
    exclaim_count = count(==('!'), text)
    letter_count = count(isletter, text)
    uppercase_count = count(isuppercase, text)
    uppercase_ratio = letter_count == 0 ? 0.0 : uppercase_count / letter_count
    punctuation_burst = occursin(r"[!?]{2,}", text) ? 0.08 : 0.0
    repeated_character = occursin(r"(.)\1{2,}", lowered) ? 0.06 : 0.0
    length_energy = min(word_count, 60) / 60.0 * 0.16
    arousal = _clamp_unit(
        length_energy +
        arousal_lexical +
        min(exclaim_count, 4) * 0.08 +
        min(question_count, 4) * 0.015 +
        min(uppercase_ratio, 0.55) * 0.42 +
        punctuation_burst +
        repeated_character
    )

    punctuation_count = exclaim_count + question_count + count(==('…'), text)
    pace = _clamp_unit(
        min(word_count, 55) / 55.0 * 0.34 +
        min(punctuation_count, 8) * 0.035 +
        punctuation_burst +
        repeated_character
    )

    marker_values = get(scorer.config, "memory_markers", Any[])
    memory_markers = marker_values isa AbstractVector ?
        Set(lowercase(String(value)) for value in marker_values if value isa AbstractString) :
        Set{String}()
    reference_hits = count(word -> word in memory_markers, words)
    memory_density = _clamp_unit(min(word_count / 90.0, 0.78) + min(reference_hits, 4) * 0.07)

    directive = _is_directive(scorer, lowered, words)
    return TurnSignals(
        sentiment,
        arousal,
        directive,
        confusion,
        pace,
        memory_density,
        playfulness,
        distress,
    )
end

"""
    derive_trigger(signals) -> String

Describe why the engine is moving. The trigger is diagnostic input semantics;
it is not the personality state itself. Personality is selected by grid number.
"""
function derive_trigger(signals::TurnSignals)
    signals.distress >= 0.68 && signals.confusion >= 0.35 && return "user_overwhelmed"
    signals.distress >= 0.68 && return "user_distressed"
    signals.confusion >= 0.58 && return "user_confused"
    signals.sentiment <= -0.32 && signals.arousal >= 0.28 && return "user_frustrated"
    signals.sentiment >= 0.45 && signals.arousal >= 0.45 && return "user_hyped"
    signals.playfulness >= 0.52 && return "user_joking"
    signals.directive && return "user_directive"
    signals.sentiment <= -0.25 && signals.arousal < 0.28 && return "user_serious_or_tired"
    (signals.pace >= 0.38 || signals.memory_density >= 0.42 || signals.arousal >= 0.34) && return "user_engaged"
    return "neutral"
end

"""
    behavior_intensity(signals) -> Float64

Project input signals onto the grid's full 0–1 intensity axis. The continuous
baseline and weighted dimensions keep all five rows naturally reachable.
"""
function behavior_intensity(signals::TurnSignals)
    raw_activity = (
        abs(signals.sentiment) +
        signals.arousal +
        signals.confusion +
        signals.pace +
        signals.playfulness +
        signals.distress +
        (signals.directive ? 0.25 : 0.0)
    )
    raw_activity <= 0.03 && return 0.05
    return _clamp_unit(
        0.18 +
        signals.arousal * 0.48 +
        signals.pace * 0.16 +
        abs(signals.sentiment) * 0.08 +
        signals.playfulness * 0.08 +
        signals.distress * 0.08 +
        signals.confusion * 0.05 +
        (signals.directive ? 0.08 : 0.0)
    )
end

behavior_row(signals::TurnSignals) = clamp(floor(Int, behavior_intensity(signals) * 5), 0, 4)

function infer_gait(signals::TurnSignals)
    signals.confusion >= 0.72 && signals.arousal < 0.35 && return "idle"
    intensity = behavior_intensity(signals)
    intensity >= 0.80 && return "sprint"
    intensity >= 0.60 && return "trot"
    intensity < 0.20 && return "idle"
    return "walk"
end
