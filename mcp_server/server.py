"""SparkByte MCP server for engine data, runtime turns, and optional hardware tools."""

import sqlite3
import json
import os
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent

# Resolve sparkbyte_memory.db path based on environment or directory existence
state_dir = os.environ.get("SPARKBYTE_STATE_DIR", "").strip() or None
STATE_DIR = Path(state_dir) if state_dir else ROOT / "data"
if state_dir:
    SB_DB = Path(state_dir) / "sparkbyte_memory.db"
else:
    data_db = ROOT / "data" / "sparkbyte_memory.db"
    if data_db.exists():
        SB_DB = data_db
    else:
        SB_DB = ROOT / "sparkbyte_memory.db"

# Same monorepo layout as SparkByte: Julian quarry lives next to engine unless overridden.
_EMBEDDED_QUARRY = ROOT / "JulianMetaMorph" / "JulianMetaMorph" / "data" / "quarry.db"
JUL_DB = Path(os.environ.get("JULIAN_DB", str(_EMBEDDED_QUARRY)))
SKILL_MD = Path(os.environ.get("JULIAN_SKILL", str(Path.home() / ".claude" / "skills" / "julian" / "SKILL.md")))

mcp = FastMCP("sparkbyte")

# ── DB helpers (read-only) ─────────────────────────────────────────────────────
def _sb(query: str, params: tuple = ()) -> list[dict]:
    if not SB_DB.exists():
        return [{"error": f"sparkbyte_memory.db not found at {SB_DB} — is SparkByte running?"}]
    con = sqlite3.connect(SB_DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        con.close()

def _jul(query: str, params: tuple = ()) -> list[dict]:
    if not JUL_DB.exists():
        return [{"error": f"quarry.db not found at {JUL_DB} — is Julian running?"}]
    con = sqlite3.connect(JUL_DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        con.close()

# ── Resources ──────────────────────────────────────────────────────────────────
@mcp.resource("sparkbyte://skill")
def skill_context() -> str:
    """Full SparkByte/Julian project context — architecture, tools, commands, bridge."""
    if SKILL_MD.exists():
        return SKILL_MD.read_text(encoding="utf-8")
    # fallback: inline summary
    return f"""
# SparkByte / JLEngine
Julia-native AI agent engine with behavioral control layer (gait/rhythm/aperture/drift).
Root: {ROOT}
Entry: julia --project=. start.jl | UI: http://127.0.0.1:8081

# JulianMetaMorph (joined in monorepo)
quarry: {JUL_DB}
Entry: python -m julian_metamorph.cli | UI: http://127.0.0.1:8765
""".strip()

@mcp.resource("sparkbyte://agents")
def agents() -> str:
    """All indexed agents with their tone and boot prompt summary."""
    rows = _sb("SELECT name, tone, description, substr(boot_prompt,1,300) as boot_prompt FROM agents ORDER BY name")
    return json.dumps(rows, indent=2)

# ── Tools ──────────────────────────────────────────────────────────────────────
@mcp.tool()
def get_engine_state() -> str:
    """
    Latest SparkByte engine snapshot — gait, rhythm, aperture, behavior state,
    drift pressure, stability score, model, agent.
    """
    rows = _sb("""
        SELECT timestamp, agent, model, gait, rhythm_mode, aperture_mode,
               aperture_temp, behavior_state, behavior_expressiveness,
               drift_pressure, advisory_bias, advisory_emotional_drift, advisory_msg
        FROM turn_snapshots ORDER BY id DESC LIMIT 1
    """)
    if not rows:
        return "No turn snapshots yet — SparkByte hasn't had a conversation."
    return json.dumps(rows[0], indent=2)

@mcp.tool()
def get_thoughts(limit: int = 10, thought_type: str = "diary") -> str:
    """
    Recent SparkByte thoughts/diary entries.
    thought_type: 'diary' | 'reasoning' | 'all'
    limit: number of entries (max 50)
    """
    limit = min(limit, 50)
    if thought_type == "all":
        rows = _sb("SELECT timestamp, agent, type, mood, thought FROM thoughts ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = _sb("SELECT timestamp, agent, type, mood, thought FROM thoughts WHERE type=? ORDER BY id DESC LIMIT ?", (thought_type, limit))
    return json.dumps(rows, indent=2)

@mcp.tool()
def list_forged_tools() -> str:
    """
    All tools SparkByte has forged at runtime — name, description, call count, last used.
    Includes both built-in and dynamically forged tools.
    """
    rows = _sb("SELECT name, description, call_count, last_used, is_dynamic, forged_at FROM tools ORDER BY call_count DESC")
    return json.dumps(rows, indent=2)

@mcp.tool()
def list_agents() -> str:
    """List agents indexed in SparkByte's persistent agent registry."""
    rows = _sb("SELECT name, tone, description, substr(boot_prompt,1,500) as boot_prompt FROM agents ORDER BY name")
    return json.dumps(rows, indent=2)

@mcp.tool()
def list_forged_tools_registry() -> str:
    """Read the on-disk dynamic tool registry when available."""
    registry_path = STATE_DIR / "dynamic_tools_registry.json"
    if not registry_path.exists() and not state_dir:
        legacy_registry_path = ROOT / "dynamic_tools_registry.json"
        if legacy_registry_path.exists():
            registry_path = legacy_registry_path
    if not registry_path.exists():
        return json.dumps({"error": f"dynamic_tools_registry.json not found at {registry_path}"})
    try:
        return json.dumps(json.loads(registry_path.read_text(encoding="utf-8")), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def query_memory(tag: str = "", key: str = "", limit: int = 20) -> str:
    """
    Query SparkByte's persistent memory store.
    tag: filter by tag (e.g. 'self_src', 'self_tree', 'user_note')
    key: filter by key (partial match)
    """
    limit = min(limit, 100)
    if tag and key:
        rows = _sb("SELECT timestamp, tag, key, substr(content,1,500) as content FROM memory WHERE tag=? AND key LIKE ? ORDER BY id DESC LIMIT ?", (tag, f"%{key}%", limit))
    elif tag:
        rows = _sb("SELECT timestamp, tag, key, substr(content,1,500) as content FROM memory WHERE tag=? ORDER BY id DESC LIMIT ?", (tag, limit))
    elif key:
        rows = _sb("SELECT timestamp, tag, key, substr(content,1,500) as content FROM memory WHERE key LIKE ? ORDER BY id DESC LIMIT ?", (f"%{key}%", limit))
    else:
        rows = _sb("SELECT timestamp, tag, key, substr(content,1,200) as content FROM memory ORDER BY id DESC LIMIT ?", (limit,))
    return json.dumps(rows, indent=2)

@mcp.tool()
def get_telemetry(limit: int = 20) -> str:
    """Recent SparkByte telemetry events — what the engine has been doing."""
    limit = min(limit, 100)
    rows = _sb("SELECT timestamp, event, agent, model, turn_number FROM telemetry ORDER BY id DESC LIMIT ?", (limit,))
    return json.dumps(rows, indent=2)

@mcp.tool()
def get_recent_telemetry(limit: int = 20) -> str:
    """Compatibility alias for clients that expect the older telemetry tool name."""
    return get_telemetry(limit)

@mcp.tool()
def search_julian_quarry(query: str, limit: int = 10) -> str:
    """
    Full-text search Julian's code quarry for patterns/implementations.
    Returns file hits with repo, path, language, license, score, and why.
    """
    limit = min(limit, 30)
    rows = _jul("""
        SELECT f.repo_full_name, f.file_path, f.language, f.license_spdx,
               h.score, h.category, h.why, substr(h.symbols_json,1,200) as symbols
        FROM hits h
        JOIN files f ON h.file_id = f.id
        WHERE h.why LIKE ? OR f.file_path LIKE ?
        ORDER BY h.score DESC LIMIT ?
    """, (f"%{query}%", f"%{query}%", limit))
    if not rows:
        # fallback: FTS on content
        rows = _jul("""
            SELECT f.repo_full_name, f.file_path, f.language, f.license_spdx,
                   substr(f.content,1,300) as preview
            FROM files f
            WHERE f.content LIKE ?
            ORDER BY f.id DESC LIMIT ?
        """, (f"%{query}%", limit))
    return json.dumps(rows, indent=2)

@mcp.tool()
def get_knowledge(domain: str = "", limit: int = 20) -> str:
    """
    Query SparkByte's knowledge base.
    domain: 'engine_capabilities' | 'tool_schema' | 'engine_framework' | '' for all
    """
    limit = min(limit, 50)
    if domain:
        rows = _sb("SELECT domain, topic, substr(content,1,400) as content, source FROM knowledge WHERE domain=? LIMIT ?", (domain, limit))
    else:
        rows = _sb("SELECT domain, topic, substr(content,1,200) as content, source FROM knowledge ORDER BY id DESC LIMIT ?", (limit,))
    return json.dumps(rows, indent=2)

@mcp.tool()
def run_turn(message: str) -> str:
    """
    Send a message to the running JL Engine (via A2A JSON-RPC) to execute a turn.
    Returns the engine's text response and updates the state.
    """
    import urllib.request
    import urllib.error

    url = "http://127.0.0.1:8082"
    payload = {
        "jsonrpc": "2.0",
        "id": "mcp_turn",
        "method": "tasks/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": message}]
            }
        }
    }
    req_data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("A2A_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url,
        data=req_data,
        headers=headers,
    )
    try:
        # 120 second timeout for deep reasoning / tools execution models
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if "error" in res_data:
                err_info = res_data["error"]
                if isinstance(err_info, dict):
                    return f"Error from engine (code {err_info.get('code')}): {err_info.get('message')}"
                return f"Error from engine: {err_info}"
            task = res_data.get("result", {})
            history = task.get("history", [])
            agent_replies = [h for h in history if h.get("role") == "ROLE_AGENT"]
            if agent_replies:
                parts = agent_replies[-1].get("parts", [])
                texts = [p.get("text", "") for p in parts if "text" in p]
                return "\n".join(texts)
            return "Turn executed, but no reply was found in history."
    except urllib.error.URLError as e:
        return f"Error connecting to JLEngine A2A server on port 8082: {e.reason}\nIs SparkByte/JLEngine running? Start it via 'julia --project=. start.jl' to enable execution."
    except Exception as e:
        return f"Error: {e}"

# ── Ruida laser tools ──────────────────────────────────────────────────────────
def _ruida_swizzle(data: bytes, magic: int) -> bytes:
    out = bytearray(len(data))
    for i, b in enumerate(data):
        b ^= (b >> 7) & 0xFF
        b ^= (b << 7) & 0xFF
        b ^= (b >> 7) & 0xFF
        b ^= magic
        b  = (b + 1) & 0xFF
        out[i] = b
    return bytes(out)

def _ruida_unswizzle(data: bytes, magic: int) -> bytes:
    out = bytearray(len(data))
    for i, b in enumerate(data):
        b  = (b - 1) & 0xFF
        b ^= magic
        b ^= (b >> 7) & 0xFF
        b ^= (b << 7) & 0xFF
        b ^= (b >> 7) & 0xFF
        out[i] = b
    return bytes(out)

def _enc_coord(mm: float) -> bytes:
    v = int(abs(mm) * 1000)
    return bytes([(v >> s) & 0x7F for s in (28, 21, 14, 7, 0)])

def _enc_speed(mm_s: float) -> bytes:
    v = int(mm_s * 1000)
    return bytes([(v >> s) & 0x7F for s in (28, 21, 14, 7, 0)])

def _enc_power(pct: float) -> bytes:
    v = min(int(pct * 163.84), 0x3FFF)
    return bytes([(v >> 7) & 0x7F, v & 0x7F])

def _decode_response(resp: bytes, rcv_magic: int = 0x88) -> list[dict]:
    dec = _ruida_unswizzle(resp, rcv_magic)
    results = []
    i = 0
    while i + 6 < len(dec):
        code = dec[i]
        axis = dec[i + 1]
        v = 0
        for b in dec[i + 2:i + 7]:
            v = (v << 7) | b
        results.append({
            "code": f"0x{code:02X}",
            "axis": {0: "X", 1: "Y", 2: "Z", 3: "U"}.get(axis, str(axis)),
            "value_um": v,
            "value_mm": round(v / 1000, 3),
        })
        i += 7
    return results

@mcp.tool()
def ruida_status(port: str = "COM3") -> str:
    """
    Check Ruida laser controller connection status over serial.
    Returns port state (CTS/DSR) and any data the machine sends back.
    The machine responds with position data after receiving a job.
    Use ruida_send_job() to send a job and read positions back.
    port: COM port (default COM3)
    """
    try:
        import serial, time
    except ImportError:
        return json.dumps({"error": "pyserial not installed — run: pip install pyserial"})

    try:
        s = serial.Serial(port, 115200, timeout=2)
        s.rts = True; s.dtr = True
        time.sleep(0.2)
        cts = s.cts; dsr = s.dsr
        # Read any pending data
        pending = s.read(64)
        s.close()
        return json.dumps({
            "port": port,
            "connected": cts or dsr,
            "cts": cts,
            "dsr": dsr,
            "pending_bytes": pending.hex() if pending else "",
            "note": "CTS+DSR=True means machine is powered and connected. Use ruida_send_job() to send a job.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "port": port})

@mcp.tool()
def ruida_send_job(
    port: str = "COM3",
    filename: str = "MYJOB",
    origin_x_mm: float = 10.0,
    origin_y_mm: float = 10.0,
    width_mm: float = 100.0,
    height_mm: float = 50.0,
    speed_mm_s: float = 18.0,
    power_pct: float = 58.0,
    shape: str = "rect",
    auto_start: bool = False,
) -> str:
    """
    Send a laser job to the Ruida controller over serial.
    By default, the job is uploaded but not started. Set auto_start=true to also
    send START_PROCESS (0xD8 0x00) and begin cutting immediately.

    port: COM port (default COM3)
    filename: name shown on Ruida display (max 9 chars)
    origin_x_mm / origin_y_mm: job top-left corner on the bed (mm)
    width_mm / height_mm: job bounding box (mm)
    speed_mm_s: cut speed (mm/s, typical 15-20 for 6mm MDF)
    power_pct: laser power 0-100% — HARD LIMIT 60% on this machine
    shape: 'rect' = rectangle border | 'circle' = circle | 'cross' = crosshair test
    auto_start: if True, sends START_PROCESS after upload so the machine begins cutting immediately
    """
    import math

    numeric_args = {
        "origin_x_mm": origin_x_mm,
        "origin_y_mm": origin_y_mm,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "speed_mm_s": speed_mm_s,
        "power_pct": power_pct,
    }
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in numeric_args.values()
    ):
        return json.dumps({"error": "All dimensions, speed, and power must be finite numbers."})
    if origin_x_mm < 0 or origin_y_mm < 0:
        return json.dumps({"error": "Job origin coordinates must be non-negative."})
    if width_mm <= 0 or height_mm <= 0:
        return json.dumps({"error": "Job width and height must be greater than zero."})
    if not 0 < speed_mm_s <= 200:
        return json.dumps({"error": "Speed must be greater than 0 and at most 200mm/s."})
    if not 0 <= power_pct <= 60:
        return json.dumps({"error": "Power must be between 0 and the hard limit of 60%."})
    if not isinstance(auto_start, bool):
        return json.dumps({"error": "auto_start must be a boolean; set true only to start the job immediately."})
    if not isinstance(filename, str) or not filename or any(ord(char) < 0x20 or ord(char) > 0x7E for char in filename):
        return json.dumps({"error": "Filename must contain printable ASCII characters."})
    if shape not in ("rect", "circle", "cross"):
        return json.dumps({"error": f"Unknown shape '{shape}'. Use: rect | circle | cross"})

    try:
        import serial, time
    except ImportError:
        return json.dumps({"error": "pyserial not installed"})

    SND_MAGIC = 0x11
    RCV_MAGIC = 0x88
    ox, oy = origin_x_mm, origin_y_mm
    w, h   = width_mm, height_mm
    fname  = filename[:9]

    buf = bytearray()
    buf += b"\xD8\x12"                                           # RD file start
    buf += b"\xE7\x01" + fname.encode() + b"\x00"              # SET_FILENAME
    buf += b"\xE7\x50" + _enc_coord(ox)     + _enc_coord(oy)   # DOC_MIN
    buf += b"\xE7\x51" + _enc_coord(ox + w) + _enc_coord(oy + h) # DOC_MAX
    buf += b"\xC9\x02" + _enc_speed(speed_mm_s)               # speed
    buf += b"\xC6\x01" + _enc_power(max(power_pct - 3, 0))    # min power
    buf += b"\xC6\x02" + _enc_power(power_pct)                # max power
    buf += b"\xCA\x06\x00"                                     # cut mode

    def move(x, y): return bytes(b"\x88") + _enc_coord(x) + _enc_coord(y)
    def cut(x, y):  return bytes(b"\xA8") + _enc_coord(x) + _enc_coord(y)

    if shape == "rect":
        CR = min(8.0, w / 4, h / 4)
        buf += move(ox + CR, oy)
        buf += cut(ox + w - CR, oy)
        buf += cut(ox + w, oy + CR)
        buf += cut(ox + w, oy + h - CR)
        buf += cut(ox + w - CR, oy + h)
        buf += cut(ox + CR, oy + h)
        buf += cut(ox, oy + h - CR)
        buf += cut(ox, oy + CR)
        buf += cut(ox + CR, oy)
    elif shape == "circle":
        r = min(w, h) / 2
        cx, cy = ox + w / 2, oy + h / 2
        segs = 64
        for i in range(segs + 1):
            a = 2 * math.pi * i / segs
            px, py = cx + r * math.cos(a), cy + r * math.sin(a)
            buf += (move if i == 0 else cut)(px, py)
    elif shape == "cross":
        cx, cy = ox + w / 2, oy + h / 2
        buf += move(ox, cy);     buf += cut(ox + w, cy)
        buf += move(cx, oy);     buf += cut(cx, oy + h)
    else:
        return json.dumps({"error": f"Unknown shape '{shape}'. Use: rect | circle | cross"})

    buf += move(0, 0)
    buf += b"\xD7"   # END_OF_FILE

    payload = _ruida_swizzle(bytes(buf), SND_MAGIC)

    try:
        s = serial.Serial(port, 115200, timeout=5)
        s.rts = True; s.dtr = True
        time.sleep(0.2)
        for i in range(0, len(payload), 1000):
            s.write(payload[i:i + 1000])
            time.sleep(0.01)
        time.sleep(1.0)
        resp = s.read(256)

        start_resp = b""
        if auto_start:
            # Send START_PROCESS (0xD8 0x00) — the programmatic equivalent of pressing Start on the panel
            start_cmd = _ruida_swizzle(bytes([0xD8, 0x00]), SND_MAGIC)
            s.write(start_cmd)
            time.sleep(0.5)
            start_resp = s.read(64)

        s.close()
    except Exception as e:
        return json.dumps({"error": str(e)})

    positions = _decode_response(resp, RCV_MAGIC) if resp else []
    result = {
        "sent_bytes": len(payload),
        "filename": fname,
        "shape": shape,
        "speed_mm_s": speed_mm_s,
        "power_pct": power_pct,
        "origin_mm": [ox, oy],
        "size_mm": [w, h],
        "response_bytes": len(resp),
        "positions_after": positions,
        "auto_started": auto_start,
        "start_response_bytes": len(start_resp),
        "start_response_hex": start_resp.hex() if start_resp else "",
        "status": "started" if (auto_start and start_resp) else ("job_sent" if resp else "no_response"),
    }
    return json.dumps(result, indent=2)

# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")
