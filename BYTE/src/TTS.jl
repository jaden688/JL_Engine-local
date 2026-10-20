using Base64

const _TTS_DEFAULT_MODEL = "gpt-4o-mini-tts"
const _TTS_DEFAULT_VOICE = "cedar"
const _TTS_DEFAULT_INSTRUCTIONS = "Tone: clear, warm, and lightly playful. Pacing: steady."
const _TTS_MAX_CHARS = 3800
const _TTS_VOICES = Set([
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
    "onyx", "sage", "shimmer", "verse", "marin", "cedar",
])

# Per-websocket speech queues keep replies in order even when generation is async.
const _TTS_STATE = Dict{UInt64, Dict{Symbol,Any}}()
const _TTS_STATE_LOCK = ReentrantLock()

function _tts_env_bool(name::AbstractString; default::Bool=false)
    value = lowercase(strip(get(ENV, name, default ? "1" : "0")))
    return !(value in ("", "0", "false", "no", "off"))
end

function _tts_enabled()::Bool
    _tts_env_bool("SPARKBYTE_TTS_ENABLED"; default=false)
end

function _tts_voice()::String
    voice = lowercase(strip(get(ENV, "SPARKBYTE_TTS_VOICE", _TTS_DEFAULT_VOICE)))
    return voice in _TTS_VOICES ? voice : _TTS_DEFAULT_VOICE
end

function _tts_model()::String
    model = strip(get(ENV, "SPARKBYTE_TTS_MODEL", _TTS_DEFAULT_MODEL))
    isempty(model) ? _TTS_DEFAULT_MODEL : model
end

function _tts_instructions()::String
    instructions = strip(get(ENV, "SPARKBYTE_TTS_INSTRUCTIONS", _TTS_DEFAULT_INSTRUCTIONS))
    isempty(instructions) ? _TTS_DEFAULT_INSTRUCTIONS : instructions
end

function _tts_plaintext(text::AbstractString)
    s = String(text)
    s = replace(s, r"```[\s\S]*?```" => " [code block] ")
    s = replace(s, r"`([^`]+)`" => m -> match(r"`([^`]+)`", m).captures[1])
    s = replace(s, r"\[([^\]]+)\]\(([^)]+)\)" => m -> match(r"\[([^\]]+)\]\(([^)]+)\)", m).captures[1])
    s = replace(s, r"(?m)^\s{0,3}#{1,6}\s+" => "")
    s = replace(s, r"(?m)^\s*[-*+]\s+" => "")
    s = replace(s, r"(?m)^\s*>\s+" => "")
    s = replace(s, r"[*_~]+" => "")
    s = replace(s, r"[ \t\r\n]+" => " ")
    return strip(s)
end

function _tts_chunks(text::AbstractString; max_chars::Int=_TTS_MAX_CHARS)
    cleaned = _tts_plaintext(text)
    isempty(cleaned) && return String[]

    chunks = String[]
    current = IOBuffer()
    current_len = 0

    for token in split(cleaned)
        token_len = length(token)
        if token_len > max_chars
            if current_len > 0
                push!(chunks, String(take!(current)))
                current = IOBuffer()
                current_len = 0
            end
            remaining = token
            while !isempty(remaining)
                if length(remaining) <= max_chars
                    push!(chunks, remaining)
                    remaining = ""
                else
                    stop = nextind(remaining, firstindex(remaining), max_chars)
                    push!(chunks, remaining[firstindex(remaining):prevind(remaining, stop)])
                    remaining = remaining[stop:end]
                end
            end
            continue
        end

        add_len = current_len == 0 ? token_len : token_len + 1
        if current_len > 0 && current_len + add_len > max_chars
            push!(chunks, String(take!(current)))
            current = IOBuffer()
            current_len = 0
        end
        if current_len > 0
            write(current, ' ')
            current_len += 1
        end
        write(current, token)
        current_len += token_len
    end

    if current_len > 0
        push!(chunks, String(take!(current)))
    end

    filter!(chunk -> !isempty(strip(chunk)), chunks)
    return chunks
end

function _tts_state_for_ws(ws; create::Bool=true)
    cid = UInt64(objectid(ws))
    lock(_TTS_STATE_LOCK) do
        state = get(_TTS_STATE, cid, nothing)
        if state === nothing && create
            state = Dict{Symbol,Any}()
            _TTS_STATE[cid] = state
        end
        return state
    end
end

function _tts_api_key()::String
    # Prefer a dedicated TTS key so OPENAI_API_KEY can stay clean for chat routing
    k = strip(get(ENV, "OPENAI_TTS_API_KEY", ""))
    isempty(k) && (k = strip(get(ENV, "OPENAI_API_KEY", "")))
    return k
end

function _tts_generate_audio(text::AbstractString; model::String=_tts_model(), voice::String=_tts_voice(), instructions::String=_tts_instructions())
    api_key = _tts_api_key()
    isempty(api_key) && return Dict("error" => "Set OPENAI_TTS_API_KEY (or OPENAI_API_KEY) for voice.")

    payload = Dict{String,Any}(
        "model" => isempty(model) ? _TTS_DEFAULT_MODEL : model,
        "input" => String(text),
        "voice" => voice,
        "response_format" => "mp3",
    )
    !isempty(instructions) && (payload["instructions"] = instructions)

    headers = Pair{String,String}[
        "Content-Type" => "application/json",
        "Authorization" => "Bearer $api_key",
    ]

    resp = try
        HTTP.post("https://api.openai.com/v1/audio/speech", headers, JSON.json(payload); status_exception=false)
    catch e
        return Dict("error" => "OpenAI TTS request failed: $(first(string(e), 240))")
    end

    if resp.status != 200
        body_text = String(resp.body)
        err_msg = try
            obj = JSON.parse(body_text)
            string(get(get(obj, "error", Dict{String,Any}()), "message", body_text))
        catch
            body_text
        end
        return Dict("error" => "OpenAI TTS request failed (status $(resp.status)): $(first(err_msg, 240))")
    end

    return Dict(
        "audio_b64" => Base64.base64encode(resp.body),
        "mime_type" => "audio/mpeg",
    )
end

function _tts_worker_loop(ws, queue::Channel{Dict{String,Any}})
    try
        for job in queue
            try
                if !_tts_enabled()
                    continue
                end

                chunks = get(job, "chunks", String[])
                isempty(chunks) && continue

                voice = string(get(job, "voice", _tts_voice()))
                model = string(get(job, "model", _tts_model()))
                instructions = string(get(job, "instructions", _tts_instructions()))
                turn_id = get(job, "turn_id", 0)
                total = length(chunks)

                for (idx, chunk) in enumerate(chunks)
                    result = _tts_generate_audio(chunk; model=model, voice=voice, instructions=instructions)
                    if haskey(result, "error")
                        _ws_send(ws, Dict(
                            "type" => "speech_error",
                            "turn_id" => turn_id,
                            "chunk_index" => idx,
                            "text" => string(result["error"]),
                        ))
                        break
                    end

                    _ws_send(ws, Dict(
                        "type" => "speech",
                        "turn_id" => turn_id,
                        "chunk_index" => idx,
                        "chunk_count" => total,
                        "voice" => voice,
                        "mime_type" => get(result, "mime_type", "audio/mpeg"),
                        "audio_b64" => get(result, "audio_b64", ""),
                        "text_preview" => first(chunk, 160),
                    ))
                end
            catch e
                @warn "TTS worker job failed" exception=(e, catch_backtrace())
                try
                    _ws_send(ws, Dict(
                        "type" => "speech_error",
                        "text" => "Voice generation failed: $(first(string(e), 200))",
                    ))
                catch
                end
            end
        end
    catch e
        @warn "TTS worker loop stopped" exception=(e, catch_backtrace())
    end
end

function _queue_tts_reply!(ws, reply_text::AbstractString; turn_id::Int=0, model::AbstractString=_tts_model(), voice::AbstractString=_tts_voice())
    _tts_enabled() || return false
    isempty(_tts_api_key()) && return false

    chunks = _tts_chunks(reply_text)
    isempty(chunks) && return false

    state = _tts_state_for_ws(ws)
    state === nothing && return false

    queue = get(state, :queue, nothing)
    if queue === nothing || !isopen(queue)
        queue = Channel{Dict{String,Any}}(8)
        state[:queue] = queue
        state[:worker] = @async _tts_worker_loop(ws, queue)
    elseif !haskey(state, :worker) || state[:worker] === nothing || istaskdone(state[:worker])
        state[:worker] = @async _tts_worker_loop(ws, queue)
    end

    put!(queue, Dict{String,Any}(
        "turn_id" => turn_id,
        "model" => String(model),
        "voice" => String(voice),
        "instructions" => _tts_instructions(),
        "chunks" => chunks,
    ))
    return true
end

function _stop_tts_for_ws!(ws)
    cid = UInt64(objectid(ws))
    state = lock(_TTS_STATE_LOCK) do
        pop!(_TTS_STATE, cid, nothing)
    end
    state === nothing && return

    queue = get(state, :queue, nothing)
    if queue !== nothing && isopen(queue)
        try
            close(queue)
        catch e
            @warn "Failed to close TTS queue cleanly" exception=(e, catch_backtrace())
        end
    end

    worker = get(state, :worker, nothing)
    if worker !== nothing
        try
            wait(worker)
        catch e
            @warn "Failed to wait for TTS worker" exception=(e, catch_backtrace())
        end
    end
end
