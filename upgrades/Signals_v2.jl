# upgrades/Signals_v2.jl
# Upgraded SignalScorer with Weighted Dictionaries and Phrase Detection

# 1. Exact Word Weights (No more flat +1 / -1)
const WORD_WEIGHTS = Dict{String, Float64}(
    "great" => 0.5, "awesome" => 0.8, "excellent" => 0.8, "good" => 0.3,
    "bad" => -0.5, "hate" => -0.8, "awful" => -0.8, "terrible" => -0.8,
    "annoyed" => -0.4, "frustrated" => -0.6, "happy" => 0.6, "love" => 0.8,
    "okay" => 0.1, "fine" => 0.1, "shit" => -0.7, "fuck" => -0.5,
    "brilliant" => 0.9, "broken" => -0.6, "issue" => -0.3, "solve" => 0.4
)

# 2. Phrase Weights (Combinations of words!)
const PHRASE_WEIGHTS = Dict{String, Float64}(
    "fucking hate" => -1.5,
    "absolutely brilliant" => 1.5,
    "kind of annoyed" => -0.3,
    "not sure" => -0.2,
    "very happy" => 1.0,
    "piece of shit" => -1.5,
    "blows my mind" => 1.2,
    "thank you so much" => 1.0
)

# 3. Confusion Weights (Also supports phrases now)
const CONFUSION_WEIGHTS = Dict{String, Float64}(
    "confused" => 0.8, "lost" => 0.6, "stuck" => 0.7, "unclear" => 0.5,
    "don't get it" => 0.9, "makes no sense" => 0.9, "huh" => 0.4,
    "what do you mean" => 0.8
)

const DIRECTIVE_PHRASES = [
    "be concise", "just answer", "short answer", "no fluff", "get to the point"
]

struct SignalScorer end

function _clamp_unit(value::Real)
    return max(0.0, min(1.0, Float64(value)))
end

function score(::SignalScorer, text::AbstractString)
    lowered = lowercase(text)
    
    sentiment_score = 0.0
    confusion_score = 0.0
    
    # STEP 1: Check for exact phrases first
    for (phrase, weight) in PHRASE_WEIGHTS
        if occursin(phrase, lowered)
            sentiment_score += weight
            # Remove the phrase so we don't double-count its individual words
            lowered = replace(lowered, phrase => "")
        end
    end
    
    for (phrase, weight) in CONFUSION_WEIGHTS
        if occursin(phrase, lowered)
            confusion_score += weight
            lowered = replace(lowered, phrase => "")
        end
    end

    # STEP 2: Check individual words
    words = [String(match.match) for match in eachmatch(r"[a-z']+", lowered)]
    wlen = max(1, length(words)) # avoid division by zero
    
    for word in words
        sentiment_score += get(WORD_WEIGHTS, word, 0.0)
        confusion_score += get(CONFUSION_WEIGHTS, word, 0.0)
    end

    # STEP 3: Normalize Sentiment
    # Instead of flat counting, we scale it. A score of +5.0 or -5.0 maxes it out.
    sentiment = max(-1.0, min(1.0, sentiment_score / 5.0))

    # STEP 4: Directive Check
    directive = any(phrase -> occursin(phrase, lowered), DIRECTIVE_PHRASES)
    
    # STEP 5: Confusion Math
    confusion_score += count(==('?'), text) * 0.2
    confusion = _clamp_unit(confusion_score / 3.0)

    # STEP 6: Arousal Math (NERFED THE EXCLAMATION POINTS!)
    exclaim = count(==('!'), text)
    upper_hits = count(c -> isuppercase(c), text)
    
    # Base word length arousal + 10% for first '!', 2% for each after + 10% if heavy uppercase
    arousal_raw = (wlen * 0.02) + (exclaim > 0 ? 0.10 : 0.0) + max(0, exclaim - 1) * 0.02 + (upper_hits > 5 ? 0.10 : 0.0)
    arousal = _clamp_unit(arousal_raw)

    # STEP 7: Pace & Memory Density
    pace = _clamp_unit((min(wlen, 30) / 30.0) + (exclaim > 0 ? 0.05 : 0.0))
    memory_density = _clamp_unit((wlen / 35.0) + (confusion_score * 0.05))

    return TurnSignals(sentiment, arousal, directive, confusion, pace, memory_density)
end
