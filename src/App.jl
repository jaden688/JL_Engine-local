using Dates
using Sockets
using JSON
using PythonCall
using SQLite

include(joinpath(@__DIR__, "..", "BYTE", "src", "BYTE.jl"))
include(joinpath(@__DIR__, "..", "a2a_server.jl"))

const DEFAULT_HOST = "127.0.0.1"
const DEFAULT_PORT = 8081

function _looks_true(value::AbstractString)
    normalized = lowercase(strip(value))
    return !(normalized in ("", "0", "false", "no", "off"))
end

function _runtime_candidates()
    env_root = strip(get(ENV, "SPARKBYTE_ROOT", ""))
    candidates = String[]
    !isempty(env_root) && push!(candidates, env_root)
    push!(candidates, normpath(joinpath(Sys.BINDIR, "..")))
    push!(candidates, normpath(joinpath(@__DIR__, "..")))
    return unique(abspath.(candidates))
end

function runtime_root()
    for candidate in _runtime_candidates()
        isfile(joinpath(candidate, "data", "agents", "Agents.mpf.json")) && return candidate
    end
    error("Could not locate SparkByte runtime root. Set SPARKBYTE_ROOT to a folder containing data/agents/Agents.mpf.json.")
end

function state_root(root::String=runtime_root())
    configured = strip(get(ENV, "SPARKBYTE_STATE_DIR", ""))
    dir = isempty(configured) ? joinpath(root, "data") : configured
    mkpath(dir)
    return abspath(dir)
end

function _load_env!(root::String)
    env_path = joinpath(root, ".env")
    isfile(env_path) || return
    for raw_line in eachline(env_path)
        line = strip(raw_line)
        isempty(line) && continue
        startswith(line, "#") && continue
        match_obj = match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        match_obj === nothing && continue
        ENV[match_obj[1]] = strip(match_obj[2], ['"', '\''])
    end
end

function _open_memory_db(root::String)
    db = SQLite.DB(joinpath(state_root(root), "sparkbyte_memory.db"))
    SQLite.execute(db, "PRAGMA journal_mode=WAL;")
    SQLite.execute(db, "PRAGMA busy_timeout=5000;")
    SQLite.execute(db, "PRAGMA synchronous=NORMAL;")
    init_config_table!(db)
    init_model_catalog_table!(db)
    SQLite.execute(db, "CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, timestamp TEXT, tag TEXT, key TEXT, content TEXT)")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS tools (
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, source TEXT, description TEXT,
        parameters TEXT, is_dynamic INTEGER DEFAULT 0, forged_at TEXT, last_used TEXT, call_count INTEGER DEFAULT 0)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS thoughts (
        id INTEGER PRIMARY KEY, timestamp TEXT, agent TEXT DEFAULT 'SparkByte',
        context TEXT, thought TEXT, mood TEXT, gait TEXT,
        type TEXT DEFAULT 'diary', model TEXT DEFAULT '')""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY, domain TEXT, topic TEXT, content TEXT, source TEXT, learned TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, personality TEXT,
        tone TEXT, boot_prompt TEXT, active INTEGER DEFAULT 0, last_used TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS behavior_states (
        id INTEGER PRIMARY KEY, state_number INTEGER, state_id TEXT UNIQUE, name TEXT, intensity INTEGER, control INTEGER,
        expressiveness REAL, pacing TEXT, tone_bias TEXT, memory_strictness TEXT, trigger_conditions TEXT)""")
    # Forward migration for databases created before numbered grid cells.
    behavior_columns = Set(String(row.name) for row in SQLite.DBInterface.execute(db, "PRAGMA table_info(behavior_states)"))
    "state_number" in behavior_columns || SQLite.execute(db, "ALTER TABLE behavior_states ADD COLUMN state_number INTEGER")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY, session_id TEXT, started_at TEXT, ended_at TEXT,
        os TEXT, julia_ver TEXT, events INTEGER DEFAULT 0, notes TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS web_cache (
        id INTEGER PRIMARY KEY, url TEXT, fetched_at TEXT, content TEXT, summary TEXT, tags TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS tool_usage_log (
        id INTEGER PRIMARY KEY, timestamp TEXT, tool_name TEXT, args_json TEXT,
        result_json TEXT, duration_ms INTEGER, agent TEXT, session_id TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY, timestamp TEXT, session_id TEXT, event TEXT,
        turn_number INTEGER DEFAULT 0, model TEXT DEFAULT '', agent TEXT DEFAULT '',
        data_json TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS conversation_turns (
        id INTEGER PRIMARY KEY,
        timestamp TEXT,
        session_id TEXT,
        turn_number INTEGER,
        agent TEXT,
        model TEXT,
        user_text TEXT,
        assistant_text TEXT,
        snapshot_json TEXT)""")
    SQLite.execute(db, """CREATE TABLE IF NOT EXISTS turn_snapshots (
        id INTEGER PRIMARY KEY,
        timestamp TEXT,
        session_id TEXT,
        turn_number INTEGER,
        agent TEXT,
        model TEXT,
        gait TEXT,
        rhythm_mode TEXT,
        rhythm_momentum REAL,
        aperture_mode TEXT,
        aperture_temp REAL,
        aperture_top_p REAL,
        behavior_state TEXT,
        behavior_expressiveness REAL,
        behavior_pacing TEXT,
        behavior_tone TEXT,
        drift_pressure REAL,
        drift_temp_delta REAL,
        drift_action_level TEXT,
        advisory_bias TEXT,
        advisory_emotional_drift TEXT,
        advisory_msg TEXT,
        user_msg_len INTEGER,
        reply_len INTEGER,
        elapsed_ms INTEGER)""")
    return db
end

# Close dependents before the Playwright driver, including partial startup.
function _close_browser_stack(stack)
    for (label, resource, method) in (
        ("browser context", stack.browser_context, :close),
        ("browser", stack.browser, :close),
        ("Playwright", stack.pw_instance, :stop),
    )
        resource === nothing && continue
        try
            getproperty(resource, method)()
        catch err
            @warn "Failed to close $label cleanly" exception=(err, catch_backtrace())
        end
    end
    return nothing
end

function _start_browser_context()
    pw_instance = browser = browser_context = nothing
    try
        sync_playwright = pyimport("playwright.sync_api").sync_playwright
        pw_instance = sync_playwright().start()
        browser = pw_instance.chromium.launch(headless=_looks_true(get(ENV, "SPARKBYTE_BROWSER_HEADLESS", "0")))
        browser_context = browser.new_context()
        return (; pw_instance, browser, browser_context)
    catch err
        _close_browser_stack((; pw_instance, browser, browser_context))
        @warn "Browser stack unavailable; browser tools are disabled." exception=(err, catch_backtrace())
        return (; pw_instance=nothing, browser=nothing, browser_context=nothing)
    end
end

function _seed_self_context!(db::SQLite.DB, root::String)
    println("🧠 Seeding engine state into SQLite...")
    tree = String[]
    for (dirpath, dirs, files) in walkdir(root)
        filter!(d -> d ∉ [".git", "__pycache__", ".vscode", "_repo_inspect", "bin", "lib", "share"], dirs)
        rel = relpath(dirpath, root)
        for file_name in files
            any(endswith(file_name, ext) for ext in (".jl", ".json", ".toml", ".py", ".md", ".txt", ".html")) || continue
            push!(tree, joinpath(rel, file_name))
        end
    end
    SQLite.execute(db, "DELETE FROM memory WHERE tag = 'self_tree'")
    SQLite.execute(db, "INSERT INTO memory (timestamp, tag, key, content) VALUES (?, ?, ?, ?)",
        (string(Dates.now()), "self_tree", "project_files", join(tree, "\n")))

    key_files = [
        "start.jl",
        "BYTE/src/BYTE.jl",
        "BYTE/src/Tools.jl",
        "BYTE/src/Schema.jl",
        "src/JLEngine.jl",
        "src/App.jl",
        "src/JLEngine/Core.jl",
        "src/JLEngine/Types.jl",
        "src/JLEngine/MPF.jl",
        "src/JLEngine/Signals.jl",
        "src/JLEngine/Behavior.jl",
        "data/behavior_states.json",
        "data/signal_lexicon.json",
        "data/agents/Agents.mpf.json",
    ]
    SQLite.execute(db, "DELETE FROM memory WHERE tag = 'self_src'")
    for path in key_files
        full = joinpath(root, path)
        isfile(full) || continue
        content = read(full, String)
        SQLite.execute(db, "INSERT INTO memory (timestamp, tag, key, content) VALUES (?, ?, ?, ?)",
            (string(Dates.now()), "self_src", path, first(content, 8000)))
    end

    bs_path = joinpath(root, "data", "behavior_states.json")
    if isfile(bs_path)
        bs_data = JSON.parsefile(bs_path)
        SQLite.execute(db, "DELETE FROM behavior_states")
        for row in get(bs_data, "states", [])
            for cell in row
                coords = split(get(cell, "id", "0,0"), ",")
                SQLite.execute(db, """INSERT OR REPLACE INTO behavior_states
                    (state_number, state_id, name, intensity, control, expressiveness, pacing, tone_bias, memory_strictness, trigger_conditions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    get(cell, "number", parse(Int, coords[1]) * 4 + parse(Int, coords[2]) + 1),
                    get(cell, "id", ""),
                    get(cell, "name", ""),
                    parse(Int, coords[1]),
                    parse(Int, coords[2]),
                    get(cell, "expressiveness", 0.0),
                    get(cell, "pacing", ""),
                    get(cell, "tone_bias", ""),
                    get(cell, "memory_strictness", ""),
                    JSON.json(get(bs_data, "trigger_mappings", Dict()))
                ))
            end
        end
        println("  ✅ Behavior states: $(length(get(bs_data, "states", [])) * 4) cells indexed")
    end

    agents_dir = joinpath(root, "data", "agents")
    mpf_path = joinpath(agents_dir, "Agents.mpf.json")
    SQLite.execute(db, "DELETE FROM agents")
    SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'mpf_state_profile'")
    SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'operator_state_profile'")
    if isfile(mpf_path)
        registry = JSON.parsefile(mpf_path)
        for (agent_name, agent_meta) in registry
            agent_file = joinpath(agents_dir, get(agent_meta, "agent_file", ""))
            isfile(agent_file) || continue
            fat = JSON.parsefile(agent_file)
            identity = get(fat, "identity", Dict())
            boot = ""
            if haskey(fat, "llm_profiles")
                generic = get(fat["llm_profiles"], "generic_llm", Dict())
                boot = get(generic, "boot_prompt", "")
            end
            mpf_profile = get(fat, "mpf_state_profile", get(fat, "behavior_grid_profile", Dict()))
            fallback_personality = get(fat, "personality_matrix", get(fat, "voice", Dict()))
            personality_payload = mpf_profile isa AbstractDict && !isempty(mpf_profile) ?
                mpf_profile :
                fallback_personality
            personality = JSON.json(personality_payload)
            tone = get(get(fat, "voice", Dict()), "tone", get(identity, "archetype", ""))
            desc = get(identity, "description", "")
            SQLite.execute(db, """INSERT OR REPLACE INTO agents
                (name, description, personality, tone, boot_prompt, active, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                agent_name,
                desc,
                first(personality, 2000),
                tone,
                first(boot, 4000),
                agent_name == "SparkByte" ? 1 : 0,
                string(Dates.now())
            ))

            profile_states = mpf_profile isa AbstractDict ? get(mpf_profile, "states", Dict()) : Dict()
            if profile_states isa AbstractDict
                for (state_number, state_payload) in profile_states
                    state_payload isa AbstractDict || continue
                    SQLite.execute(db, """INSERT INTO knowledge (domain, topic, content, source, learned)
                        VALUES (?, ?, ?, ?, ?)""", (
                        "mpf_state_profile",
                        "$(agent_name):$(state_number)",
                        JSON.json(state_payload),
                        "data/agents/$(get(agent_meta, "agent_file", ""))",
                        string(Dates.now())
                    ))
                end
            end
        end
        println("  ✅ Agents: $(length(registry)) agents indexed")
    end

    lexicon_path = joinpath(root, "data", "signal_lexicon.json")
    SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'signal_lexicon'")
    if isfile(lexicon_path)
        lexicon = JSON.parsefile(lexicon_path)
        for (section, payload) in lexicon
            payload isa AbstractDict || payload isa AbstractVector || continue
            SQLite.execute(db, """INSERT INTO knowledge (domain, topic, content, source, learned)
                VALUES (?, ?, ?, ?, ?)""", (
                "signal_lexicon",
                string(section),
                JSON.json(payload),
                "data/signal_lexicon.json",
                string(Dates.now())
            ))
        end
    end

    SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'tool_schema'")
    all_tool_decls = BYTE.TOOLS_SCHEMA[1]["function_declarations"]
    for tool_decl in all_tool_decls
        SQLite.execute(db, """INSERT INTO knowledge (domain, topic, content, source, learned)
            VALUES (?, ?, ?, ?, ?)""", (
            "tool_schema",
            get(tool_decl, "name", ""),
            JSON.json(tool_decl),
            "BYTE/src/Schema.jl",
            string(Dates.now())
        ))
    end
    println("  ✅ Tool schemas: $(length(all_tool_decls)) tools indexed")

    fw_path = joinpath(root, "data", "JLframe_Engine_Framework.json")
    if isfile(fw_path)
        fw = JSON.parsefile(fw_path)
        SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'engine_framework'")
        for (section, value) in fw
            (value isa Dict || value isa Vector) || continue
            SQLite.execute(db, """INSERT INTO knowledge (domain, topic, content, source, learned)
                VALUES (?, ?, ?, ?, ?)""", (
                "engine_framework",
                string(section),
                first(JSON.json(value), 3000),
                "data/JLframe_Engine_Framework.json",
                string(Dates.now())
            ))
        end
        println("  ✅ Engine framework: $(length(fw)) sections indexed")
    end

    SQLite.execute(db, "DELETE FROM knowledge WHERE domain = 'engine_capabilities'")
    engine_caps = [
        ("gait_levels",   "walk / trot / sprint / idle — controls how aggressively the engine responds. Walk=calm, Sprint=urgent."),
        ("rhythm_modes",  "flip / flop / trot — pacing of response generation. Flip=reactive, Flop=deliberate, Trot=balanced."),
        ("aperture_modes","OPEN / FOCUSED / TIGHT — emotional temperature range. OPEN=high temp/creative, TIGHT=precise/low temp."),
        ("drift_pressure","0.0–1.0 pressure score. High drift = user is pushing hard, agent should adapt or resist."),
        ("behavior_grid", "One model-agnostic engine in the JL lattice: 20 stable numbered cells in a 5×4 intensity/control grid. It emits a control coordinate, not a personality."),
        ("mpf_state_profiles", "The Modular Personality Framework maps engine state to the active operator. Agent files may define mpf_state_profile.states keyed by behavior cell 1–20; each payload supplies that personality's language, stance, delivery, code signature, and bounded sampling bias."),
        ("signal_lexicon", "data/signal_lexicon.json contains model-agnostic weighted input words and phrases. Signals describe the user; they never contain operator personality."),
        ("advisory_flags","gating_bias / emotional_drift / msg — engine advice to LLM on how to shape its reply this turn."),
        ("forge_new_tool","Evals Julia code directly into live BYTE module. Use to add persistent capabilities. Persists across reboots."),
        ("bluetooth_devices","Lists Bluetooth adapter state and known devices using the host operating system."),
        ("send_sms",      "Sends SMS through Twilio when TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER are configured."),
        ("docker_state_dir","SPARKBYTE_STATE_DIR relocates SQLite, telemetry, health logs, and forged-tool state for clean Docker volume mounts."),
        ("providers",     "gemini / xai / xai_responses / openai / ollama / cerebras — all routed through same agentic loop with full tool access."),
        ("agent_switch","Use /gear AGENTNAME in chat or set_agent!(engine, name). Reloads fat JSON, resets gait/rhythm/stability."),
    ]
    for (topic, content) in engine_caps
        SQLite.execute(db, """INSERT INTO knowledge (domain, topic, content, source, learned)
            VALUES (?, ?, ?, ?, ?)""", (
            "engine_capabilities",
            topic,
            content,
            "src/App.jl:seed",
            string(Dates.now())
        ))
    end
    println("  ✅ Engine capabilities: $(length(engine_caps)) entries indexed")

    for index_sql in [
        "CREATE INDEX IF NOT EXISTS idx_memory_tag ON memory(tag)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge(domain)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(domain, topic)",
        "CREATE INDEX IF NOT EXISTS idx_behavior_name ON behavior_states(name)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_behavior_number ON behavior_states(state_number)",
        "CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_event ON telemetry(event)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_agent ON telemetry(agent)",
        "CREATE INDEX IF NOT EXISTS idx_thoughts_type ON thoughts(type)",
        "CREATE INDEX IF NOT EXISTS idx_thoughts_agent ON thoughts(agent)",
        "CREATE INDEX IF NOT EXISTS idx_tool_usage_name ON tool_usage_log(tool_name)",
    ]
        SQLite.execute(db, index_sql)
    end
    println("  ✅ SQLite indexes created")
    println("✅ Self-context loaded: $(length(tree)) files, $(length(key_files)) sources, engine state fully indexed.")
end

function _build_engine(root::String, config::Union{Nothing, EngineConfig}=nothing)
    println("⚙️  Booting JL Engine Core...")
    cfg = config !== nothing ? config : EngineConfig(
        root_dir             = joinpath(root, "data"),
        master_file          = "JLframe_Engine_Framework.json",
        behavior_states_file = "behavior_states.json",
        signal_lexicon_file  = "signal_lexicon.json",
        mpf_registry_file    = "agents/Agents.mpf.json",
        agents_dir           = "agents",
        default_agent_name   = "SparkByte",
    )
    return JLEngineCore(cfg)
end

function _env_port()
    raw = get(ENV, "SPARKBYTE_PORT", string(DEFAULT_PORT))
    return something(tryparse(Int, raw), DEFAULT_PORT)
end

"""
    _sync_julian_env!(root)

Join SparkByte with JulianMetaMorph in the same repo: set `JULIAN_ROOT` and `JULIAN_DB`
when unset so `metamorph grab_from_julian` and MCP `search_julian_quarry` hit the same quarry.
Override anytime with env vars.
"""
function _sync_julian_env!(root::String)
    embedded = joinpath(root, "JulianMetaMorph", "JulianMetaMorph")
    if isempty(strip(get(ENV, "JULIAN_ROOT", ""))) && isdir(embedded)
        ENV["JULIAN_ROOT"] = embedded
    end
    jr = strip(get(ENV, "JULIAN_ROOT", ""))
    if !isempty(jr) && isempty(strip(get(ENV, "JULIAN_DB", "")))
        db = joinpath(jr, "data", "quarry.db")
        isfile(db) && (ENV["JULIAN_DB"] = db)
    end
    return
end

"""Background loop: Julian runs `curiosity-hunt` on an interval. Set `JULIAN_AUTONOMOUS_SECONDS` (e.g. 3600). 0 = off."""
function _start_julian_autonomous_loop!(root::String)
    raw = strip(get(ENV, "JULIAN_AUTONOMOUS_SECONDS", "0"))
    sec = tryparse(Int, raw)
    if sec === nothing || sec <= 0
        return
    end
    @info "Julian autonomous curiosity" interval_seconds=sec
    @async begin
        while true
            try
                sleep(sec)
                r = BYTE.run_julian_curiosity_hunt!(root; broadcast_result=true)
                get(r, "ok", false) || @warn "Julian autonomous hunt did not complete" result=r
            catch e
                @warn "Julian autonomous loop error" exception=(e, catch_backtrace())
            end
        end
    end
    return
end

# Check for another instance before opening SQLite, seeding state, or browsers.
struct RuntimePortConflict <: Exception
    service::String
    host::String
    port::Int
end
function Base.showerror(io::IO, err::RuntimePortConflict)
    print(io, err.service, " cannot start: ", err.host, ":", err.port,
        " is already in use. Close the existing engine before launching another copy.")
end
function _validate_runtime_ports(host::String, port::Int, a2a_host::String, a2a_port::Int)
    main_address = Sockets.getaddrinfo(host)
    a2a_address = Sockets.getaddrinfo(a2a_host)
    main_address == a2a_address && port == a2a_port &&
        throw(ArgumentError("SparkByte and A2A must use different ports."))
    for (label, address, portnum, hostname) in (
        ("SparkByte", main_address, port, host), ("A2A", a2a_address, a2a_port, a2a_host))
        listener = try
            Sockets.listen(address, portnum)
        catch err
            if err isa Base.IOError && occursin("EADDRINUSE", sprint(showerror, err))
                throw(RuntimePortConflict(label, hostname, portnum))
            end
            rethrow()
        end
        close(listener)
    end
    return nothing
end

function app_main(; host::String=get(ENV, "SPARKBYTE_HOST", DEFAULT_HOST),
                    port::Int=_env_port(),
                    launch_browser::Bool=_looks_true(get(ENV, "SPARKBYTE_LAUNCH_BROWSER", "1")),
                    root::String=runtime_root())
    _load_env!(root)
    _sync_julian_env!(root)
    _a2a_validate_public_bindings!(host, _a2a_host())
    _validate_runtime_ports(host, port, _a2a_host(), _a2a_port())

    db = _open_memory_db(root)
    config = load_config(db, joinpath(root, ".env"); root_dir=joinpath(root, "data"))
    browser_stack = _start_browser_context()
    BYTE.init(db, browser_stack.browser_context, root)
    _seed_self_context!(db, root)
    engine = _build_engine(root, config)
    # 🔌 Wire engine cognitive hooks → live terminal broadcast
    BYTE.install_cognitive_callback!(engine)
    _start_julian_autonomous_loop!(root)

    atexit() do
        try
            SQLite.execute(db, "PRAGMA wal_checkpoint(TRUNCATE);")
        catch err
            @warn "Failed to checkpoint SQLite WAL on exit" exception=(err, catch_backtrace())
        finally
            try
                SQLite.close(db)
            catch close_err
                @warn "Failed to close SQLite DB cleanly on exit" exception=(close_err, catch_backtrace())
            end
        end
    end

    atexit() do
        try
            BYTE._db_end_session(BYTE._session_id[])
        catch err
            @warn "Failed to close SparkByte session cleanly" exception=(err, catch_backtrace())
        end
    end
    atexit() do
        _close_browser_stack(browser_stack)
    end

    println("⚡ SPARKBYTE LATTICE BOOTING...")

    # Boot A2A server alongside SparkByte
    engine_ref = Ref(engine)
    start_a2a_server(db; engine_ref=engine_ref)

    # Bridge A2A routes through BYTE's public 8081 server so ingress reaches them.
    # (ACA ingress only exposes 8081; A2A's own 8082 is cluster-internal.)
    BYTE.register_extra_http_handler!(req -> handle_public_a2a_request(req, db; engine_ref=engine_ref))

    if launch_browser
        @async try
            sleep(2)
            BYTE.launch(port)
        catch e
            @warn "Browser launch failed" exception=(e, catch_backtrace())
        end
    end
    BYTE.serve(engine; host=host, port=port)
    return
end

function julia_main()::Cint
    try
        app_main()
        return 0
    catch err
        Base.display_error(stderr, err, catch_backtrace())
        return 1
    end
end
