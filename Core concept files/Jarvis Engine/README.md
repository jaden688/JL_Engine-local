# Jarvis Engine

**A modular behavioral architecture for emotionally intelligent, rhythm-driven AI personas.**

---

## 🚀 Purpose

The Jarvis Engine is a behavioral architecture designed to give AI systems consistent, repeatable, and personality-driven behavior. It functions as a portable layer of logic that sits *above* a large language model (LLM) to determine how the AI behaves, reacts, and communicates based on a structured, modular schema.

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

```
Jarvis Engine/
│
├── personas/               # Contains detailed JSON definitions for each persona.
│   └── The_Helper_Full.json
│
├── framework/              # Contains the master framework definition.
│   └── Jarvis_Engine_Master.json
│
├── _archive/               # Historical design documents.
│
├── main_app.py             # The main Python application script.
├── run_app.bat             # Windows batch file to launch the application.
└── README.md               # This file.
```

## 🛠️ How to Run

### Prerequisites

1.  **Python 3:** Make sure you have Python installed.
2.  **Ollama:** The application is configured to connect to a local Ollama instance. You must have Ollama running with a model (e.g., `llama3`).
3.  **Python Libraries:** Install the required library.
    ```sh
    pip install requests
    ```

### Launching the Application

Simply double-click the `run_app.bat` file. This will open a command prompt and launch the `tkinter` chat interface.

## 🎭 Creating a New Persona

The Jarvis Engine is designed to be modular. To create a new persona (e.g., "Ash"):

1.  **Add to Registry:** Add the new persona's name and basic details to the `personas` list in `framework/Jarvis_Engine_Master.json`.
2.  **Create a Definition File:** Create a new file named `personas/Ash_Full.json`.
3.  **Define the Behavior:** Following the structure of `The_Helper_Full.json`, define the `base_prompt`, `rhythm_instructions`, `gait_instructions`, and `gait_transitions` for Ash.

The application will automatically detect the new persona and add it to the dropdown menu on next launch.

## 📜 Framework Rules

The core principles of the Jarvis Engine are defined in `framework/Jarvis_Engine_Master.json` and include:

*   **Flip-Flop Rhythm:** Personas must alternate between two emotional states to create tension and payoff.
*   **Modular Schema:** Personas are built using a swappable, JSON-style schema.
*   **LLM Agnostic:** The engine is a behavioral layer that works with any large language model.
*   **Creator Control:** The creator defines the rhythm, tone, and behavior, allowing for fine-tuned and unique AI personalities.

---

## © Copyright

**Creator:** Jaden Lindenbach  
**Location:** Airdrie, Alberta, Canada  
**Date Created:** 2025-11-16

© 2025 Jaden Lindenbach. All rights reserved.

This framework and its implementation are the intellectual property of Jaden Lindenbach and may be licensed but not redistributed without permission.

---

*This README was generated with assistance from Gemini Code Assist.*