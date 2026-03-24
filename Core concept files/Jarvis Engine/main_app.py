import tkinter as tk
from tkinter import scrolledtext
import requests
import json
import os
from collections import deque

# -----------------------------
# CONFIGURATION
# -----------------------------

CONFIG = {
    "model": "llama3",  # Change this if you use a different model name
    "ollama_url": "http://localhost:11434/api/chat",
    "request_timeout": 60,
    "history_length": 10,  # Max number of user/assistant message pairs to keep
    "framework_dir": "framework",
    "personas_dir": "personas",
    "master_file": "Jarvis_Engine_Master.json"
}

# -----------------------------
# JARVIS ENGINE – RHYTHM ENGINE
# -----------------------------

class RhythmEngine:
    """
    Manages the turn-by-turn behavioral rhythm (Flip/Flop states) based on
    pre-defined, cyclical patterns from the Jarvis Engine Framework.
    """
    def __init__(self, pattern_name: str = "STANDARD"):
        self.patterns = {
            "STANDARD": ["flip", "flip", "flop"],
            "WAVE": ["flip", "flip", "flip", "flop", "flop", "flip", "flip", "flop", "flop", "flop"],
            "PULSE": ["flip", "flop", "flip", "flop", "flip", "flop", "flop"],
            "SPIRAL": ["flip", "flip", "flip", "flip", "flop", "flop", "flip", "flip", "flop"]
        }
        self.pattern = self.patterns.get(pattern_name.upper(), self.patterns["STANDARD"])
        self.index = 0

    def set_pattern(self, pattern_name: str):
        """Switches to a new rhythm pattern and resets the index."""
        self.pattern = self.patterns.get(pattern_name.upper(), self.patterns["STANDARD"])
        self.index = 0

    def get_next_state(self) -> str:
        """Gets the next state from the rhythm pattern and advances the cycle."""
        state = self.pattern[self.index]
        self.index = (self.index + 1) % len(self.pattern)
        return state

# -----------------------------
# JARVIS ENGINE – PERSONA LOADER & PROMPT BUILDER
# -----------------------------

class Persona:
    """Loads and holds all behavioral data for a single persona from a JSON file."""
    def __init__(self, file_path: str):
        self.file_path = file_path
        try:            
            with open(file_path, 'r') as f:
                data = json.load(f)
            self.name = data.get("name", "Unknown Persona")
            self.base_prompt = data.get("base_prompt", "")
            self.rhythm_instructions = data.get("rhythm_instructions", {})
            self.gait_instructions = data.get("gait_instructions", {})
            self.gait_transitions = data.get("gait_transitions", {})
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading persona file {file_path}: {e}")
            # Create a safe fallback persona
            self.name = "Error Persona"
            self.base_prompt = "There was an error loading the persona. Please check the JSON files."
            self.rhythm_instructions = {}
            self.gait_instructions = {}
            self.gait_transitions = {}

def build_system_prompt(persona: Persona, gait: str, rhythm: str) -> str:
    """
    Builds the system prompt based on the current behavioral gait (long-term mood)
    and rhythm (turn-specific behavior).
    """
    # Combine the base prompt with the specific instructions for the current gait and rhythm.
    prompt_parts = [
        persona.base_prompt,
        persona.gait_instructions.get(gait, ""),
        persona.rhythm_instructions.get(rhythm, "")
    ]
    return "\n\n".join(filter(None, prompt_parts)) # Filter out empty strings

def detect_trigger(user_text: str) -> str | None:
    """Detects user intent triggers from their message using simple heuristics."""
    text = user_text.lower()
    if any(x in text for x in ["lol", "lmao", "😂", "haha", "that's funny", "you crack me up"]):
        return "user_joking"
    if any(x in text for x in ["this is insane", "holy", "lets go", "let's go", "send it", "hyped", "so sick"]):
        return "user_hyped"
    if any(x in text for x in ["too much", "overwhelmed", "stop joking", "serious now", "focus", "calm down"]):
        return "user_overwhelmed"
    if any(x in text for x in ["be serious", "no jokes", "just answer", "straight answer", "i'm tired"]):
        return "user_serious_or_tired"
    if len(text) > 0:
        return "user_engaged"
    return None

def update_gait(current: str, trigger: str | None, transitions: dict) -> str:
    """Updates the gait based on the current state and a trigger (a simple state machine)."""
    if trigger is None or current not in transitions:
        return current
    return transitions[current].get(trigger, current)

# -----------------------------
# OLLAMA CALL
# -----------------------------

def call_ollama_jarvis(messages):
    """Sends a chat request to the Ollama API."""
    try:
        resp = requests.post(
            CONFIG["ollama_url"],
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "model": CONFIG["model"],
                "messages": messages,
                "stream": False
            }),
            timeout=CONFIG["request_timeout"]
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
    except Exception as e:
        return f"[ERROR talking to model: {e}]"

# -----------------------------
# TKINTER UI + APP LOGIC
# -----------------------------

class JarvisGaitApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis Engine")
        self.chat_log = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=25, width=80)
        self.chat_log.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(padx=10, pady=(0, 10), fill=tk.X)
        self.user_entry = tk.Entry(bottom_frame)
        self.user_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.user_entry.bind("<Return>", self.on_send)

        send_button = tk.Button(bottom_frame, text="Send", command=self.on_send)
        send_button.pack(side=tk.LEFT, padx=(5, 0))

        # --- Engine Controls & Status ---
        status_frame = tk.Frame(root)
        status_frame.pack(padx=10, pady=(0, 10), fill=tk.X)

        self.gait_label = tk.Label(root, text="Current gait: walk")
        self.gait_label.pack(in_=status_frame, side=tk.LEFT)

        self.rhythm_label = tk.Label(root, text="Current rhythm: flip")
        self.rhythm_label.pack(in_=status_frame, side=tk.LEFT, padx=(20, 0))

        # --- Control Menus ---
        control_frame = tk.Frame(root)
        control_frame.pack(padx=10, pady=(0, 10), fill=tk.X)

        # Rhythm pattern selector menu
        self.rhythm_engine = RhythmEngine("STANDARD")
        self.rhythm_var = tk.StringVar(root)
        self.rhythm_var.set("STANDARD") # default value
        rhythm_options = list(self.rhythm_engine.patterns.keys())
        rhythm_menu = tk.OptionMenu(control_frame, self.rhythm_var, *rhythm_options, command=self.on_rhythm_change)
        rhythm_menu.pack(side=tk.RIGHT, padx=(5,0))
        tk.Label(control_frame, text="Rhythm Pattern:").pack(side=tk.RIGHT)

        # Persona selector menu
        self.persona_var = tk.StringVar(root)
        persona_menu = tk.OptionMenu(control_frame, self.persona_var, "", command=self.on_persona_change)
        persona_menu.pack(side=tk.LEFT)
        self.persona_menu = persona_menu

        # --- State Initialization ---
        self.load_persona_registry()
        default_persona_path = os.path.join(CONFIG["personas_dir"], "The_Helper_Full.json")
        self.persona = Persona(default_persona_path) # Load default persona
        self.persona_var.set(self.persona.name)
        self.root.title(f"Jarvis Engine – {self.persona.name}")

        self.history = deque(maxlen=CONFIG["history_length"] * 2) # *2 for user/assistant pairs
        self.current_rhythm = self.rhythm_engine.get_next_state()
        self.current_gait = "walk"

        # Set initial UI state
        self.rhythm_label.config(text=f"Current rhythm: {self.current_rhythm}")
        self.append_chat("SYSTEM", f"Persona '{self.persona.name}' initialized. Type something to begin.\n")

    def load_persona_registry(self):
        """Loads the list of available personas from the registry file."""
        registry_path = os.path.join(CONFIG["framework_dir"], CONFIG["master_file"])
        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)
            # The personas are nested under the 'jarvis_engine' key
            persona_list = registry.get("jarvis_engine", {}).get("personas", [])
            persona_names = [p.get("name") for p in persona_list if p.get("name")]
            menu = self.persona_menu["menu"]
            menu.delete(0, "end")
            for name in persona_names:
                menu.add_command(label=name, command=lambda value=name: self.on_persona_change(value))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.append_chat("SYSTEM", f"ERROR: Could not load persona registry: {e}")

    def append_chat(self, speaker: str, text: str):
        self.chat_log.insert(tk.END, f"{speaker}: {text}\n\n")
        self.chat_log.see(tk.END)

    def on_send(self, event=None):
        user_text = self.user_entry.get().strip()
        if not user_text: return
        self.append_chat("YOU", user_text)
        self.user_entry.delete(0, tk.END)

        # --- Jarvis Engine Logic ---
        # 1. Update long-term mood (Gait) based on user input
        trigger = detect_trigger(user_text)
        old_gait = self.current_gait
        self.current_gait = update_gait(self.current_gait, trigger, self.persona.gait_transitions)
        if self.current_gait != old_gait:
            self.append_chat("SYSTEM", f"Gait changed: {old_gait.upper()} → {self.current_gait.upper()}")
        self.gait_label.config(text=f"Current gait: {self.current_gait}")

        # 2. Get the turn-specific behavior (Rhythm)
        self.current_rhythm = self.rhythm_engine.get_next_state()
        self.rhythm_label.config(text=f"Current rhythm: {self.current_rhythm}")

        # 3. Build the prompt and call the model
        system_msg = {"role": "system", "content": build_system_prompt(self.persona, self.current_gait, self.current_rhythm)}
        messages = [system_msg] + list(self.history) + [{"role": "user", "content": user_text}]
        
        reply = call_ollama_jarvis(messages)
        
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        self.append_chat("JARVIS", reply)

    def on_rhythm_change(self, selected_pattern):
        """Callback for when the user selects a new rhythm pattern."""
        self.rhythm_engine.set_pattern(selected_pattern)
        self.current_rhythm = self.rhythm_engine.get_next_state() # Get first state of new pattern
        self.rhythm_label.config(text=f"Current rhythm: {self.current_rhythm}")
        self.append_chat("SYSTEM", f"Rhythm pattern changed to {selected_pattern.upper()}. Cycle reset.")

    def on_persona_change(self, selected_persona_name):
        """Callback for when the user selects a new persona."""
        self.persona_var.set(selected_persona_name) # Update the variable to show selection
        # NOTE: This assumes a convention where the file is named `PersonaName_Full.json`
        persona_file = os.path.join(CONFIG["personas_dir"], f"{selected_persona_name.replace(' ', '_')}_Full.json")
        self.persona = Persona(persona_file)
        self.root.title(f"Jarvis Engine – {self.persona.name}")
        self.history.clear()
        self.current_gait = "walk" # Reset gait
        self.append_chat("SYSTEM", f"--- Persona switched to '{self.persona.name}'. Conversation history cleared. ---")


def main():
    root = tk.Tk()
    app = JarvisGaitApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()