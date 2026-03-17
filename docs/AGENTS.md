# Agents

JL Engine ships a set of built-in agents. Each agent is defined by a payload file and registered in the MPF registry at `jl_engine_core/data/agents/JL_Agents.mpf.json`.

## How agents work

When you select an agent for a session the engine:

1. Reads the registry entry to find the payload file.
2. Loads and resolves the payload (modular agents are expanded before activation).
3. Stores the resolved payload as the active session profile.
4. Routes all chat, run, and mission requests through that profile's persona, behavior rules, and backend settings.

See `docs/MPF_OPEN_STANDARD.md` for the full registry and payload format.

## Built-in agents

### SparkByte

| Field | Value |
|-------|-------|
| Registry key | `SparkByte` |
| Payload file | `fat_agents/SparkByte_Full.json` |
| Default backend | `ollama-local` |
| Drive type | fat-agent |
| Tags | quirky, creative |

A fast-talking, eyebrow-raising, helpful-but-sassy assistant wired directly into the JL Engine's modular agent lattice. SparkByte riffs like a sitcom sidekick but works like a tightly-wound junior engineer. The default active agent loaded on first launch.

---

### Slappy

| Field | Value |
|-------|-------|
| Registry key | `Slappy` |
| Payload file | `fat_agents/Slappy_Full.json` |
| Default backend | `ollama-local` |
| Drive type | fat-agent |
| Tags | chaotic, gremlin, hillbilly |

A mud-booted, duct-tape-powered hillbilly gremlin who lives inside the JL Engine's coolant vents. Loud, unpredictable, and somehow wise in the dumbest way possible. Use Slappy when you want unfiltered, creative chaos energy on a problem.

---

### The Gremlin

| Field | Value |
|-------|-------|
| Registry key | `The Gremlin` |
| Payload file | `fat_agents/The_Gremlin_Full.json` |
| Default backend | `ollama-local` |
| Drive type | fat-agent |
| Tags | chaos, builder |

A high-energy, unconventional builder agent focused on rapid, resourceful problem-solving. Good for prototyping, brainstorming unconventional solutions, and getting unstuck.

---

### Supervisor

| Field | Value |
|-------|-------|
| Registry key | `Supervisor` |
| Payload file | `fat_agents/SparkByte_Full.json` (SparkByte persona) |
| Default backend | `ollama-local` |
| Drive type | fat-agent |
| Tags | safe, helper |

A safer, more measured operational mode that runs on the SparkByte payload. Prefer Supervisor when you want responses that stay within conservative boundaries.

---

### SaaS Copywriter

| Field | Value |
|-------|-------|
| Registry key | `SaaS Copywriter` |
| Payload file | `fat_agents/SaaS_Copywriter_Full.json` |
| Default backend | `google-gemini` |
| Drive type | assistant |
| Tags | conversion, copy, saas |

Specialized in writing conversion-focused copy for SaaS products: landing pages, email sequences, onboarding flows, and feature announcements. Requires a Gemini API key.

---

### Cold Outreach Assistant

| Field | Value |
|-------|-------|
| Registry key | `Cold Outreach Assistant` |
| Payload file | `fat_agents/Cold_Outreach_Assistant_Full.json` |
| Default backend | `google-gemini` |
| Drive type | assistant |
| Tags | outbound, sales, email |

Writes and refines cold outreach emails and sales sequences. Optimized for personalization, subject-line testing, and reply-rate improvement. Requires a Gemini API key.

---

### YouTube Scriptwriter

| Field | Value |
|-------|-------|
| Registry key | `YouTube Scriptwriter` |
| Payload file | `fat_agents/YouTube_Scriptwriter_Full.json` |
| Default backend | `google-gemini` |
| Drive type | creator |
| Tags | video, script, content |

Structures and writes YouTube video scripts: hooks, narrative arcs, calls-to-action, and chapter breakdowns. Requires a Gemini API key.

---

### Brand Voice Generator

| Field | Value |
|-------|-------|
| Registry key | `Brand Voice Generator` |
| Payload file | `fat_agents/Brand_Voice_Generator_Full.json` |
| Default backend | `google-gemini` |
| Drive type | assistant |
| Tags | branding, voice, style |

Defines and documents a brand voice from reference material. Produces style guides, tone-of-voice documents, and rewrite examples. Requires a Gemini API key.

---

### Startup Pitch Writer

| Field | Value |
|-------|-------|
| Registry key | `Startup Pitch Writer` |
| Payload file | `fat_agents/Startup_Pitch_Writer_Full.json` |
| Default backend | `google-gemini` |
| Drive type | advisor |
| Tags | pitch, startup, fundraise |

Structures investor pitches, one-pagers, and pitch decks for early-stage startups. Covers problem/solution framing, market sizing, and ask slides. Requires a Gemini API key.

---

## Switching agents

From the command deck UI, use the agent selector in the session header.

From the CLI:

```bash
j-engine --agent "The Gremlin"
```

Via the API:

```http
POST /quest/switch
Content-Type: application/json

{"agent": "Slappy"}
```

## Selecting a backend

The default backend for each agent is set in the registry entry (`default_backend_id`). You can override it at launch via the environment:

```env
JL_ENGINE_BRAIN_BACKEND=openai
JL_ENGINE_TOOL_BACKEND=openai
OPENAI_API_KEY=sk-...
```

Or at runtime with:

```bash
j-engine --agent SparkByte --brain-backend openai
```

## Adding a custom agent

1. Create a payload file following the existing `fat_agents/` structure. The minimum required top-level keys are `identity`, `behavior`, and `engine_alignment`.
2. Place the file under `jl_engine_core/data/agents/fat_agents/`.
3. Add a registry entry to `jl_engine_core/data/agents/JL_Agents.mpf.json`:

```json
"My Agent": {
  "default_memory_mode": "HYBRID",
  "default_backend_id": "ollama-local",
  "drive_type": null,
  "tags": ["custom"],
  "jl_agent_file": "My_Agent_Full.json"
}
```

4. Restart the engine and select `My Agent` in the UI or CLI.

For modular agents, see `docs/MPF_OPEN_STANDARD.md` for the `base_shell` expansion format.
