using Pkg
Pkg.activate(".")
using HTTP
using JSON
using Dates

const WS_URL = "ws://127.0.0.1:8081"
const REPLY_TIMEOUT_SECONDS = 180

function env_value(name::AbstractString)
    env_value = strip(get(ENV, String(name), ""))
    !isempty(env_value) && return strip(env_value, ['"', Char(39)])
    isfile(".env") || return ""

    prefix = string(name, "=")
    for line in eachline(".env")
        startswith(strip(line), prefix) || continue
        parts = split(line, "="; limit=2)
        length(parts) == 2 || return ""
        return strip(strip(parts[2]), ['"', Char(39)])
    end
    return ""
end

const TOKEN = env_value("TELEGRAM_BOT_TOKEN")

function send_telegram_message(chat_id, text::AbstractString)
    isempty(strip(text)) && return false
    url = "https://api.telegram.org/bot$TOKEN/sendMessage"
    payload = Dict("chat_id" => string(chat_id), "text" => String(text))
    resp = HTTP.post(url, ["Content-Type" => "application/json"], JSON.json(payload); status_exception=false)
    if resp.status < 200 || resp.status >= 300
        log_msg("ERROR: Telegram send failed with HTTP $(resp.status)")
        return false
    end
    data = JSON.parse(String(resp.body))
    ok = get(data, "ok", false) === true
    ok || log_msg("ERROR: Telegram send failed: $(get(data, "description", "unknown"))")
    return ok
end

function wait_for_engine_reply(ws; timeout_seconds::Real=REPLY_TIMEOUT_SECONDS)
    deadline = time() + timeout_seconds
    chunks = String[]
    receive_channel = Channel{Any}(1)
    receive_task = @async begin
        while true
            try
                put!(receive_channel, HTTP.WebSockets.receive(ws))
            catch e
                put!(receive_channel, e)
                break
            end
        end
    end

    while time() < deadline
        status = timedwait(() -> isready(receive_channel), max(0.1, min(1.0, deadline - time())))
        if status != :ok
            continue
        end

        raw = take!(receive_channel)
        raw isa Exception && return isempty(chunks) ? "" : join(chunks, "")
        packet = try
            JSON.parse(String(raw))
        catch
            nothing
        end
        packet isa AbstractDict || continue

        msg_type = string(get(packet, "type", ""))
        if msg_type == "spark"
            text = string(get(packet, "text", ""))
            !isempty(strip(text)) && push!(chunks, text)
        elseif msg_type == "engine_state"
            !isempty(chunks) && return join(chunks, "")
        elseif msg_type in ("tool_error", "error")
            text = string(get(packet, "text", ""))
            !isempty(strip(text)) && return text
        end
    end

    # Do NOT interrupt receive_task — it shares the outer WS; cancelling it corrupts the connection.
    return isempty(chunks) ? "" : join(chunks, "")
end

function request_engine_reply(prompt::AbstractString)
    payload = Dict(
        "type" => "user_msg",
        "text" => String(prompt),
        "chat_mode" => true
    )

    return HTTP.WebSockets.open(WS_URL) do ws
        HTTP.WebSockets.send(ws, JSON.json(payload))
        log_msg("Forwarded to engine.")
        return wait_for_engine_reply(ws)
    end
end

function log_msg(msg)
    ts = Dates.format(Dates.now(), "yyyy-mm-dd HH:MM:SS")
    line = "[$ts] $msg\n"
    print(line)
    open("telegram_listener.log", "a") do f
        write(f, line)
    end
end

function poll_telegram()
    if isempty(TOKEN)
        log_msg("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
        return
    end

    offset = 0
    log_msg("Starting Telegram listener.")
    
    while true
        try
            url = "https://api.telegram.org/bot$TOKEN/getUpdates?timeout=10&offset=$offset"
            resp = HTTP.get(url; readtimeout=15, retry=false)
            data = JSON.parse(String(resp.body))

            if data["ok"] && !isempty(data["result"])
                for update in data["result"]
                    offset = update["update_id"] + 1

                    if haskey(update, "message") && haskey(update["message"], "text")
                        msg = update["message"]["text"]
                        sender = update["message"]["from"]["first_name"]
                        chat_id = update["message"]["chat"]["id"]

                        log_msg("Received from $sender: $msg")

                        prompt = "[TELEGRAM MESSAGE from $sender]\n$msg\n\n(System: Reply directly with the exact Telegram response text. Do not mention tools, WebSockets, or internal routing.)"
                        reply = request_engine_reply(prompt)
                        cleaned = strip(reply)
                        # Filter engine-internal noise: abort notices, stop notices, empty
                        is_noise = isempty(cleaned) ||
                                   startswith(cleaned, "⊣") ||
                                   occursin("*Aborted.*", cleaned) ||
                                   occursin("Stop requested", cleaned) ||
                                   occursin("Nothing is generating", cleaned)
                        if is_noise
                            log_msg("Skipped internal engine notice (not forwarded to Telegram).")
                        elseif send_telegram_message(chat_id, reply)
                            log_msg("Sent reply to Telegram.")
                        else
                            log_msg("ERROR: Engine produced no Telegram reply before timeout.")
                        end
                    end
                end
            end
        catch e
            if !occursin("ReadTimeoutError", string(e)) && !occursin("EOFError", string(e))
                log_msg("Error polling Telegram: $e")
                sleep(2)
            end
        end
        sleep(0.5)
    end
end

poll_telegram()
