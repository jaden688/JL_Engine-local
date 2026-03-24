# JL Engine Memory Layering (HYBRID / SHARED_ONLY / PERSONA_ONLY)

This summarizes the new layered persistence so you can find it quickly when wiring devices or debugging saved state.

## File layout
- `memory/base_core.json` (optional, read-only): seed facts shared to all personas; never written back.
- `memory/shared.json`: cross-persona/shared memories.
- `memory/personas/<persona_id>.json`: private persona memories.
- `memory/sessions/<persona_id>/<session_id>.json`: optional session overlays tagged with `_session: true` to isolate a run without touching persistent persona data.

Legacy `memory/memory_store.json` is auto-migrated on first load into the layout above; the original file is left as a backup.

## Modes (UI dropdown)
- `HYBRID`: read/write shared + persona + session; base_core is merged for reads only.
- `PERSONA_ONLY`: read/write persona + session; shared is ignored.
- `SHARED_ONLY`: read/write shared; persona/session is ignored.

## Controls (UI)
- Memory card shows current session label.
- “New Session” button: creates a fresh session id (`sess_yyyymmddhhMMSS`), clears the current persona’s session overlay, and writes it to `sessions/<persona>/<session>.json`.
- `/memory clear`: clears the current persona store for the active key, then saves with the selected mode.

## Runtime hooks (main_app.py)
- Load: `load_all_memories(..., persona_id, session_id)` pulls base_core + shared + persona + session, tagging base_core entries with `_base_core` and session entries with `_session`.
- Save: `save_all_memories(..., memory_mode, persona_id, session_id)` honors the mode, strips `_base_core` from writes, and splits persona vs session entries.
- Entries tagged with `_session` stay in the session overlay; `_base_core` entries are read-only and never persisted back into shared.

## Cross-device sync (stub)
- `memory_sync.py` defines `MemorySyncAdapter` with `push/pull` placeholders.
- Config hook in `JLframe_Engine_Framework.json` under `jl_engine.memory.sync`:
  ```json
  "memory": {
    "sync": {
      "enabled": true,
      "provider": "http|s3|custom",
      "endpoint": "...",
      "auth": "...",
      "user_id": "user123",
      "device_id": "device123"
    }
  }
  ```
- Adapter is currently a no-op; implement provider-specific logic there when ready.
