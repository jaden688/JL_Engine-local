Generated agent payloads live in this folder.

Rules:
- Hand-managed canonical MPF agents stay in `jl_engine_core/data/agents/`.
- Runtime-generated or auto-generated agents are written here instead of the top-level agent folder.
- Registry entries in `JL_Agents.mpf.json` may point here with a relative `jl_agent_file` like `generated/MyAgent.json`.
- Generated agents must still use the same JSON agent payload format as canonical agents.
