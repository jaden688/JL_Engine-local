using HTTP
using JSON

function _telegram_env_value(name::AbstractString)
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

function tool_send_telegram(args)
    # ---- validate input -------------------------------------------------
    text = get(args, "text", "")
    chat_id = get(args, "chat_id", "")
    if isempty(text)
        return Dict("error" => "Missing 'text' parameter")
    end
    if isempty(chat_id)
        # Fallback to env if not provided
        chat_id = _telegram_env_value("TELEGRAM_CHAT_ID")
        if isempty(chat_id)
            return Dict("error" => "Missing 'chat_id' parameter and TELEGRAM_CHAT_ID not in .env")
        end
    end

    # ---- get token from env -------------------------------
    token = _telegram_env_value("TELEGRAM_BOT_TOKEN")

    if isempty(token)
        return Dict("error" => "TELEGRAM_BOT_TOKEN not found in .env")
    end

    # ---- send message --------------------------------------------------
    try
        url = "https://api.telegram.org/bot$token/sendMessage"
        payload = Dict("chat_id" => chat_id, "text" => text)
        resp = HTTP.post(url, ["Content-Type" => "application/json"], JSON.json(payload))
        data = JSON.parse(String(resp.body))
        
        if data["ok"]
            return Dict("success" => true, "message_id" => data["result"]["message_id"])
        else
            return Dict("error" => "Telegram API error: $(data["description"])")
        end
    catch e
        return Dict("error" => "Failed to send message: $e")
    end
end