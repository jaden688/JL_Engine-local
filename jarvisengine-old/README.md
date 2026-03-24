# JL Engine

**A modular behavioral architecture for emotionally intelligent, rhythm-driven AI personas.**

---

## 🚀 Purpose

The JL Engine is a behavioral architecture designed to give AI systems consistent, repeatable, and personality-driven behavior. It functions as a portable layer of logic that sits *above* a large language model (LLM) to determine how the AI behaves, reacts, and communicates based on a structured, modular schema.

This is not a loose prompt; it is a structured system for creating dynamic, stateful AI agents.

## 🧠 Core Concepts

The engine is built on a "Hybrid Pattern" that combines two distinct behavioral layers:

1.  **The Gait Engine (Long-Term Mood):** This system manages the persona's overall emotional state (`IDLE`, `WALK`, `TROT`, `GALLOP`). It analyzes user input to shift the persona's general energy and tone over the course of a conversation.

2.  **The Rhythm Engine (Turn-by-Turn Behavior):** This system dictates the specific behavior for the *current* turn using a repeating cycle of `flip` and `flop` states.
    *   **Flip:** A "chaotic" state where the persona is playfully incorrect, uses reverse logic, or creates narrative tension.
    *   **Flop:** A "clear" state where the persona is sincere, direct, and provides the grounded, helpful answer.

These two layers work together to create a persona that is both predictable in its rhythm and responsive to the user's emotional state.

## 📂 Folder Structure

The project is organized to separate application code from persona and framework data.

```sh
Jarvis Engine1.1/
├── framework/
│   ├── behavior_engine.py
│   ├── emotional_aperture.py
│   ├── helper_supervisor.py
│   ├── rhythm_engine.py
│   ├── drift_pressure.py
│   ├── J1_Engine_Master.json
│   └── behavior_states.json
├── personas/
│   └── (persona_files.json)
├── memory/
│   └── memory_store.json
├── main.py                 # The main Python application script.
├── run_app.bat             # Windows batch file to launch the application.
└── README.md               # This file.
```

## 🛠️ How to Run

### Prerequisites

1.  **Python 3:** Make sure you have Python installed.
2.  **Ollama:** The application is configured to connect to a local Ollama instance. You must have Ollama running with a model (e.g., `llama3`).
3.  **Python Libraries:** Install the required library.
    The `run_app.bat` script handles this automatically by using `pip install -r requirements.txt`.

### Launching the Application

Simply double-click the `run_app.bat` file. This will install dependencies, start the Ollama server, and launch the application's chat interface.

## 🎭 Creating a New Persona

The JL Engine is designed to be modular. To create a new persona (e.g., "Ash"):

1.  **Add to Registry:** Add the new persona's name and basic details to the `personas` list in `framework/Jarvis_Engine_Master.json`.
2.  **Create a Definition File:** Create a new `YourPersona_Full.json` file in the `personas/` directory.
3.  **Define the Behavior:** Following the structure of existing personas (like `The_Gremlin_Full.json`), define the `core_identity`, `personality_traits`, `gait_instructions`, and other required fields.

The application will automatically detect the new persona and add it to the dropdown menu on next launch.

## 📜 Core System Rules

The engine operates on a set of non-negotiable rules to ensure stability and integrity:
*   **No False Claims:** The engine must never claim abilities it doesn't have, generate fake system access, or imply self-awareness.
*   **Simulated Identity:** Persona identity is always a simulation, not genuine emotion or consciousness.
*   **Grounded Behavior:** All dynamic behavior (gait, personas) must remain grounded in the model's real abilities.
*   **Supervisory Authority:** The Helper Supervisory Module has final authority on rule enforcement and behavior stabilization.

---

## 📄 License

This project is licensed under a proprietary commercial license. See the [LICENSE](LICENSE) file for details.

---

## © Copyright

**Creator:** Jaden Lindenbach  
**Location:** Airdrie, Alberta, Canada  
**Date Created:** 2025-11-16

© 2025 Jaden Lindenbach. All rights reserved.

This framework and its implementation are the intellectual property of Jaden Lindenbach and may be licensed but not redistributed without permission.

---
"# fuzzink" 
