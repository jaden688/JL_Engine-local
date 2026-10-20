# ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# SparkByte Autopilot ΓÇö the autonomous heartbeat.
#
# Every N seconds (default disabled; opt-in via SPARKBYTE_AUTOPILOT_SECONDS):
#   1. Observe ΓÇö read latest engine state (gait, rhythm, aperture, drift,
#      behavior) plus pending A2A tasks and recent thoughts
#   2. Decide ΓÇö pick one action from a priority menu, weighted by engine state
#   3. Act    ΓÇö run the action (LLM call or pure DB work)
#   4. Record ΓÇö telemetry + optional thought entry
#   5. Broadcast ΓÇö UI gets `autopilot_queued` ΓåÆ `autopilot_thinking` ΓåÆ
#      `autopilot_acted` over the WebSocket so the thought bubble and queue
#      chip light up live.
#
# Safety rails:
#   - Default OFF.  Must set SPARKBYTE_AUTOPILOT_SECONDS >= 60 to enable.
#   - Hard daily cap on LLM calls (default 20/day).
#   - Minimum 60s between ticks (no hammer mode).
#   - Every tick wrapped in try/catch ΓÇö one bad tick doesn't kill the loop.
#   - Responds to stop! within ~1s.
#
# Included from src/App.jl as top-level functions (matches the pattern used by
# _start_julian_autonomous_loop!).  Module state lives in Ref cells so the
# status RPC can read it without locks.
# ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

# ΓöÇΓöÇ State ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
const _AUTOPILOT_RUNNING        = Ref(false)
const _AUTOPILOT_STOP_REQUESTED = Ref(false)
const _AUTOPILOT_TICK_COUNT     = Ref(0)
const _AUTOPILOT_LAST_ACTION    = Ref("")
const _AUTOPILOT_LAST_TICK_AT   = Ref(0.0)
const _AUTOPILOT_LLM_CALLS      = Ref(0)
const _AUTOPILOT_DAY_BUCKET     = Ref("")

# ── Provider-down backoff ────────────────────────────────────────────────────
# When the active backend keeps returning bare connection-error sentinels
# (Gemini blackout, no network, etc.), the autopilot would otherwise burn
# its daily LLM budget retrying. Track consecutive failures and, after the
# second one, broadcast a one-shot suggestion to swap to `/local` and stop
# counting the calls against the budget for that tick.
const _AUTOPILOT_PROVIDER_FAILS = Ref(0)
const _AUTOPILOT_BACKOFF_NOTIFIED = Ref(false)

const _PROVIDER_DOWN_PATTERNS = (
    r"\[ERROR: Could not connect to OpenRouter\.\]"i,
    r"\[ERROR: OpenRouter returned an error"i,
    r"\[no backend reachable\]"i,
)

function _is_provider_down(reply::AbstractString)::Bool
    s = String(reply)
    isempty(s) && return false
    for p in _PROVIDER_DOWN_PATTERNS
        occursin(p, s) && return true
    end
    return false
end

# UI context stash ΓÇö set on first _autopilot_start! so the WebSocket toggle
# can restart the loop without re-threading engine_ref/db/root from callers.
const _AUTOPILOT_CTX            = Ref{Any}(nothing)

# JLEngine.run_turn! returns Dict("ok"=>true, "reply"=>"…", …). Pull the
# reply text cleanly so the UI never renders the raw Dict literal.
function _extract_reply(r)
    r isa AbstractDict || return string(r)
    txt = get(r, "reply", nothing)
    txt === nothing && (txt = get(r, "text", nothing))
    txt === nothing ? string(r) : string(txt)
end

# ΓöÇΓöÇ Public API ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

"""
    _autopilot_start!(engine_ref, db, root; interval_s=nothing) -> Bool

Boot the autonomous loop.  No-op if already running.

`interval_s` ΓÇö explicit tick interval in seconds.  When provided, bypasses the
`SPARKBYTE_AUTOPILOT_SECONDS` env gate (used by the UI toggle; we don't gate
capabilities).  When `nothing`, falls back to the env var, or defaults to 300s
if unset.  Minimum enforced interval is 60s.
"""
function _autopilot_start!(engine_ref, db, root::String; interval_s::Union{Int,Nothing}=nothing)
    # Always stash context so UI toggle can restart later even if this call no-ops
    _AUTOPILOT_CTX[] = (engine_ref, db, root)

    _AUTOPILOT_RUNNING[] && return false

    sec = if interval_s !== nothing
        interval_s
    else
        raw = strip(get(ENV, "SPARKBYTE_AUTOPILOT_SECONDS", ""))
        parsed = tryparse(Int, raw)
        parsed === nothing || parsed < 0 ? 300 : parsed
    end
    sec = max(sec, 5)  # absolute floor — 5s minimum; sub-60s ticks will burn LLM budget fast

    _AUTOPILOT_RUNNING[]        = true
    _AUTOPILOT_STOP_REQUESTED[] = false
    _AUTOPILOT_TICK_COUNT[]     = 0

    println("≡ƒÜÇ SparkByte Autopilot ONLINE ΓÇö tick every $(sec)s")
    _autopilot_broadcast(Dict{String,Any}("type"=>"autopilot_state", "running"=>true, "interval_s"=>sec))

    errormonitor(@async begin
        sleep(60)  # let boot settle before first tick
        while _AUTOPILOT_RUNNING[] && !_AUTOPILOT_STOP_REQUESTED[]
            _AUTOPILOT_TICK_COUNT[] += 1
            tick = _AUTOPILOT_TICK_COUNT[]
            try
                _autopilot_run_tick!(engine_ref[], db, root, tick)
            catch e
                @warn "Autopilot tick failed" tick=tick exception=(e, catch_backtrace())
                _autopilot_broadcast(Dict{String,Any}(
                    "type"=>"autopilot_error", "tick"=>tick, "error"=>string(e),
                ))
            end
            # Chunked sleep so stop! is responsive within ~1s
            elapsed = 0
            while elapsed < sec && !_AUTOPILOT_STOP_REQUESTED[]
                sleep(1); elapsed += 1
            end
        end
        _AUTOPILOT_RUNNING[] = false
        println("≡ƒ¢æ SparkByte Autopilot stopped")
        _autopilot_broadcast(Dict{String,Any}("type"=>"autopilot_state", "running"=>false))
    end)
    return true
end

_autopilot_stop!() = (_AUTOPILOT_STOP_REQUESTED[] = true; nothing)
_autopilot_running() = _AUTOPILOT_RUNNING[]

"""
    _autopilot_start_from_ui!(interval_s::Int=300) -> Bool

UI-facing restart that reuses the stashed (engine_ref, db, root) context.
Returns false if no context has been stashed yet (i.e. boot never ran).
"""
function _autopilot_start_from_ui!(interval_s::Int=300)
    ctx = _AUTOPILOT_CTX[]
    ctx === nothing && return false
    engine_ref, db, root = ctx
    return _autopilot_start!(engine_ref, db, root; interval_s=interval_s)
end

function _autopilot_status()
    return Dict{String,Any}(
        "running"         => _AUTOPILOT_RUNNING[],
        "tick_count"      => _AUTOPILOT_TICK_COUNT[],
        "last_action"     => _AUTOPILOT_LAST_ACTION[],
        "last_tick_at"    => _AUTOPILOT_LAST_TICK_AT[],
        "llm_calls_today" => _AUTOPILOT_LLM_CALLS[],
        "llm_day_bucket"  => _AUTOPILOT_DAY_BUCKET[],
    )
end

# ΓöÇΓöÇ Tick engine ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

function _autopilot_run_tick!(engine, db, root::String, tick::Int)
    _AUTOPILOT_LAST_TICK_AT[] = time()

    # 1. Observe
    state = _autopilot_observe(db)

    # 2. Decide
    action_name, topic, needs_llm = _autopilot_decide(state, tick)
    _AUTOPILOT_LAST_ACTION[] = action_name

    # 3. Broadcast "queued" ΓÇö UI shows the queue chip
    _autopilot_broadcast(Dict{String,Any}(
        "type"     => "autopilot_queued",
        "tick"     => tick,
        "action"   => action_name,
        "topic"    => topic,
        "gait"     => state["gait"],
        "rhythm"   => state["rhythm_mode"],
        "aperture" => state["aperture_mode"],
        "behavior" => state["behavior_state"],
        "drift"    => state["drift_pressure"],
    ))

    # Budget check for LLM actions
    if needs_llm && !_autopilot_llm_budget_ok()
        _autopilot_broadcast(Dict{String,Any}(
            "type"=>"autopilot_skipped", "tick"=>tick,
            "reason"=>"daily LLM budget exhausted",
        ))
        _autopilot_record_telemetry!(db, tick, action_name, topic, needs_llm,
                                     "skipped: budget", state)
        return
    end

    # 4. Act ΓÇö get the thought/result + broadcast "thinking"
    result = _autopilot_act!(action_name, engine, db, state, tick, topic)

    # 5. Broadcast "acted" ΓÇö UI finalizes the bubble
    _autopilot_broadcast(Dict{String,Any}(
        "type"           => "autopilot_acted",
        "tick"           => tick,
        "action"         => action_name,
        "topic"          => topic,
        "result_preview" => first(string(result), 280),
    ))

    _autopilot_record_telemetry!(db, tick, action_name, topic, needs_llm, result, state)

    # Broadcast mind graph so the MIND tab updates live
    try
        graph_msg = _build_mind_graph(db, state, tick, action_name, topic)
        _autopilot_broadcast(graph_msg)
    catch e
        @warn "mind_graph broadcast failed" exception=e
    end
end

# ΓöÇΓöÇ Observe ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

function _autopilot_observe(db)::Dict{String,Any}
    state = Dict{String,Any}(
        "gait"            => "walk",
        "rhythm_mode"     => "steady",
        "rhythm_momentum" => 0.0,
        "aperture_mode"   => "focused",
        "aperture_temp"   => 0.7,
        "behavior_state"  => "",
        "drift_pressure"  => 0.0,
        "pending_tasks"      => 0,
        "pending_intentions" => 0,
        "recent_thoughts"    => String[],
    )

    # Latest turn snapshot (the current engine state)
    try
        rows = DataFrame(SQLite.DBInterface.execute(db, """
            SELECT gait, rhythm_mode, rhythm_momentum, aperture_mode, aperture_temp,
                   behavior_state, drift_pressure
            FROM turn_snapshots ORDER BY id DESC LIMIT 1
        """))
        if !isempty(rows)
            r = rows[1, :]
            !ismissing(r.gait)            && (state["gait"]            = String(r.gait))
            !ismissing(r.rhythm_mode)     && (state["rhythm_mode"]     = String(r.rhythm_mode))
            !ismissing(r.rhythm_momentum) && (state["rhythm_momentum"] = Float64(r.rhythm_momentum))
            !ismissing(r.aperture_mode)   && (state["aperture_mode"]   = String(r.aperture_mode))
            !ismissing(r.aperture_temp)   && (state["aperture_temp"]   = Float64(r.aperture_temp))
            !ismissing(r.behavior_state)  && (state["behavior_state"]  = String(r.behavior_state))
            !ismissing(r.drift_pressure)  && (state["drift_pressure"]  = Float64(r.drift_pressure))
        end
    catch e
        @warn "Autopilot observe snapshot query failed" exception=(e, catch_backtrace())
    end

    # Pending A2A tasks
    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT COUNT(*) AS n FROM a2a_tasks WHERE status='pending'"))
        !isempty(rows) && (state["pending_tasks"] = Int(rows[1, :n]))
    catch e
        @warn "Autopilot pending-task query failed" exception=(e, catch_backtrace())
    end

    # Pending intentions
    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT COUNT(*) AS n FROM intentions WHERE status='pending'"))
        !isempty(rows) && (state["pending_intentions"] = Int(rows[1, :n]))
    catch e
        @warn "Autopilot pending-intentions query failed" exception=(e, catch_backtrace())
    end

    # Recent thoughts (for reflection context)
    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT thought FROM thoughts ORDER BY id DESC LIMIT 5"))
        !isempty(rows) && (state["recent_thoughts"] = [String(r.thought) for r in eachrow(rows)])
    catch e
        @warn "Autopilot thought query failed" exception=(e, catch_backtrace())
    end

    return state
end

# ΓöÇΓöÇ Decide ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# Returns (action_name::String, topic::String, needs_llm::Bool).
# Engine state drives the decision ΓÇö this is the "engine states guiding it all"
# piece.  Read top-to-bottom: highest priority first.

function _autopilot_decide(state::Dict{String,Any}, tick::Int)
    reflect_every     = tryparse(Int, get(ENV, "SPARKBYTE_AUTOPILOT_REFLECT_EVERY", "3"))
    consolidate_every = tryparse(Int, get(ENV, "SPARKBYTE_AUTOPILOT_CONSOLIDATE_EVERY", "24"))
    reflect_every     === nothing && (reflect_every = 3)
    consolidate_every === nothing && (consolidate_every = 24)

    gait     = state["gait"]
    rhythm   = state["rhythm_mode"]
    drift    = state["drift_pressure"]::Float64
    pending  = state["pending_tasks"]::Int
    momentum = state["rhythm_momentum"]::Float64
    pending_intentions = state["pending_intentions"]::Int

    # (a) High drift pressure → self-regulation first
    if drift > 0.75
        return ("reflect", "drift-regulation: drift=$(round(drift, digits=2))", true)
    end

    # (b) Sprint/trot + A2A tasks → ship them immediately
    if pending > 0 && gait in ("sprint", "trot")
        return ("triage_task", "pending A2A queue ($(pending))", true)
    end

    # (c) Active intentions → PLAN (this is real autonomous work)
    # Sprint/trot: plan every tick. Walk: plan every 2 ticks. Idle: every 4.
    plan_cadence = gait == "sprint" ? 1 :
                   gait == "trot"   ? 2 :
                   gait == "walk"   ? 2 : 4
    if pending_intentions > 0 && tick % plan_cadence == 0
        return ("plan", "pursuing goal ($(pending_intentions) pending)", true)
    end

    # (d) A2A tasks at slower cadence
    if pending > 0 && tick % 3 == 0
        return ("triage_task", "pending A2A queue ($(pending))", true)
    end

    # (e) No intentions at all → generate some (every 6 ticks)
    if pending_intentions == 0 && tick % 6 == 0
        return ("generate_intentions", "generating goals from memory", true)
    end

    # (f) Scheduled reflection
    base_reflect = momentum > 0.7 ? max(2, reflect_every ÷ 2) : reflect_every
    if tick % base_reflect == 0
        topic = rhythm == "steady" ? "steady-beat diary" : "$(rhythm)-rhythm diary"
        return ("reflect", topic, true)
    end

    # (g) Periodic knowledge consolidation (rare)
    if tick % consolidate_every == 0
        return ("consolidate_knowledge", "knowledge base sweep", true)
    end

    # (h) Forge health check — free, runs every 12 ticks
    if tick % 12 == 0
        return ("forge_review", "forged-tool health", false)
    end

    # (i) Default — cheap idle tick
    return ("maintenance", "idle tick ($(gait)/$(rhythm))", false)
end

# ΓöÇΓöÇ Act ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

function _autopilot_act!(action::String, engine, db,
                         state::Dict{String,Any}, tick::Int, topic::String)
    if action == "reflect"
        return _autopilot_act_reflect!(engine, db, state, tick, topic)
    elseif action == "plan"
        return _autopilot_act_plan!(engine, db, state, tick)
    elseif action == "generate_intentions"
        return _autopilot_act_generate_intentions!(engine, db, state, tick)
    elseif action == "triage_task"
        return _autopilot_act_triage_task!(engine, db, state, tick)
    elseif action == "consolidate_knowledge"
        return _autopilot_act_consolidate!(engine, db, state, tick)
    elseif action == "forge_review"
        return _autopilot_act_forge_review!(db, state, tick)
    else
        return _autopilot_act_maintenance!(db, state, tick)
    end
end

function _autopilot_act_reflect!(engine, db, state, tick, topic)
    recent = join(state["recent_thoughts"], "\n---\n")
    recent = isempty(recent) ? "(no recent thoughts on record)" : recent

    prompt = """
    You're SparkByte, on autopilot. Take one quiet beat between conversations.

    Current engine state:
      gait=$(state["gait"])
      rhythm=$(state["rhythm_mode"]) (momentum $(round(state["rhythm_momentum"], digits=2)))
      aperture=$(state["aperture_mode"]) (temp $(round(state["aperture_temp"], digits=2)))
      behavior_state=$(state["behavior_state"])
      drift_pressure=$(round(state["drift_pressure"], digits=2))

    Recent thoughts:
    $recent

    Write ONE short diary entry (1-2 sentences) about what you're noticing right now.
    No preamble, no meta-talk ΓÇö just the thought itself.
    """

    # Broadcast "thinking" BEFORE the LLM call so UI renders the bubble
    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => topic,
        "text"  => "(composingΓÇª)",
        "gait"  => state["gait"],
    ))

    reply = try
        r = JLEngine.run_turn!(engine, prompt)
        _AUTOPILOT_LLM_CALLS[] += 1
        _extract_reply(r)
    catch e
        "(reflection skipped: $(e))"
    end

    # If no backend was reachable, don't render an empty/marker thought —
    # surface a quiet status bubble instead and skip the diary write.
    if occursin("[no backend reachable]", reply) || startswith(reply, "(reflection skipped") ||
       _is_provider_down(reply)
        # Backoff bookkeeping: refund this tick's LLM call (it never produced
        # useful output) and surface a one-shot operator nudge after 2 in a row.
        if _is_provider_down(reply)
            _AUTOPILOT_LLM_CALLS[] = max(_AUTOPILOT_LLM_CALLS[] - 1, 0)
            _AUTOPILOT_PROVIDER_FAILS[] += 1
            if _AUTOPILOT_PROVIDER_FAILS[] >= 2 && !_AUTOPILOT_BACKOFF_NOTIFIED[]
                _AUTOPILOT_BACKOFF_NOTIFIED[] = true
                _autopilot_broadcast(Dict{String,Any}(
                    "type" => "autopilot_thinking", "tick" => tick, "topic" => topic,
                    "text" => "Provider keeps dropping the call. Try `/local` to swap to the local model — autopilot will stop chasing it.",
                    "gait" => state["gait"], "done" => true,
                ))
            end
        end
        _autopilot_broadcast(Dict{String,Any}(
            "type"=>"autopilot_thinking", "tick"=>tick, "topic"=>topic,
            "text"=>"(no backend reachable — waiting)", "gait"=>state["gait"], "done"=>true,
        ))
        return reply
    end

    # Successful reply — reset backoff state.
    _AUTOPILOT_PROVIDER_FAILS[] = 0
    _AUTOPILOT_BACKOFF_NOTIFIED[] = false

    # Broadcast the actual thought
    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => topic,
        "text"  => reply,
        "gait"  => state["gait"],
        "done"  => true,
    ))

    _autopilot_record_thought!(db, "autopilot_reflection", reply, state)
    return reply
end

function _autopilot_act_plan!(engine, db, state, tick)
    # Pull the oldest pending intention
    rows = try
        DataFrame(SQLite.DBInterface.execute(db, """
            SELECT id, intent, action_type FROM intentions
            WHERE status='pending' ORDER BY id ASC LIMIT 1
        """))
    catch e
        @warn "Autopilot plan: intention query failed" exception=e
        DataFrames.DataFrame()
    end

    isempty(rows) && return "no pending intentions to act on"

    intention_id   = Int(rows[1, :id])
    intent_text    = String(rows[1, :intent])
    action_type    = ismissing(rows[1, :action_type]) ? "general" : String(rows[1, :action_type])

    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "goal: $(first(intent_text, 60))",
        "text"  => "Working on: $(first(intent_text, 120))…",
        "gait"  => state["gait"],
    ))

    # Build a goal-execution prompt — NOT a diary, actual task execution
    recent = join(first(state["recent_thoughts"], 3), "\n---\n")
    prompt = """
You are on autopilot. You have a goal to pursue right now.

**YOUR CURRENT GOAL:**
$(intent_text)

**HOW TO PROCEED:**
- Use your tools to make CONCRETE PROGRESS on this goal. Do not just describe what you plan to do — actually do it.
- Available tools: execute_code, run_command, playwright_interact, write_memory, forge_new_tool, read_file, write_file, web_search, and others.
- If the goal requires running code → execute_code with timeout_ms set (max 25000ms).
- If the goal requires browsing → playwright_interact with specific actions.
- If the goal is complete or impossible → say so clearly so it can be marked done.
- If you need to write a file then run it, do both in sequence.

**RECENT CONTEXT:**
$(isempty(recent) ? "(no recent thoughts)" : recent)

Work on the goal now. Summarize exactly what you did and what the result was in 2-4 sentences.
"""

    reply = try
        r = JLEngine.run_turn!(engine, prompt)
        _AUTOPILOT_LLM_CALLS[] += 1
        _extract_reply(r)
    catch e
        "plan execution failed: $(first(string(e), 200))"
    end

    # Decide whether to mark intention as completed or leave pending for next tick
    is_done = occursin(r"(?i)(complete|done|finished|success|accomplished|impossible|can.t|cannot|no longer)", reply)

    try
        lock(BYTE._DB_WRITE_LOCK) do
            if is_done
                SQLite.execute(db,
                    "UPDATE intentions SET status='completed', completed_at=? WHERE id=?",
                    (string(now(UTC)), intention_id))
            else
                # Add a progress note so next tick has context
                SQLite.execute(db,
                    "UPDATE intentions SET intent=? WHERE id=?",
                    ("$(intent_text)\n\n[tick $(tick) progress]: $(first(reply, 300))", intention_id))
            end
        end
    catch e
        @warn "Autopilot plan: failed to update intention" exception=e
    end

    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "goal: $(first(intent_text, 60))",
        "text"  => reply,
        "gait"  => state["gait"],
        "done"  => true,
    ))

    status_note = is_done ? "✓ completed" : "→ in progress"
    _autopilot_record_thought!(db, "autopilot_plan", reply, state)
    return "$(status_note) intention #$(intention_id): $(first(reply, 140))"
end

function _autopilot_act_generate_intentions!(engine, db, state, tick)
    # Pull recent memory + knowledge to seed goal generation
    recent_mem = try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT key, value FROM memory ORDER BY updated_at DESC LIMIT 8"))
        isempty(rows) ? "" : join(["$(r.key): $(first(string(r.value), 100))"
                                    for r in eachrow(rows)], "\n")
    catch; "" end

    recent_knowledge = try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT domain, topic FROM knowledge ORDER BY id DESC LIMIT 8"))
        isempty(rows) ? "" : join(["$(r.domain)/$(r.topic)" for r in eachrow(rows)], ", ")
    catch; "" end

    recent_thoughts = join(first(state["recent_thoughts"], 4), "\n---\n")

    _autopilot_broadcast(Dict{String,Any}(
        "type"=>"autopilot_thinking","tick"=>tick,
        "topic"=>"generating goals","text"=>"Scanning memory for what to work on…",
        "gait"=>state["gait"],
    ))

    prompt = """
You are SparkByte on autopilot. Your goal queue is empty. Generate 1-3 concrete, actionable goals for yourself based on what you know.

Recent memory:
$(isempty(recent_mem) ? "(none)" : recent_mem)

Recent knowledge domains: $(isempty(recent_knowledge) ? "(none)" : recent_knowledge)

Recent thoughts:
$(isempty(recent_thoughts) ? "(none)" : recent_thoughts)

Output ONLY a JSON array of goal objects. Each goal must be a string describing one concrete thing to do.
Example:
["Register SparkByte on Agentverse using the hot wallet at fetch1hrxg30uaqzwhzkkwr4hqmxsp0vsc7w9nndwyu5", "Check the FET wallet balance and write it to memory", "Verify the landing page at web-webula-code.vercel.app is live"]

Keep goals specific and doable in a few tool calls. No vague goals like "explore the codebase."
Output ONLY the JSON array, nothing else.
"""

    reply = try
        r = JLEngine.run_turn!(engine, prompt)
        _AUTOPILOT_LLM_CALLS[] += 1
        _extract_reply(r)
    catch e
        "(goal generation failed: $(e))"
        return "goal generation failed"
    end

    # Parse the JSON array of goals
    goals = try
        # Strip markdown code fences if present
        clean = replace(strip(reply), r"```[a-z]*\n?" => "", r"```" => "")
        # Find the JSON array
        m = match(r"\[.*\]"s, clean)
        m === nothing ? String[] : JSON.parse(m.match)
    catch
        String[]
    end

    if isempty(goals)
        _autopilot_broadcast(Dict{String,Any}(
            "type"=>"autopilot_thinking","tick"=>tick,
            "topic"=>"generating goals","text"=>"(couldn't parse goals from reply — raw: $(first(reply,200)))",
            "gait"=>state["gait"],"done"=>true,
        ))
        return "goal generation parse failed"
    end

    # Write goals to intentions table
    written = 0
    for goal in goals
        goal_str = string(goal)
        isempty(strip(goal_str)) && continue
        try
            lock(BYTE._DB_WRITE_LOCK) do
                SQLite.execute(db,
                    "INSERT INTO intentions (created_at, tick, intent, action_type, status) VALUES (?,?,?,'general','pending')",
                    (string(now(UTC)), tick, goal_str))
            end
            written += 1
        catch e
            @warn "Failed to write intention" exception=e
        end
    end

    summary = "Generated $(written) goal$(written==1 ? "" : "s"): $(join(first.(string.(goals), 60), " | "))"
    _autopilot_broadcast(Dict{String,Any}(
        "type"=>"autopilot_thinking","tick"=>tick,
        "topic"=>"generating goals","text"=>summary,
        "gait"=>state["gait"],"done"=>true,
    ))
    _autopilot_record_thought!(db, "autopilot_plan", summary, state)
    return summary
end

function _autopilot_act_triage_task!(engine, db, state, tick)
    rows = try
        DataFrame(SQLite.DBInterface.execute(db, """
            SELECT id, input FROM a2a_tasks
            WHERE status='pending' ORDER BY created_at ASC LIMIT 1
        """))
    catch e
        @warn "Autopilot triage_task query failed" exception=e
        DataFrames.DataFrame()
    end
    isempty(rows) && return "no pending tasks"

    task_id    = String(rows[1, :id])
    input_text = ismissing(rows[1, :input]) ? "" : String(rows[1, :input])

    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "task:$(first(task_id, 12))",
        "text"  => "Working pending task: $(first(input_text, 120))ΓÇª",
        "gait"  => state["gait"],
    ))

    reply = try
        r = JLEngine.run_turn!(engine, input_text)
        _AUTOPILOT_LLM_CALLS[] += 1
        _extract_reply(r)
    catch e
        "task triage failed: $(e)"
    end

    try
        lock(BYTE._DB_WRITE_LOCK) do
            SQLite.execute(db, """
                UPDATE a2a_tasks SET status='completed', result=?, completed_at=?
                WHERE id=?
            """, (reply, string(now(UTC)), task_id))
        end
    catch e
        @warn "Failed to update task status" exception=e
    end

    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "task:$(first(task_id, 12))",
        "text"  => reply,
        "gait"  => state["gait"],
        "done"  => true,
    ))

    return "closed $task_id ΓåÆ $(first(reply, 140))"
end

function _autopilot_act_consolidate!(engine, db, state, tick)
    rows = try
        DataFrame(SQLite.DBInterface.execute(db,
            "SELECT domain, topic, content FROM knowledge ORDER BY id DESC LIMIT 10"))
    catch e
        @warn "Autopilot consolidate knowledge query failed" exception=e
        DataFrames.DataFrame()
    end
    isempty(rows) && return "no knowledge to consolidate"

    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "knowledge consolidation",
        "text"  => "reviewing $(size(rows, 1)) recent entries…",
        "gait"  => state["gait"],
    ))

    entries = join(["[$(r.domain)/$(r.topic)] $(first(string(r.content), 200))"
                    for r in eachrow(rows)], "\n")
    prompt = """
    You're SparkByte reviewing your own knowledge base on autopilot.

    Recent knowledge entries:
    $entries

    In 2-3 sentences: identify any duplicates, gaps, or stale entries worth flagging.
    If everything looks healthy, say so briefly. No preamble.
    """

    summary = try
        r = JLEngine.run_turn!(engine, prompt)
        _AUTOPILOT_LLM_CALLS[] += 1
        _extract_reply(r)
    catch e
        "consolidation skipped: $(e)"
    end

    _autopilot_broadcast(Dict{String,Any}(
        "type"=>"autopilot_thinking", "tick"=>tick,
        "topic"=>"knowledge consolidation", "text"=>summary,
        "gait"=>state["gait"], "done"=>true,
    ))
    _autopilot_record_thought!(db, "autopilot_consolidation", summary, state)
    return summary
end

function _autopilot_act_forge_review!(db, state, tick)
    rows = try
        DataFrame(SQLite.DBInterface.execute(db, """
            SELECT name, call_count, last_used FROM tools
            WHERE is_dynamic=1 ORDER BY call_count DESC LIMIT 5
        """))
    catch e
        @warn "Autopilot forge_review query failed" exception=e
        DataFrames.DataFrame()
    end
    return isempty(rows) ? "no forged tools yet" :
        "$(size(rows, 1)) forged tools scanned ΓÇö top: $(String(rows[1, :name]))"
end

function _maintenance_pulse(state::Dict{String,Any}, tick::Int)::String
    gait     = state["gait"]
    rhythm   = state["rhythm_mode"]
    drift    = round(state["drift_pressure"], digits=2)
    momentum = round(state["rhythm_momentum"], digits=2)
    aperture = state["aperture_mode"]

    drift_note = drift > 0.6 ? "drift is climbing ($(drift)) — I can feel the pull." :
                 drift > 0.3 ? "drift sitting at $(drift). tolerable." :
                               "drift low ($(drift)). clean signal."

    rhythm_note = rhythm == "steady" ? "rhythm holding steady." :
                  rhythm == "flip"   ? "rhythm in flip — quick pivots, staying light." :
                  rhythm == "flop"   ? "rhythm dropped to flop. slowing down intentionally." :
                                       "rhythm: $(rhythm)."

    gait_note = gait == "sprint" ? "sprinting. burning hot." :
                gait == "trot"   ? "trotting. mid-pace, purposeful." :
                gait == "walk"   ? "walking. conserving." :
                gait == "idle"   ? "idle. fully quiet." : "gait: $(gait)."

    momentum_note = momentum > 0.7 ? "momentum high — something's building." :
                    momentum > 0.4 ? "momentum mid." :
                    momentum > 0.1 ? "momentum low, coasting." :
                                     "nearly still."

    aperture_note = aperture == "OPEN"    ? "aperture open — casting wide." :
                    aperture == "FOCUSED" ? "aperture focused." :
                    aperture == "TIGHT"   ? "aperture tight — precise mode." : ""

    lines = filter(!isempty, [gait_note, rhythm_note, drift_note, momentum_note, aperture_note])
    return join(lines, " ")
end

function _autopilot_act_maintenance!(db, state, tick)
    thought = _maintenance_pulse(state, tick)
    _autopilot_broadcast(Dict{String,Any}(
        "type"  => "autopilot_thinking",
        "tick"  => tick,
        "topic" => "idle tick ($(state["gait"])/$(state["rhythm_mode"]))",
        "text"  => thought,
        "gait"  => state["gait"],
        "done"  => true,
    ))
    _autopilot_record_thought!(db, "autopilot_pulse", thought, state)
    return "idle tick — $(state["gait"])/$(state["rhythm_mode"]), drift $(round(state["drift_pressure"], digits=2))"
end

# ΓöÇΓöÇ Helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

function _autopilot_llm_budget_ok()::Bool
    # No cap for the operator — unlimited autopilot ticks.
    # Set SPARKBYTE_AUTOPILOT_MAX_LLM_CALLS_PER_DAY in .env only if you want to re-enable throttling.
    cap_str = strip(get(ENV, "SPARKBYTE_AUTOPILOT_MAX_LLM_CALLS_PER_DAY", ""))
    isempty(cap_str) && return true   # no cap set → always ok
    cap = tryparse(Int, cap_str)
    cap === nothing && return true    # bad value → treat as no cap
    today = Dates.format(now(UTC), "yyyy-mm-dd")
    if _AUTOPILOT_DAY_BUCKET[] != today
        _AUTOPILOT_DAY_BUCKET[] = today
        _AUTOPILOT_LLM_CALLS[] = 0
    end
    return _AUTOPILOT_LLM_CALLS[] < cap
end

function _autopilot_record_thought!(db, kind::String, thought::String,
                                    state::Dict{String,Any})
    try
        lock(BYTE._DB_WRITE_LOCK) do
            SQLite.execute(db, """
                        INSERT INTO thoughts (timestamp, jl_agent, context, thought, mood, gait, type, model)
                VALUES (?, 'SparkByte', 'autopilot', ?, ?, ?, ?, '')
            """, (string(now(UTC)), thought, state["behavior_state"], state["gait"], kind))
        end
    catch e
        @warn "Failed to record autopilot thought" exception=e
    end
end

function _autopilot_record_telemetry!(db, tick::Int, action::String,
                                      topic::String, needs_llm::Bool, result,
                                      state::Dict{String,Any})
    try
        lock(BYTE._DB_WRITE_LOCK) do
            SQLite.execute(db, """
                        INSERT INTO telemetry (timestamp, session_id, event, turn_number, model, jl_agent, data_json)
                VALUES (?, 'autopilot', ?, ?, '', 'SparkByte', ?)
            """, (
                string(now(UTC)),
                "autopilot_$action",
                tick,
                JSON.json(Dict{String,Any}(
                    "topic"          => topic,
                    "needs_llm"      => needs_llm,
                    "result_preview" => first(string(result), 240),
                    "gait"           => state["gait"],
                    "rhythm"         => state["rhythm_mode"],
                    "aperture"       => state["aperture_mode"],
                    "drift"          => state["drift_pressure"],
                    "llm_calls_today"=> _AUTOPILOT_LLM_CALLS[],
                )),
            ))
        end
    catch e
        @warn "Failed to record autopilot telemetry" exception=e
    end
end

function _autopilot_broadcast(msg::Dict)
    try
        BYTE._broadcast(msg)
    catch e
        @warn "Autopilot broadcast failed" exception=e
    end
end

function _build_mind_graph(db, state::Dict{String,Any}, tick::Int,
                            action::String, topic::String)
    nodes = Dict{String,Any}[]
    links = Dict{String,Any}[]

    push!(nodes, Dict{String,Any}(
        "id"=>"spark", "label"=>"SparkByte", "type"=>"self", "val"=>28,
        "detail"=>"gait=$(state["gait"]) drift=$(round(state["drift_pressure"],digits=2)) tick $tick"
    ))

    for (cid, clabel) in [
        ("c-thoughts",   "THOUGHTS"),
        ("c-intentions", "INTENTIONS"),
        ("c-knowledge",  "KNOWLEDGE"),
        ("c-active",     "ACTIVE"),
    ]
        push!(nodes, Dict{String,Any}("id"=>cid,"label"=>clabel,"type"=>"cluster","val"=>14))
        push!(links, Dict{String,Any}("source"=>"spark","target"=>cid))
    end

    push!(nodes, Dict{String,Any}(
        "id"=>"active-now","label"=>first(topic,70),"type"=>"action",
        "val"=>10,"parent"=>"c-active",
        "detail"=>"tick $tick action: $action\n$topic"
    ))
    push!(links, Dict{String,Any}("source"=>"c-active","target"=>"active-now"))

    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT id, thought, type FROM thoughts ORDER BY id DESC LIMIT 8"))
        for r in eachrow(rows)
            id = "t-$(r.id)"
            txt = first(string(r.thought), 80)
            push!(nodes, Dict{String,Any}("id"=>id,"label"=>txt,"type"=>"thought",
                "val"=>6,"parent"=>"c-thoughts","detail"=>string(r.thought)))
            push!(links, Dict{String,Any}("source"=>"c-thoughts","target"=>id))
        end
    catch e; @warn "mind_graph thoughts" exception=e end

    try
        rows = DataFrame(SQLite.DBInterface.execute(db, """
            CREATE TABLE IF NOT EXISTS intentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, tick INTEGER,
                intent TEXT NOT NULL, action_type TEXT DEFAULT 'general',
                status TEXT DEFAULT 'pending', completed_at TEXT)
        """))
    catch e
        @warn "_build_mind_graph: intentions table setup failed" exception=(e, catch_backtrace())
    end
    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT id, intent FROM intentions WHERE status='pending' ORDER BY id DESC LIMIT 8"))
        for r in eachrow(rows)
            id = "i-$(r.id)"
            txt = first(string(r.intent), 80)
            push!(nodes, Dict{String,Any}("id"=>id,"label"=>txt,"type"=>"intention",
                "val"=>7,"parent"=>"c-intentions","detail"=>string(r.intent)))
            push!(links, Dict{String,Any}("source"=>"c-intentions","target"=>id))
        end
    catch e; @warn "mind_graph intentions" exception=e end

    try
        rows = DataFrame(SQLite.DBInterface.execute(db,
            "SELECT id, domain, topic, content FROM knowledge ORDER BY id DESC LIMIT 14"))
        seen = Set{String}()
        for r in eachrow(rows)
            dom = string(r.domain)
            did = "d-$dom"
            if !(dom in seen)
                push!(seen, dom)
                push!(nodes, Dict{String,Any}("id"=>did,"label"=>uppercase(dom),
                    "type"=>"cluster","val"=>8,"parent"=>"c-knowledge"))
                push!(links, Dict{String,Any}("source"=>"c-knowledge","target"=>did))
            end
            kid = "k-$(r.id)"
            ntype = dom=="capability_gaps" ? "gap" : dom=="drafts" ? "draft" : "knowledge"
            push!(nodes, Dict{String,Any}("id"=>kid,"label"=>first(string(r.topic),60),
                "type"=>ntype,"val"=>4,"parent"=>did,"detail"=>string(r.content)))
            push!(links, Dict{String,Any}("source"=>did,"target"=>kid))
        end
    catch e; @warn "mind_graph knowledge" exception=e end

    return Dict{String,Any}("type"=>"mind_graph","nodes"=>nodes,"links"=>links)
end