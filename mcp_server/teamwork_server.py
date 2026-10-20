"""Bounded MCP task and message board for OpenCode teamwork.

This server coordinates OpenCode sessions and reads SparkByte's existing local
control API. It does not execute shell commands or edit project files.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("OPENCODE_TEAMWORK_DB", str(ROOT / ".opencode" / "teamwork.sqlite3")))
SPARKBYTE_STATE_URL = os.environ.get("SPARKBYTE_CONTROL_URL", "http://127.0.0.1:8081/control/state")
MAX_TEAM_TASKS = 8
MAX_ACTIVE_TASKS = 3
MAX_MESSAGES = 40
MAX_TEXT = 3000
_lock = threading.RLock()

mcp = FastMCP("sparkbyte-teamwork")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
            created_at REAL NOT NULL, task_limit INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
            team_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
            joined_at REAL NOT NULL, PRIMARY KEY(team_id, name),
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, team_id TEXT NOT NULL, title TEXT NOT NULL,
            assignee TEXT NOT NULL, instructions TEXT NOT NULL, status TEXT NOT NULL,
            created_at REAL NOT NULL, started_at REAL, finished_at REAL,
            result TEXT, UNIQUE(team_id, title),
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS claims (
            team_id TEXT NOT NULL, task_id TEXT NOT NULL, path TEXT NOT NULL,
            mode TEXT NOT NULL, PRIMARY KEY(team_id, task_id, path)
        );
        CREATE TABLE IF NOT EXISTS messages (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT NOT NULL,
            sender TEXT NOT NULL, recipient TEXT NOT NULL, body TEXT NOT NULL,
            created_at REAL NOT NULL
        );
    """)
    return con


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _clean(value: str, label: str, limit: int = MAX_TEXT) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty")
    if len(value) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return value


def _team(con: sqlite3.Connection, team_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown team id")
    return row


@mcp.tool()
def team_create(name: str, task_limit: int = 4) -> str:
    """Create a bounded coordination team. Task limit is capped at eight."""
    name = _clean(name, "name", 100)
    if not 1 <= task_limit <= MAX_TEAM_TASKS:
        return f"task_limit must be between 1 and {MAX_TEAM_TASKS}"
    team_id = str(uuid.uuid4())
    with _lock, _connect() as con:
        con.execute("INSERT INTO teams VALUES(?,?,?,?,?)", (team_id, name, "active", time.time(), task_limit))
        con.execute("INSERT INTO members VALUES(?,?,?,?)", (team_id, "lead", "orchestrator", time.time()))
    return _json({"team_id": team_id, "name": name, "status": "active", "task_limit": task_limit})


@mcp.tool()
def team_join(team_id: str, member: str, role: str = "worker") -> str:
    """Register one named OpenCode teammate in an existing team."""
    member = _clean(member, "member", 80)
    role = _clean(role, "role", 80)
    with _lock, _connect() as con:
        team = _team(con, team_id)
        if team["status"] != "active":
            return "Team is closed"
        con.execute("INSERT OR IGNORE INTO members VALUES(?,?,?,?)", (team_id, member, role, time.time()))
    return _json({"team_id": team_id, "member": member, "role": role, "joined": True})


@mcp.tool()
def team_delegate(team_id: str, title: str, assignee: str, instructions: str,
                  files: list[str] | None = None, write_files: bool = False) -> str:
    """Add a uniquely titled task; reserve requested paths to prevent edit conflicts.

    Assign separate files to concurrent writers. Read-only tasks may overlap.
    This board records delegation; use OpenCode's Task subagent to execute it.
    """
    title = _clean(title, "title", 160)
    assignee = _clean(assignee, "assignee", 80)
    instructions = _clean(instructions, "instructions")
    files = files or []
    if len(files) > 20:
        return "A task may claim at most 20 paths"
    normalized = [p.replace("\\", "/").strip(" /").casefold() for p in files]
    if any(not p or any(part == ".." for part in p.split("/")) for p in normalized):
        return "Paths must be workspace-relative and cannot escape the workspace"
    task_id = str(uuid.uuid4())
    mode = "write" if write_files else "read"
    with _lock, _connect() as con:
        team = _team(con, team_id)
        if team["status"] != "active":
            return "Team is closed"
        count = con.execute("SELECT count(*) FROM tasks WHERE team_id=?", (team_id,)).fetchone()[0]
        if count >= team["task_limit"]:
            return "Team task limit reached"
        if con.execute("SELECT 1 FROM members WHERE team_id=? AND name=?", (team_id, assignee)).fetchone() is None:
            return "Assignee must join the team before receiving work"
        if write_files and not normalized:
            return "A write task must declare at least one file path"
        for path in normalized:
            if write_files:
                existing = con.execute(
                    "SELECT path FROM claims WHERE mode='write' AND task_id<>?",
                    (task_id,),
                ).fetchall()
                for claim in existing:
                    claimed = claim["path"]
                    if path == claimed or path.startswith(claimed + "/") or claimed.startswith(path + "/"):
                        return f"Write path overlaps an active claim: {path} conflicts with {claimed}"
        try:
            con.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (task_id, team_id, title, assignee, instructions, "queued", time.time(), None, None, None))
        except sqlite3.IntegrityError:
            return "Duplicate task title rejected (prevents duplicate delegation loops)"
        for path in normalized:
            con.execute("INSERT INTO claims VALUES(?,?,?,?)", (team_id, task_id, path, mode))
    return _json({"task_id": task_id, "team_id": team_id, "title": title, "assignee": assignee,
                  "status": "queued", "files": normalized, "write_files": write_files})


@mcp.tool()
def team_claim(team_id: str, task_id: str, member: str) -> str:
    """Claim an assigned task. Active work is globally capped at three."""
    with _lock, _connect() as con:
        _team(con, team_id)
        row = con.execute("SELECT * FROM tasks WHERE id=? AND team_id=?", (task_id, team_id)).fetchone()
        if row is None:
            return "Unknown task"
        if row["assignee"] != member:
            return "Only the assigned teammate may claim this task"
        if row["status"] == "running":
            return "Duplicate claim rejected; task is already running"
        if row["status"] != "queued":
            return f"Task cannot be claimed from status {row['status']}"
        active = con.execute("SELECT count(*) FROM tasks WHERE team_id=? AND status='running'", (team_id,)).fetchone()[0]
        if active >= MAX_ACTIVE_TASKS:
            return f"Concurrency limit reached ({MAX_ACTIVE_TASKS})"
        now = time.time()
        con.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?", (now, task_id))
    return _json({"task_id": task_id, "status": "running", "started_at": now})


@mcp.tool()
def team_finish(team_id: str, task_id: str, member: str, result: str) -> str:
    """Record a bounded task result and release its path claims."""
    result = _clean(result, "result")
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM tasks WHERE id=? AND team_id=?", (task_id, team_id)).fetchone()
        if row is None:
            return "Unknown task"
        if row["assignee"] != member:
            return "Only the assigned teammate may finish this task"
        if row["status"] != "running":
            return f"Task cannot be finished from status {row['status']}"
        con.execute("UPDATE tasks SET status='done', result=?, finished_at=? WHERE id=?",
                    (result, time.time(), task_id))
        con.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
    return _json({"task_id": task_id, "status": "done", "result": result})


@mcp.tool()
def team_fail(team_id: str, task_id: str, member: str, reason: str) -> str:
    """Mark an unsuccessful task and release its write claims for recovery."""
    reason = _clean(reason, "reason", 1000)
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM tasks WHERE id=? AND team_id=?", (task_id, team_id)).fetchone()
        if row is None:
            return "Unknown task"
        if row["assignee"] != member:
            return "Only the assigned teammate may fail this task"
        if row["status"] != "running":
            return f"Task cannot be failed from status {row['status']}"
        con.execute("UPDATE tasks SET status='failed', result=?, finished_at=? WHERE id=?",
                    (reason, time.time(), task_id))
        con.execute("DELETE FROM claims WHERE task_id=?", (task_id,))
    return _json({"task_id": task_id, "status": "failed", "reason": reason})


@mcp.tool()
def team_message(team_id: str, sender: str, recipient: str, body: str) -> str:
    """Send a capped, persistent direct message between registered team members."""
    body = _clean(body, "body")
    with _lock, _connect() as con:
        _team(con, team_id)
        for member in (sender, recipient):
            if con.execute("SELECT 1 FROM members WHERE team_id=? AND name=?", (team_id, member)).fetchone() is None:
                return f"Unknown team member: {member}"
        count = con.execute("SELECT count(*) FROM messages WHERE team_id=?", (team_id,)).fetchone()[0]
        if count >= MAX_MESSAGES:
            return f"Team message limit reached ({MAX_MESSAGES})"
        cur = con.execute("INSERT INTO messages(team_id,sender,recipient,body,created_at) VALUES(?,?,?,?,?)",
                          (team_id, sender, recipient, body, time.time()))
    return _json({"message_id": cur.lastrowid, "team_id": team_id, "sender": sender,
                  "recipient": recipient, "delivered": True})


@mcp.tool()
def team_status(team_id: str) -> str:
    """Read the team's members, task lifecycle/timing, results, and recent messages."""
    with _lock, _connect() as con:
        team = _team(con, team_id)
        members = [dict(r) for r in con.execute("SELECT name,role,joined_at FROM members WHERE team_id=? ORDER BY joined_at", (team_id,))]
        tasks = [dict(r) for r in con.execute("SELECT id,title,assignee,status,created_at,started_at,finished_at,result FROM tasks WHERE team_id=? ORDER BY created_at", (team_id,))]
        messages = [dict(r) for r in con.execute("SELECT seq,sender,recipient,body,created_at FROM messages WHERE team_id=? ORDER BY seq DESC LIMIT 20", (team_id,))]
    return _json({"team": dict(team), "members": members, "tasks": tasks, "messages": list(reversed(messages))})


@mcp.tool()
def sparkbyte_runtime_state() -> str:
    """Read live runtime diagnostics from SparkByte's existing local HTTP API."""
    from urllib.request import urlopen

    try:
        with urlopen(SPARKBYTE_STATE_URL, timeout=3) as response:
            body = response.read(65537)
        if len(body) > 65536:
            return _json({"ok": False, "error": "SparkByte state response exceeds 64 KiB"})
        data = json.loads(body.decode("utf-8"))
        return _json(data)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc), "url": SPARKBYTE_STATE_URL})


if __name__ == "__main__":
    mcp.run(transport="stdio")
