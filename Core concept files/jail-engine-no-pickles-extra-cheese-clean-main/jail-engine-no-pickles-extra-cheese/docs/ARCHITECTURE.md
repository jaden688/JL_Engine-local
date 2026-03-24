# JL Engine V2 – High-Level Architecture

This document summarizes the cleaned-up V2-style architecture that centers
around a single orchestrator: `JLEngineCore` (in `engine_core.py`).

## Core Concepts

- **Headless core**: `JLEngineCore` owns the actual behavior logic and does not
  depend on any GUI frameworks.
- **UI as a client**: `main_app.py` (Tk GUI) should treat the engine as a black
  box:

      reply, telemetry = engine.process_turn(user_text, persona_name="The Helper")

- **Telemetry**: The engine always returns structured telemetry that the GUI/HUD
  can render without re-implementing engine logic.

## Main Modules

- `engine_core.py` – orchestrator that wires together:
  - `BehaviorStateMachine` (behavior_engine.py)
  - `SignalScorer` (conversational_signals.py)
  - `EmotionalAperture` (emotional_aperture.py)
  - `CognitiveModeSelector` (cognitive_modes.py)
  - `RhythmEngine` (rhythm.py)
  - `DriftPressureSystem` (drift_pressure.py)
  - MPF personas via `framework/mpf`
  - Brain backend via `backends.py`

- `behavior_engine.py` – grid-based behavior state machine.

- `cognitive_modes.py` / `cognitive_gears.py` – reasoning modes and their
  modifiers.

- `emotional_aperture.py` – emotional aperture (expressiveness / focus /
  overload).

- `rhythm.py` – output rhythm mode (flip, flop, twitch, etc) based on triggers,
  behavior, gait and drift.

- `drift_pressure.py` – drift pressure calculation and corrective actions.

- `framework/JL_Engine_Master.json` – master engine config and core rules.

- `personas/` – persona JSON files, referenced via `personas/Personas.mpf.json`.

## Typical Turn Flow

1. **User input** is provided to `JLEngineCore.process_turn()`.

2. The engine:
   - scores conversational signals from the raw text,
   - reads the current behavior state from the grid,
   - updates the emotional aperture,
   - selects cognitive modes,
   - computes drift pressure and corrective actions,
   - computes the rhythm mode,
   - builds a layered system prompt (core rules + persona + engine state),
   - sends the messages to the configured brain backend.

3. The brain backend returns a reply and metadata; the engine returns:
   - `reply_text` – final string to show to the user,
   - `telemetry` – a dict with persona, behavior, aperture, cognitive mode,
     drift, rhythm, etc.

The GUI (or any other client) should render the reply and use telemetry
to update HUDs or logs.

## Next Steps / Integration Notes

- The Tk GUI in `main_app.py` can be incrementally refactored so that all
  prompt-building logic is removed from the UI and delegated to
  `JLEngineCore`.

- New tools (e.g. serial bridge control, Open Interpreter, VS Code agents) should call
  the engine via the same `process_turn()` API to avoid duplicating logic.
