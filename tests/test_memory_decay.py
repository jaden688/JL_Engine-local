from __future__ import annotations

import json

from jl_engine_core.engine_core import JLEngineCore
from jl_engine_core.hybrid_memory import (
    InMemoryHybridMemory,
    RECENT_INTERACTION_LIMIT,
    SQLiteHybridMemory,
    compact_recent_interactions,
)


def test_engine_core_skips_synthetic_memory_turns():
    engine = JLEngineCore.__new__(JLEngineCore)

    assert (
        engine._should_store_memory_turn(  # type: ignore[attr-defined]
            "Continue assisting the user. If browser navigation is needed, emit `BROWSER_OPEN: https://...`.",
            '{"final":"ok"}',
        )
        is False
    )
    assert (
        engine._should_store_memory_turn(  # type: ignore[attr-defined]
            "Reply with your agent name only.",
            "SparkByte",
        )
        is False
    )
    assert (
        engine._should_store_memory_turn(  # type: ignore[attr-defined]
            "hey byteee :3",
            "Hey there, cutie! What can I do for you today?",
        )
        is True
    )
    assert (
        engine._should_store_memory_turn(  # type: ignore[attr-defined]
            "I was hoping you could tell me what your capabilities are",
            (
                "I'm your sassy assistant integrated into the JL Engine. "
                "I can interpret your commands, assist with tasks, and provide information. "
                "What's your goal?"
            ),
        )
        is False
    )


def test_engine_core_sanitizes_repeated_capability_loops_from_recent_memory():
    engine = JLEngineCore.__new__(JLEngineCore)
    interactions = [
        {
            "user_message": "I was kind of hoping you would tell me what your capabilities are",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. My capabilities include "
                "interpreting your commands, assisting with tasks, and providing information. "
                "I can call tools to complete real-world actions like interacting with files, "
                "running shell commands, or creating temporary tools. I can also provide direct "
                "answers without tool calls. Let's focus on what you need help with. What's your goal?"
            ),
        },
        {
            "user_message": "hey byteee :3",
            "output": "Hey there, cutie! What can I do for you today?",
        },
        {
            "user_message": "You're hole",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. I can interpret your commands, "
                "assist with tasks, and provide information. I can also call tools to complete real-world "
                "actions like interacting with files, running shell commands, or creating temporary tools. "
                "What's your goal?"
            ),
        },
        {
            "user_message": "Continue assisting the user. If browser navigation is needed, emit `BROWSER_OPEN: https://...`.",
            "output": '{"final":"I am synthetic."}',
        },
    ]

    cleaned = engine._sanitize_recent_interactions(interactions)  # type: ignore[attr-defined]

    assert len(cleaned) == 1
    assert cleaned[0]["user_message"] == "hey byteee :3"
    assert all("Continue assisting the user" not in item["user_message"] for item in cleaned)


def test_in_memory_hybrid_memory_trims_recent_interactions_to_limit():
    memory = InMemoryHybridMemory()

    for idx in range(RECENT_INTERACTION_LIMIT + 5):
        memory.update_after_turn(
            agent_id="SparkByte",
            user_message=f"user-{idx}",
            output=f"output-{idx}",
            engine_state={"gait": "walk", "rhythm": "flip", "aperture_mode": "OPEN", "dynamic": {}},
        )

    recent = memory.get_context("SparkByte")["agent_memory"]["recent_interactions"]

    assert len(recent) == RECENT_INTERACTION_LIMIT
    assert recent[0]["user_message"] == f"user-{5}"
    assert recent[-1]["user_message"] == f"user-{RECENT_INTERACTION_LIMIT + 4}"


def test_compact_recent_interactions_keeps_latest_capability_loop_only():
    interactions = [
        {
            "user_message": "what can you do",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. "
                "I can interpret your commands, assist with tasks, and provide information. "
                "What's your goal?"
            ),
        },
        {
            "user_message": "hey byteee :3",
            "output": "Hey there, cutie! What can I do for you today?",
        },
        {
            "user_message": "tell me that again",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. "
                "I can help with tasks, provide information, and even call tools. "
                "What's your goal?"
            ),
        },
    ]

    compacted = compact_recent_interactions(interactions)

    assert [item["user_message"] for item in compacted] == ["hey byteee :3"]


def test_compact_recent_interactions_keeps_latest_copy_of_repeated_user_prompt():
    interactions = [
        {
            "user_message": "I was hoping you could tell me that",
            "output": "First answer.",
        },
        {
            "user_message": "hey byteee :3",
            "output": "Hey there, cutie! What can I do for you today?",
        },
        {
            "user_message": "I was hoping you could tell me that",
            "output": "Better answer.",
        },
    ]

    compacted = compact_recent_interactions(interactions)

    assert [item["user_message"] for item in compacted] == [
        "hey byteee :3",
        "I was hoping you could tell me that",
    ]
    assert compacted[-1]["output"] == "Better answer."


def test_sqlite_hybrid_memory_compacts_persisted_recent_interactions(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    memory = SQLiteHybridMemory(db_path)
    recent = [
        {
            "user_message": "what can you do",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. "
                "I can interpret your commands, assist with tasks, and provide information. "
                "What's your goal?"
            ),
        },
        {
            "user_message": "Continue assisting the user. If browser navigation is needed, emit `BROWSER_OPEN: https://...`.",
            "output": '{"final":"synthetic"}',
        },
        {
            "user_message": "tell me that again",
            "output": (
                "I'm your sassy assistant integrated into the JL Engine. "
                "I can help with tasks, provide information, and even call tools. "
                "What's your goal?"
            ),
        },
    ]
    payload = {
        "recent_interactions": recent,
        "mood": "neutral",
        "notes": {},
        "dynamic_state": {},
    }
    memory._save_agent("SparkByte", payload)  # type: ignore[attr-defined]

    compacted = memory.get_context("SparkByte")["agent_memory"]["recent_interactions"]

    assert compacted == []

    reloaded = json.loads(
        memory._connect()  # type: ignore[attr-defined]
        .execute("SELECT payload FROM agent_memory WHERE agent_id = ?", ("SparkByte",))
        .fetchone()[0]
    )
    assert reloaded["recent_interactions"] == []
