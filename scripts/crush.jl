# ==============================================================================
# SPARKBYTE // CRUSH CONSOLE
# Charm-Crush inspired interactive terminal console for BYTE / JLEngine.
# ==============================================================================

import Pkg
const ROOT_DIR = normpath(joinpath(@__DIR__, ".."))
if !haskey(Base.loaded_modules, Base.PkgId(Base.UUID("cd3eb016-35fb-5094-929b-558a96fad6f3"), "HTTP"))
    Pkg.activate(ROOT_DIR; io=devnull)
end

using HTTP
using HTTP.WebSockets
using JSON
using Dates
using JLEngine

# ── ANSI Styling Palette (Charm Crush Inspired) ──────────────────────────────
const RESET      = "\e[0m"
const BOLD       = "\e[1m"
const DIM        = "\e[2m"
const ITALIC     = "\e[3m"
const UNDERLINE  = "\e[4m"

const PINK       = "\e[38;5;213m"
const PURPLE     = "\e[38;5;141m"
const CYAN       = "\e[38;5;51m"
const BLUE       = "\e[38;5;75m"
const GREEN      = "\e[38;5;120m"
const YELLOW     = "\e[38;5;221m"
const AMBER      = "\e[38;5;214m"
const RED        = "\e[38;5;203m"
const GRAY       = "\e[38;5;244m"
const DARK_GRAY  = "\e[38;5;238m"

# ── Console Helper Functions ─────────────────────────────────────────────────
function terminal_width()
    try
        displaysize(stdout)[2]
    catch
        80
    end
end

function draw_box_top(title::String="", color::String=PURPLE)
    w = min(terminal_width() - 2, 80)
    if isempty(title)
        println(color * "╭" * "─"^(w - 2) * "╮" * RESET)
    else
        t_len = length(title)
        remain = max(0, w - t_len - 5)
        println(color * "╭─ " * BOLD * title * RESET * color * " " * "─"^remain * "╮" * RESET)
    end
end

function draw_box_line(text::String="", color::String=PURPLE; text_color::String=RESET)
    w = min(terminal_width() - 2, 80)
    # Strip ANSI escape codes for width calculation
    plain_text = replace(text, r"\e\[[0-9;]*m" => "")
    pad = max(0, w - length(plain_text) - 4)
    println(color * "│ " * RESET * text_color * text * RESET * " "^pad * color * " │" * RESET)
end

function draw_box_bottom(color::String=PURPLE)
    w = min(terminal_width() - 2, 80)
    println(color * "╰" * "─"^(w - 2) * "╯" * RESET)
end

function render_banner(agent::String, model::String, gait::String, aperture::String, rhythm::String, port_info::String="")
    println()
    draw_box_top("⚡ SPARKBYTE CRUSH // CONSOLE", PURPLE)
    draw_box_line("Operator: $(BOLD)$(CYAN)$agent$(RESET)  $(GRAY)•$(RESET)  Model: $(YELLOW)$model$(RESET)", PURPLE)
    draw_box_line("Gait: $(GREEN)$gait$(RESET)  $(GRAY)•$(RESET)  Aperture: $(AMBER)$aperture$(RESET)  $(GRAY)•$(RESET)  Rhythm: $(PINK)$rhythm$(RESET)", PURPLE)
    if !isempty(port_info)
        draw_box_line("Connected to: $(BLUE)$port_info$(RESET)", PURPLE)
    else
        draw_box_line("Mode: $(GREEN)In-Process Autonomous Engine$(RESET)", PURPLE)
    end
    draw_box_line("$(DIM)Type /help for slash commands, /exit to quit$(RESET)", PURPLE)
    draw_box_bottom(PURPLE)
    println()
end

# ── Server Detection ─────────────────────────────────────────────────────────
function detect_active_byte_server()
    for port in [8008, 8081]
        try
            resp = HTTP.get("http://127.0.0.1:$port/health"; readtimeout=1, connect_timeout=1)
            if resp.status == 200
                data = JSON.parse(String(resp.body))
                return (port=port, agent=get(data, "agent", "SparkByte"))
            end
        catch
        end
    end
    return nothing
end

# ── Mode A: WebSocket Client (Connecting to Live BYTE Server) ─────────────────
function run_ws_client(port::Int, initial_agent::String)
    url = "ws://127.0.0.1:$port"
    curr_agent = initial_agent
    curr_model = "anthropic/claude-3.7-sonnet"
    curr_gait = "walk"
    curr_aperture = "FOCUSED"
    curr_rhythm = "flip"

    render_banner(curr_agent, curr_model, curr_gait, curr_aperture, curr_rhythm, "ws://127.0.0.1:$port")

    HTTP.WebSockets.open(url) do ws
        # Receiver background task
        thinking_buffer = IOBuffer()
        is_thinking = Ref(false)

        @async try
            for msg in ws
                raw = String(msg)
                event = try JSON.parse(raw) catch; continue end
                t = get(event, "type", "")

                if t == "thinking"
                    delta = get(event, "delta", false)
                    txt = get(event, "text", "")
                    if !is_thinking[]
                        is_thinking[] = true
                        print(PINK * "\n🧠 [Thinking] " * RESET * DIM)
                    end
                    print(txt)
                    flush(stdout)
                elseif t == "tool_start"
                    is_thinking[] = false
                    name = get(event, "name", "unknown")
                    args = get(event, "args", Dict())
                    println()
                    println(AMBER * "╭─ ⚙️  Tool Call: " * BOLD * name * RESET * AMBER * " " * "─"^max(0, 50 - length(name)) * "╮" * RESET)
                    println(AMBER * "│ " * RESET * DIM * "Args: " * JSON.json(args) * RESET)
                elseif t == "tool" || t == "tool_output"
                    txt = get(event, "text", get(event, "output", ""))
                    println(AMBER * "│ " * RESET * GREEN * "⮑ " * string(txt) * RESET)
                    println(AMBER * "╰" * "─"^60 * "╯" * RESET)
                elseif t == "spark"
                    if is_thinking[]
                        println(RESET)
                        is_thinking[] = false
                    end
                    text = get(event, "text", "")
                    println()
                    println(CYAN * BOLD * "╭─ ⚡ $(curr_agent) ────────────────────────────────────────╮" * RESET)
                    for line in split(text, "\n")
                        println(CYAN * "│ " * RESET * line)
                    end
                    println(CYAN * "╰" * "─"^52 * "╯" * RESET)
                    println()
                elseif t == "ui_update"
                    curr_gait = lowercase(get(event, "gear", curr_gait))
                    modes = get(event, "modes", [])
                    if length(modes) >= 2
                        curr_rhythm = string(modes[1])
                        curr_aperture = string(modes[2])
                    end
                elseif t == "tokens"
                    pt = get(event, "session_prompt", 0)
                    ct = get(event, "session_completion", 0)
                    m = get(event, "model", curr_model)
                    curr_model = m
                    println(DARK_GRAY * "   [Tokens: prompt=$(pt) | completion=$(ct) | model=$(m)]" * RESET)
                end
            end
        catch e
            if !(e isa EOFError || e isa HTTP.WebSockets.WebSocketError)
                @warn "WS client error" exception=e
            end
        end

        # REPL prompt loop
        while true
            prompt_str = CYAN * BOLD * "[$curr_agent]" * RESET * " " * AMBER * "❯ " * RESET
            print(prompt_str)
            flush(stdout)
            line = readline()
            isempty(strip(line)) && continue

            cmd = strip(line)
            if lowercase(cmd) in ("/exit", "/quit", "exit", "quit")
                println(PURPLE * "Goodbye! ⚡" * RESET)
                break
            elseif lowercase(cmd) == "/clear"
                print("\e[2J\e[H")
                render_banner(curr_agent, curr_model, curr_gait, curr_aperture, curr_rhythm, "ws://127.0.0.1:$port")
                continue
            elseif lowercase(cmd) == "/help"
                println(GRAY * "Commands:" * RESET)
                println("  $(BOLD)/openrouter <key>$(RESET)  - Set OpenRouter API key and persist to .env")
                println("  $(BOLD)/key <key>$(RESET)         - Set API key / show key statuses")
                println("  $(BOLD)/gear <AgentName>$(RESET)  - Switch agent (SparkByte, Slappy, The Gremlin, Temporal, Supervisor)")
                println("  $(BOLD)/model <ModelId>$(RESET)   - Change LLM model")
                println("  $(BOLD)/status$(RESET)            - Show behavioral state")
                println("  $(BOLD)/clear$(RESET)             - Clear console")
                println("  $(BOLD)/exit$(RESET)              - Exit console")
                continue
            elseif startswith(cmd, "/gear")
                parts = split(cmd)
                if length(parts) > 1
                    curr_agent = String(parts[2])
                end
            end

            # Send turn to BYTE server
            payload = Dict{String,Any}(
                "type" => "user",
                "text" => line,
                "image" => nothing,
                "mime" => nothing,
                "chat_mode" => false
            )
            HTTP.WebSockets.send(ws, JSON.json(payload))
            sleep(0.3)
        end
    end
end

# ── Mode B: Standalone Autonomous Engine (In-Process) ────────────────────────
struct StandaloneConsoleWS
    agent_ref::Ref{String}
end

function HTTP.WebSockets.send(ws::StandaloneConsoleWS, msg::AbstractString)
    event = try JSON.parse(msg) catch; return end
    t = get(event, "type", "")
    if t == "thinking"
        txt = get(event, "text", "")
        print(PINK * txt * RESET)
        flush(stdout)
    elseif t == "tool_start"
        name = get(event, "name", "unknown")
        args = get(event, "args", Dict())
        println()
        println(AMBER * "╭─ ⚙️  Tool Call: " * BOLD * name * RESET * AMBER * " " * "─"^max(0, 50 - length(name)) * "╮" * RESET)
        println(AMBER * "│ " * RESET * DIM * "Args: " * JSON.json(args) * RESET)
    elseif t == "tool" || t == "tool_output"
        txt = get(event, "text", get(event, "output", ""))
        println(AMBER * "│ " * RESET * GREEN * "⮑ " * string(txt) * RESET)
        println(AMBER * "╰" * "─"^60 * "╯" * RESET)
    elseif t == "spark"
        text = get(event, "text", "")
        agent = ws.agent_ref[]
        println()
        println(CYAN * BOLD * "╭─ ⚡ $(agent) ────────────────────────────────────────╮" * RESET)
        for line in split(text, "\n")
            println(CYAN * "│ " * RESET * line)
        end
        println(CYAN * "╰" * "─"^52 * "╯" * RESET)
        println()
    elseif t == "tokens"
        pt = get(event, "session_prompt", 0)
        ct = get(event, "session_completion", 0)
        m = get(event, "model", "")
        println(DARK_GRAY * "   [Tokens: prompt=$(pt) | completion=$(ct) | model=$(m)]" * RESET)
    end
end

function run_standalone_engine()
    println(PURPLE * "⚡ Initializing autonomous in-process engine..." * RESET)
    
    root = ROOT_DIR
    JLEngine._load_env!(root)
    db = JLEngine._open_memory_db(root)
    browser_stack = JLEngine._start_browser_context()
    
    BYTE_mod = Main.JLEngine.BYTE
    BYTE_mod.init(db, browser_stack.browser_context, root)
    JLEngine._seed_self_context!(db, root)
    engine = JLEngine._build_engine(root)
    BYTE_mod.install_cognitive_callback!(engine)

    curr_agent = Ref(string(engine.current_agent_name))
    console_ws = StandaloneConsoleWS(curr_agent)
    history = Any[]

    render_banner(curr_agent[], BYTE_mod._current_model, "walk", "FOCUSED", "flip", "")

    while true
        prompt_str = CYAN * BOLD * "[$(curr_agent[])]" * RESET * " " * AMBER * "❯ " * RESET
        print(prompt_str)
        flush(stdout)
        line = readline()
        isempty(strip(line)) && continue

        cmd = strip(line)
        if lowercase(cmd) in ("/exit", "/quit", "exit", "quit")
            println(PURPLE * "Shutting down... Goodbye! ⚡" * RESET)
            break
        elseif lowercase(cmd) == "/clear"
            print("\e[2J\e[H")
            empty!(history)
            render_banner(curr_agent[], BYTE_mod._current_model, "walk", "FOCUSED", "flip", "")
            continue
        elseif lowercase(cmd) == "/help"
            println(GRAY * "Commands:" * RESET)
            println("  $(BOLD)/openrouter <key>$(RESET)  - Set OpenRouter API key and persist to .env")
            println("  $(BOLD)/key <key>$(RESET)         - Set API key / show key statuses")
            println("  $(BOLD)/gear <AgentName>$(RESET)  - Switch agent (SparkByte, Slappy, The Gremlin, Temporal, Supervisor)")
            println("  $(BOLD)/model <ModelId>$(RESET)   - Change LLM model")
            println("  $(BOLD)/status$(RESET)            - Show behavioral state")
            println("  $(BOLD)/clear$(RESET)             - Clear console & conversation history")
            println("  $(BOLD)/exit$(RESET)              - Exit console")
            continue
        elseif startswith(cmd, "/gear")
            parts = split(cmd)
            if length(parts) > 1
                new_agent = String(parts[2])
                if Main.JLEngine.set_agent!(engine, new_agent)
                    curr_agent[] = new_agent
                    println(GREEN * "⚡ Agent switched to: $(new_agent)" * RESET)
                else
                    println(RED * "⚠️ Unknown agent: $(new_agent)" * RESET)
                end
            end
            continue
        elseif startswith(cmd, "/model")
            parts = split(cmd)
            if length(parts) > 1
                BYTE_mod._current_model = String(parts[2])
                println(GREEN * "⚡ Active model set to: $(BYTE_mod._current_model)" * RESET)
            end
            continue
        elseif lowercase(cmd) == "/status"
            println(GRAY * "Status:" * RESET)
            println("  Agent: $(curr_agent[])")
            println("  Model: $(BYTE_mod._current_model)")
            println("  Gear:  $(BYTE_mod._current_gear)")
            println("  Modes: $(join(BYTE_mod._active_modes, ", "))")
            continue
        end

        # Process user turn through BYTE's agentic loop
        raw_msg = JSON.json(Dict{String,Any}(
            "type" => "user",
            "text" => line,
            "image" => nothing,
            "mime" => nothing,
            "chat_mode" => false
        ))

        try
            BYTE_mod.process_message(console_ws, raw_msg, history, engine)
        catch e
            println(RED * "⚠️ Error processing message: $(e)" * RESET)
        end
    end
end

# ── Main Entrypoint ──────────────────────────────────────────────────────────
function main()
    active_server = detect_active_byte_server()
    if active_server !== nothing
        run_ws_client(active_server.port, active_server.agent)
    else
        run_standalone_engine()
    end
end

main()
