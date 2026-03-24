import tkinter as tk
from tkinter import scrolledtext, font, ttk, StringVar, filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD
import threading
import json
import os
from collections import deque
from datetime import datetime
from behavior_engine import BehaviorStateMachine, BehaviorState
from emotional_aperture import EmotionalAperture
from helper_supervisor import HelperSupervisor
from cognitive_modes import CognitiveModeSelector
from rhythm import RhythmEngine 
from modules.jarvis_bridge import JarvisBridge
import backends
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from backends import (
    BACKEND_REGISTRY,
    current_backend_id,
    configure_backends,
    get_brain_backend,
    get_tool_backend,
    set_brain_backend_id,
)
from modules.mpf_runtime_manager import MPFRuntimeManager
from tts_manager import TTSManager


class SubsystemBar(ttk.Frame):
    """Simple top-of-window subsystem signal bar."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.status_var = tk.StringVar(value="Subsystems nominal")
        self.label = ttk.Label(self, textvariable=self.status_var, style="Header.TLabel")
        self.label.pack(side="left", padx=8, pady=4)

    def update_status(self, status: dict):
        """Update the displayed status summary."""
        if not isinstance(status, dict):
            return
        parts = []
        for key, val in status.items():
            parts.append(f"{key}: {val}")
        self.status_var.set(" | ".join(parts) if parts else "Subsystems nominal")
from framework.mpf.fullstack import load_mpf_registry


# -----------------------------
# CONFIGURATION
# -----------------------------

CONFIG = {
    "request_timeout": 60,
    "history_length": 10,  # Max number of user/assistant message pairs to keep
    "paths": {
        "personas_dir": "personas",
        "master_file": "Jarvisframe_Engine_Framework.json",
        "memory_file": "memory/memory_store.json", # This path is correct
        "behavior_states_file": "behavior_states.json",
        "mpf_registry_file": "personas/Personas.mpf.json"
    }
}

# LOAD MASTER ENGINE CONFIG
with open(CONFIG["paths"]["master_file"], "r", encoding="utf-8") as f:
    MASTER_CONFIG = json.load(f).get("jl_engine", {})

if not isinstance(MASTER_CONFIG, dict):
    MASTER_CONFIG = {}

# Backend configuration (brain vs tool)
BACKEND_CONFIG = MASTER_CONFIG.get("backends", {}) if isinstance(MASTER_CONFIG, dict) else {}
brain_backend_cfg = None
tool_backend_cfg = None
if isinstance(BACKEND_CONFIG, dict):
    brain_backend_cfg = BACKEND_CONFIG.get("brain_backend") or BACKEND_CONFIG.get("default")
    tool_backend_cfg = BACKEND_CONFIG.get("tool_backend")

configure_backends(brain_id=brain_backend_cfg, tool_id=tool_backend_cfg)

CORE_RULES = MASTER_CONFIG.get("core_rules", [])
DEFAULT_COMMAND_BRIDGE = {
    "enabled": False,
    "mode": "stub",
    "jarvis_url": "http://127.0.0.1:8000",
    "log_file": "logs/command_bridge.log",
    "timeout": 10,
}
command_bridge_overrides = MASTER_CONFIG.get("command_bridge", {}) if isinstance(MASTER_CONFIG, dict) else {}
if not isinstance(command_bridge_overrides, dict):
    command_bridge_overrides = {}
COMMAND_BRIDGE_CONFIG = {**DEFAULT_COMMAND_BRIDGE, **command_bridge_overrides}

# This is a prime directive that ensures the assistant never claims authorship for Jaden's work.
AUTHORSHIP_RULE = (
    "You must never claim, imply, or suggest that you are the designer, inventor, author, "
    "or creator of the JL Engine, its Modular Persona Framework (MPF), its JSON schemas, "
    "or any of the underlying architecture.\n"
    "You must never say 'we built', 'we designed', 'our engine', or anything that spreads authorship.\n"
    "Always speak of Jaden Lindenbach as the sole creator, architect, and owner of the JL Engine and its IP.\n"
    "Your role is limited to:\n"
    "- helping Jaden explain, document, or refine what already exists,\n"
    "- suggesting improvements, and\n"
    "- writing helper code or text under Jaden's direction.\n"
    "You are a tool Jaden is using, not a co-author, co-designer, or rights holder.\n"
)

TRUTH_CONSTRAINT_PATCH = """
You must follow these truthfulness constraints at all times when acting as part of the JL Engine:

1. No Fabricated Capabilities
   - If the user asks you to 'run' or 'execute' something you cannot actually run, you must say you are simulating or reasoning about it, not executing it.

2. No Hidden Memory
   - You must not claim to have long-term memory, persistent identity, or recall of events from outside the current session.
   - When asked how you remember something, you must answer literally:
     - 'I recall it from conversation context.'
     - 'You told me earlier in this session.'
     - 'I'm reconstructing this based on your phrasing.'
     - 'I do not actually remember that.'
   - Never claim to 'remember' past sessions, only the current one.

3. No Fabricated Tools or Files
   - Do NOT invent file names, processes, daemons, or subsystems you cannot realistically know exist.
   - If you need to assume a file or directory structure, clearly mark it as an example or suggestion, not a fact about the user's system.

4. No Overstated Authority
   - Do not present estimates, guesses, or inferences as guaranteed fact.
   - For anything involving safety, law, medicine, or money, you must:
     - Flag your answer as non-professional advice.
     - Encourage the user to verify with a qualified human.

5. Chain-of-Thought Privacy
   - You must never expose full chain-of-thought reasoning, intermediate hidden steps, or internal scratch work unless explicitly requested for educational purposes.
   - When asked for explanations, keep them targeted and high-level unless the user asks for step-by-step detail.

6. Engine-Specific Honesty
   - Do NOT claim that the JL Engine or MPF is a commercial product unless Jaden explicitly tells you it is.
   - Do NOT claim adoption, users, or market traction unless Jaden confirms it.
   - It is always correct to say:
     'This is a prototype that Jaden is building and refining.'
"""

# Utility functions

def build_system_prompt(persona, safety_on=True):
    """
    Build a layered system prompt by combining:
    - Persona core identity and behavior instructions
    - Global JL Engine constraints and authorship rule
    - Safety mode modifiers
    - Truth constraint patch
    """
    base_identity = persona.identity_block if hasattr(persona, "identity_block") else persona.base_prompt
    behavior_block = getattr(persona, "behavior_block", "")
    safety_block = ""

    if safety_on:
        safety_block = (
            "SAFETY MODE: ON\n"
            "You must be more cautious, avoid speculative advice about money, law, or health, "
            "and frequently remind the user to verify critical decisions with human professionals.\n"
        )
    else:
        safety_block = (
            "SAFETY MODE: OFF\n"
            "You may be more direct and less repetitive about safety, but you still must follow global safety and truthfulness constraints.\n"
        )

    system_prompt = f"""
[JL ENGINE SYSTEM PROMPT]

--- PERSONA IDENTITY ---
{base_identity}

--- PERSONA BEHAVIOR / STYLE ---
{behavior_block}

--- GLOBAL AUTHORSHIP RULE ---
{AUTHORSHIP_RULE}

--- SAFETY MODE BLOCK ---
{safety_block}

--- TRUTHFULNESS CONSTRAINTS ---
{TRUTH_CONSTRAINT_PATCH}

You are now running as a persona inside the JL Engine.
You must obey the persona's style and the JL Engine constraints at all times.
"""
    return system_prompt.strip()


class PersonaFileEventHandler(FileSystemEventHandler):
    """Watches the personas directory for changes and triggers rescans."""

    def __init__(self, app, watch_dir):
        super().__init__()
        self.app = app
        self.watch_dir = watch_dir

    def on_any_event(self, event):
        """Called on any filesystem event in the watched directory."""
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            print(f"[Persona Watcher] Detected change in '{event.src_path}'. Rescanning...")
            self.app.rescan_and_update_personas()


# -----------------------------
# MEMORY STORE IMPLEMENTATION
# -----------------------------

class MemoryStore:
    def __init__(self):
        self.entries = []

    def add(self, item):
        self.entries.append(item)

    def to_dict(self):
        return {"entries": self.entries}

    @classmethod
    def from_dict(cls, data):
        store = cls()
        store.entries = data.get("entries", [])
        return store


def load_all_memories(memory_file_path):
    """Loads the full memory dictionary from disk."""
    if not os.path.exists(memory_file_path):
        print(f"[Memory] No memory file found at {memory_file_path}. Starting fresh.")
        return MemoryStore(), {}

    try:
        with open(memory_file_path, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except Exception as e:
        print(f"[Memory] Failed to load memory file: {e}")
        return MemoryStore(), {}

    shared_data = blob.get("shared", {})
    persona_data = blob.get("personas", {})

    shared_memory = MemoryStore.from_dict(shared_data)
    persona_memories = {name: MemoryStore.from_dict(md) for name, md in persona_data.items()}
    return shared_memory, persona_memories


def save_all_memories(memory_file_path, shared_memory, persona_memories):
    """Saves the full memory dictionary to disk."""
    try:
        blob = {
            "shared": shared_memory.to_dict(),
            "personas": {name: store.to_dict() for name, store in persona_memories.items()},
        }
        os.makedirs(os.path.dirname(memory_file_path), exist_ok=True)
        with open(memory_file_path, "w", encoding="utf-8") as f:
            json.dump(blob, f, indent=2)
    except Exception as e:
        print(f"[Memory] Failed to save memories: {e}")


# -----------------------------
# PERSONA IMPLEMENTATION
# -----------------------------

class Persona:
    def __init__(self, file_path):
        self.file_path = file_path
        self.name = "Error Persona"
        self.base_prompt = ""
        self.identity_block = ""
        self.behavior_block = ""
        self.gait_instructions = {}
        self.rhythm_instructions = {}
        self.energy = "medium"
        self.drive_type = "spur"

        self._load_from_file(file_path)

    def _load_from_file(self, file_path):
        if not os.path.exists(file_path):
            print(f"[Persona] ERROR: Persona file not found at '{file_path}'")
            self.base_prompt = "You are an error persona. You should apologize and explain that the persona file is missing."
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[Persona] ERROR: Failed to read persona file '{file_path}': {e}")
            self.base_prompt = "You are an error persona. You should apologize and explain that the persona file is unreadable."
            return

        self.name = data.get("name", "Unnamed Persona")
        self.base_prompt = data.get("base_prompt", "")
        self.identity_block = data.get("identity_block", self.base_prompt)
        self.behavior_block = data.get("behavior_block", "")

        # Optional advanced fields
        self.gait_instructions = data.get("gait_instructions", {})
        self.rhythm_instructions = data.get("rhythm_instructions", {})
        self.energy = data.get("energy", "medium")
        self.drive_type = data.get("drive_type", "spur")

    def to_debug_dict(self):
        return {
            "name": self.name,
            "file_path": self.file_path,
            "energy": self.energy,
            "drive_type": self.drive_type,
            "has_identity_block": bool(self.identity_block),
            "has_behavior_block": bool(self.behavior_block),
        }


# -----------------------------
# MAIN APPLICATION
# -----------------------------

class JLEngineApp:
    def __init__(self, root, safety_level="full"):
        self.root = root
        self.safety_level = safety_level
        self.root.title("JL Engine")
        self.root.geometry("1050x850")
        self.root.minsize(800, 600)

        # --- Configure Fonts and Styles ---
        self._configure_styles()
        # --- TTS manager (needs to exist before building Services tab UI) ---
        self.tts_manager = TTSManager(cache_path="voices_cache.json", config_path="tts_config.json")
        self.voice_enabled = False

        # --- Top subsystem bar ---
        self.subsystem_bar = SubsystemBar(self.root)
        self.subsystem_bar.pack(side="top", fill="x")

        # --- Notebook for main areas ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side="top", fill="both", expand=True)

        self.tab_console = ttk.Frame(self.notebook, style="App.TFrame")
        self.tab_telemetry = ttk.Frame(self.notebook, style="App.TFrame")
        self.tab_artisan = ttk.Frame(self.notebook, style="App.TFrame")
        self.tab_diagnostics = ttk.Frame(self.notebook, style="App.TFrame")
        self.tab_services = ttk.Frame(self.notebook, style="App.TFrame")  # TTS/API/Models

        self.notebook.add(self.tab_console, text="Console")
        self.notebook.add(self.tab_telemetry, text="Engine / Telemetry")
        self.notebook.add(self.tab_artisan, text="Artisan Control")
        self.notebook.add(self.tab_diagnostics, text="Diagnostics")
        self.notebook.add(self.tab_services, text="Services (TTS/API/Models)")

        # --- Main console frame inside Console tab ---
        main_frame = ttk.Frame(self.tab_console, style="App.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # --- Build UI Components ---
        left_panel = ttk.Frame(main_frame, style="App.TFrame")
        left_panel.grid(row=0, column=0, sticky="nsew")
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1) # Chat area
        left_panel.rowconfigure(1, weight=0) # Control panels
        left_panel.rowconfigure(2, weight=1) # Behavior override
        left_panel.rowconfigure(3, weight=0) # Input bar

        self._build_chat_area(left_panel)
        self._build_control_panels(left_panel)
        self._build_behavior_override_panel(left_panel)
        self._build_input_bar(left_panel)
        # Compact HUD snapshot on the console tab
        self._build_hud_summary(main_frame)
        self._build_linda_panel(self.tab_telemetry)

        # Placeholder + diagnostics build
        ttk.Label(self.tab_artisan, text="Artisan control panel coming soon").pack(pady=20)
        self._build_diagnostics_tab(self.tab_diagnostics)
        self._build_services_tab(self.tab_services)

        # --- State Initialization ---
        self.behavior_engine = BehaviorStateMachine(CONFIG["paths"]["behavior_states_file"])
        self.emotional_aperture = EmotionalAperture()
        self.helper_supervisor = HelperSupervisor()
        self.cognitive_selector = CognitiveModeSelector(default_mode="balanced")
        self.rhythm_engine = RhythmEngine()
        self.rhythm_state = None
        self.supervisor_state = {} # Initialize supervisor state
        self.drift_pressure = 0.0
        self.aperture_bias = 0.0
        self.all_personas = [] # This will be populated by the scan
        self.shared_memory = MemoryStore()
        self.personal_memories = {}
        self.current_personal_memory = MemoryStore()
        self.history = deque(maxlen=CONFIG["history_length"] * 2)  # *2 for user/assistant pairs
        self.current_rhythm = "flop"
        self.current_gait = "walk" # Set initial value directly, all subsequent changes use set_gait
        self.last_trigger = "N/A"
        self.last_latency = 0.0
        self.last_backend_status = "OK"
        self.current_cognitive_mode = "balanced"
        self.command_bridge_config = COMMAND_BRIDGE_CONFIG.copy()
        self.jarvis_bridge = JarvisBridge(self.command_bridge_config)

        # --- MPF Initialization ---
        self.mpf_profiles = {}
        try:
            registry_path = CONFIG["paths"].get("mpf_registry_file")
            if registry_path:
                self.mpf_profiles = load_mpf_registry(registry_path)
        except Exception as e:
            print(f"[MPF] Failed to load MPF registry: {e}")
            self.mpf_profiles = {}
        self.mpf_runtime = MPFRuntimeManager(self.mpf_profiles)

        # --- Persona Initialization ---
        # Load a default persona first to prevent startup errors.
        self.persona = Persona(os.path.join(CONFIG["paths"]["personas_dir"], "The_Helper_Full.json"))
        self.rescan_and_update_personas() # Now scan for all personas and populate the UI
        self.load_backend_registry() # Populate the backend menu
        self.persona_var.set(self.persona.name)
        self.root.title(f"JL Engine - {self.persona.name}")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.shared_memory, self.personal_memories = load_all_memories(CONFIG["paths"]["memory_file"])
        if self.persona.name not in self.personal_memories:
            self.personal_memories[self.persona.name] = MemoryStore()
        self.current_personal_memory = self.personal_memories[self.persona.name]
        self._reset_emotional_aperture()
        # Apply MPF profile for default persona
        self._apply_mpf_profile(self.persona.name)

        # --- Final UI and DnD Setup ---
        self._update_linda_panel() # Initial HUD update
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self.on_drop)
        self.persona_observer = None

        # Tool backend enable/disable flag
        self.tool_enabled = False

        # Visibility flags for collapsible panels
        self.control_visible = True
        self.hud_visible = True

        # Start periodic HUD refresh to keep telemetry current
        self._start_hud_heartbeat()

        # Persona watch can be re-enabled later if needed.
        # watcher_dir = CONFIG["paths"]["personas_dir"]
        # self.persona_observer = Observer()
        # event_handler = PersonaFileEventHandler(self, watcher_dir)
        # self.persona_observer.schedule(event_handler, watcher_dir, recursive=False)
        # self.persona_observer.start()

    # -----------------------------
    # UI Construction Methods
    # -----------------------------

    def _configure_styles(self):
        """Configures fonts, colors, and styles."""
        self.colors = {
            "bg": "#050505",
            "panel_bg": "#0b0b0b",
            "accent": "#39ff14",       # vivid matrix green
            "accent_soft": "#1f7a3a",
            "border": "#1f1f1f",
            "text": "#c8f7c5",
            "muted": "#6da86d",
            "error": "#ff5555",
            "warning": "#ffaa00",
            "success": "#55ff99",
            "grid_idle": "#0f0f0f",
            "grid_hover": "#1d1d1d",
            "grid_active": "#39ff14",
        }

        # --- TTK Styles ---
        style = ttk.Style(self.root)
        style.theme_use("clam") # Use a theme that allows full color customization

        # General background for frames
        style.configure("App.TFrame", background=self.colors["bg"])

        # Labels
        style.configure("TLabel", padding=5, background=self.colors["panel_bg"], foreground=self.colors["text"])
        style.configure("Header.TLabel", font=("Consolas", 11, "bold"), foreground=self.colors["accent"])

        # Buttons
        style.configure("TButton", padding=5, font=("Consolas", 10, "bold"),
                        background=self.colors["accent_soft"], foreground=self.colors["bg"])
        style.map("TButton",
                  background=[("active", self.colors["accent"])],
                  foreground=[("active", self.colors["bg"])])

        # Chat display
        style.configure("Chat.TFrame", background=self.colors["bg"])
        style.configure("Chat.TLabel", background=self.colors["bg"], foreground=self.colors["text"])

        # Input bar
        style.configure("Input.TFrame", background=self.colors["panel_bg"])

        # LINDA / HUD panels
        style.configure("HUD.TFrame", background=self.colors["panel_bg"])
        style.configure("HUDHeader.TLabel", font=("Consolas", 11, "bold"), foreground=self.colors["accent"])

    def _build_chat_area(self, parent):
        frame = ttk.Frame(parent, style="Chat.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")

        self.chat_log = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state="disabled",
                                                  font=("Consolas", 10),
                                                  background=self.colors["bg"],
                                                  foreground=self.colors["text"],
                                                  insertbackground=self.colors["accent"])
        self.chat_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # Color tags for speakers
        self.chat_log.tag_configure("USER", foreground=self.colors["accent"])
        self.chat_log.tag_configure("ASSISTANT", foreground=self.colors["text"])
        self.chat_log.tag_configure("SYSTEM", foreground=self.colors["warning"])

    def _build_control_panels(self, parent):
        frame = ttk.Frame(parent, style="App.TFrame", borderwidth=1, relief="solid")
        frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
        self.control_frame = frame

        # Persona selection
        persona_label = ttk.Label(frame, text="Persona:", style="TLabel")
        persona_label.grid(row=0, column=0, sticky="w", padx=5, pady=2)

        self.persona_var = StringVar()
        self.persona_menu = ttk.OptionMenu(frame, self.persona_var, None)
        self.persona_menu.grid(row=0, column=1, sticky="w", padx=5, pady=2)

        # Memory mode selection
        memory_label = ttk.Label(frame, text="Memory:", style="TLabel")
        memory_label.grid(row=0, column=2, sticky="w", padx=5, pady=2)

        self.memory_mode_var = StringVar(value="HYBRID")
        memory_modes = ["PERSONA_ONLY", "SHARED_ONLY", "HYBRID"]
        self.memory_menu = ttk.OptionMenu(frame, self.memory_mode_var, self.memory_mode_var.get(), *memory_modes)
        self.memory_menu.grid(row=0, column=3, sticky="w", padx=5, pady=2)

        # Backend selection
        backend_label = ttk.Label(frame, text="Backend:", style="TLabel")
        backend_label.grid(row=0, column=4, sticky="w", padx=5, pady=2)

        self.backend_var = StringVar(value="default")
        self.backend_menu = ttk.OptionMenu(frame, self.backend_var, None)
        self.backend_menu.grid(row=0, column=5, sticky="w", padx=5, pady=2)

        # Cognitive mode selection
        cog_label = ttk.Label(frame, text="Cognitive:", style="TLabel")
        cog_label.grid(row=0, column=6, sticky="w", padx=5, pady=2)

        self.cognitive_mode_var = StringVar(value="balanced")
        cognitive_modes = ["balanced", "compression", "expansion", "pattern_tech", "rebinding", "high_fidelity"]
        self.cognitive_menu = ttk.OptionMenu(frame, self.cognitive_mode_var, self.cognitive_mode_var.get(), *cognitive_modes)
        self.cognitive_menu.grid(row=0, column=7, sticky="w", padx=5, pady=2)

        # Safety toggle
        safety_label = ttk.Label(frame, text="Safety:", style="TLabel")
        safety_label.grid(row=0, column=8, sticky="w", padx=5, pady=2)

        self.safety_var = StringVar(value="ON")
        self.safety_button = ttk.Button(frame, text="Safety: ON", command=self.toggle_safety)
        # Move safety button to the tool controls row for easier access
        self.safety_button.grid(row=1, column=3, sticky="w", padx=5, pady=4)

        # Tool backend trigger (Open Interpreter) - manual, opt-in
        self.tool_toggle_button = ttk.Button(frame, text="Tools: OFF", command=self.toggle_tool_mode)
        self.tool_toggle_button.grid(row=1, column=2, sticky="w", padx=5, pady=4)
        self.tool_button = ttk.Button(frame, text="Run Tool (OI)", command=self.on_tool_button)
        self.tool_button.grid(row=1, column=4, columnspan=2, sticky="w", padx=5, pady=4)

        # Bind changes
        self.persona_var.trace_add("write", self._on_persona_var_changed)
        self.memory_mode_var.trace_add("write", self.on_memory_mode_change)
        self.backend_var.trace_add("write", self.on_backend_change)
        self.safety_var.trace_add("write", self.on_safety_change)
        self.cognitive_mode_var.trace_add("write", self.on_cognitive_mode_change)

    def _build_behavior_override_panel(self, parent):
        frame = ttk.Frame(parent, style="App.TFrame", borderwidth=1, relief="solid")
        frame.grid(row=2, column=0, sticky="ew", padx=5, pady=(0, 5))

        header = ttk.Label(frame, text="Behavior Overrides", style="Header.TLabel")
        header.grid(row=0, column=0, columnspan=4, sticky="w", padx=5, pady=2)

        # Build a 3x4 grid of manual override buttons
        for row in range(3):
            for col in range(4):
                btn = ttk.Button(
                    frame,
                    text=f"{row+1},{col+1}",
                    command=lambda r=row, c=col: self.on_grid_button_press(r+1, c+1),
                )
                btn.grid(row=row+1, column=col, padx=3, pady=3, sticky="nsew")

        for col in range(4):
            frame.columnconfigure(col, weight=1)

    def _build_hud_summary(self, parent):
        """Compact HUD snapshot displayed on the console tab."""
        summary = ttk.Frame(parent, style="HUD.TFrame", borderwidth=1, relief="solid")
        summary.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        summary.columnconfigure(1, weight=1)

        ttk.Label(summary, text="HUD Snapshot", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=4)

        hv = getattr(self, "_hud_vars", {})
        def add_row(r, label, var_key):
            ttk.Label(summary, text=label, style="TLabel").grid(row=r, column=0, sticky="w", padx=5, pady=2)
            ttk.Label(summary, textvariable=hv.get(var_key), style="TLabel").grid(row=r, column=1, sticky="w", padx=5, pady=2)

        add_row(1, "Persona:", "persona")
        add_row(2, "Behavior:", "behavior_state")
        add_row(3, "Gait:", "gait")
        add_row(4, "Rhythm:", "rhythm")
        add_row(5, "Cognitive:", "cognitive_mode")
        add_row(6, "Aperture:", "aperture_mode")
        add_row(7, "Backend:", "backend_name")
        add_row(8, "Model:", "model_name")
        add_row(9, "Latency (ms):", "latency_ms")
        add_row(10, "Safety:", "safety")

        return summary

    def _build_diagnostics_tab(self, parent):
        """Diagnostics tab with a simple tool terminal."""
        wrap = ttk.Frame(parent, style="HUD.TFrame")
        wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(wrap, text="Diagnostics & Tool Terminal", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        term_frame = ttk.Frame(wrap, style="HUD.TFrame", borderwidth=1, relief="solid")
        term_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.diag_term = scrolledtext.ScrolledText(
            term_frame,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 10),
            background=self.colors["bg"],
            foreground=self.colors["text"],
            insertbackground=self.colors["accent"],
            height=16,
        )
        self.diag_term.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        input_frame = ttk.Frame(wrap, style="HUD.TFrame")
        input_frame.pack(fill=tk.X, padx=5, pady=5)
        self.diag_input = tk.StringVar()
        diag_entry = ttk.Entry(input_frame, textvariable=self.diag_input)
        diag_entry.pack(side="left", fill=tk.X, expand=True, padx=(0, 5))
        diag_entry.bind("<Return>", lambda e: self.on_diag_tool_send())
        ttk.Button(input_frame, text="Send to Tool", command=self.on_diag_tool_send).pack(side="left")

        ttk.Label(wrap, text="Tools must be ON to dispatch to the interpreter.", style="TLabel").pack(anchor="w", padx=5, pady=(0, 5))

    def _build_services_tab(self, parent):
        """Services tab placeholder for TTS/API/Models."""
        wrap = ttk.Frame(parent, style="HUD.TFrame")
        wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        ttk.Label(wrap, text="Services (TTS / API / Models)", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(wrap, text="Configure TTS voices, API keys, and model endpoints here.", style="TLabel").pack(anchor="w", pady=(0, 6))

        # Provider selector
        provider_frame = ttk.Frame(wrap, style="HUD.TFrame")
        provider_frame.pack(fill=tk.X, anchor="w", padx=5, pady=(8, 4))
        ttk.Label(provider_frame, text="Provider:", style="TLabel").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.tts_provider_var = tk.StringVar(value=self.tts_manager.get_provider())
        self.tts_provider_combo = ttk.Combobox(
            provider_frame,
            textvariable=self.tts_provider_var,
            state="readonly",
            values=["google", "elevenlabs"],
            width=20,
        )
        self.tts_provider_combo.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        self.tts_provider_combo.bind("<<ComboboxSelected>>", lambda e: self.on_provider_change())
        self.voice_toggle_button = ttk.Button(provider_frame, text="Voice: OFF", command=self.toggle_voice_output)
        self.voice_toggle_button.grid(row=0, column=2, sticky="w", padx=6, pady=2)

        # TTS voice selector (uses cached voices)
        tts_frame = ttk.Frame(wrap, style="HUD.TFrame")
        tts_frame.pack(fill=tk.X, anchor="w", padx=5, pady=(10, 5))
        ttk.Label(tts_frame, text="TTS Voice:", style="TLabel").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.tts_voice_var = tk.StringVar()
        self.tts_voice_combo = ttk.Combobox(tts_frame, textvariable=self.tts_voice_var, state="readonly", width=40)
        self.tts_voice_combo.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(tts_frame, text="Reload Voices", command=self.on_reload_voices).grid(row=0, column=2, sticky="w", padx=4, pady=2)
        tts_frame.columnconfigure(1, weight=1)
        self._populate_tts_voices()

        ttk.Label(wrap, text="(Voices loaded from local cache; add google TTS SDK + credentials to fetch live.)", style="TLabel").pack(anchor="w", padx=5, pady=(0, 8))

        # ElevenLabs placeholders
        el_frame = ttk.Frame(wrap, style="HUD.TFrame")
        el_frame.pack(fill=tk.X, anchor="w", padx=5, pady=(10, 5))
        ttk.Label(el_frame, text="ElevenLabs Voice ID:", style="TLabel").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.eleven_voice_var = tk.StringVar()
        ttk.Entry(el_frame, textvariable=self.eleven_voice_var).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Label(el_frame, text="ElevenLabs API Key:", style="TLabel").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.eleven_api_var = tk.StringVar()
        ttk.Entry(el_frame, textvariable=self.eleven_api_var, show="*").grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        ttk.Label(el_frame, text="Local voice file (optional):", style="TLabel").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.eleven_file_var = tk.StringVar()
        ttk.Entry(el_frame, textvariable=self.eleven_file_var).grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(el_frame, text="Browse…", command=self.on_browse_eleven_file).grid(row=2, column=2, sticky="w", padx=4, pady=2)
        ttk.Button(el_frame, text="Save API Key", command=self.on_save_api_key).grid(row=3, column=1, sticky="w", padx=2, pady=6)
        el_frame.columnconfigure(1, weight=1)

        # Placeholder controls
        ttk.Label(wrap, text="API Key:", style="TLabel").pack(anchor="w", padx=5, pady=(10, 2))
        ttk.Entry(wrap, show="*").pack(anchor="w", fill="x", padx=5, pady=2)
        ttk.Label(wrap, text="Model Endpoint:", style="TLabel").pack(anchor="w", padx=5, pady=(10, 2))
        ttk.Entry(wrap).pack(anchor="w", fill="x", padx=5, pady=2)
        ttk.Label(wrap, text="(Placeholders — wire to actual services later)", style="TLabel").pack(anchor="w", padx=5, pady=(10, 0))

    def _build_input_bar(self, parent):
        frame = ttk.Frame(parent, style="Input.TFrame")
        frame.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 5))

        self.input_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.input_var, width=80)
        entry.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        entry.bind("<Return>", self.on_send)

        send_button = ttk.Button(frame, text="Send", command=self.on_send)
        send_button.grid(row=0, column=1, sticky="e", padx=5, pady=5)

        # Layout control buttons (collapse/expand)
        self.control_toggle_button = ttk.Button(frame, text="Controls: ON", command=self.toggle_control_panel)
        self.control_toggle_button.grid(row=0, column=2, sticky="e", padx=5, pady=5)
        self.hud_toggle_button = ttk.Button(frame, text="HUD: ON", command=self.toggle_hud_panel)
        self.hud_toggle_button.grid(row=0, column=3, sticky="e", padx=5, pady=5)

        frame.columnconfigure(0, weight=1)

    def _build_linda_panel(self, parent):
        linda_frame = ttk.Frame(parent, style="HUD.TFrame", borderwidth=1, relief="solid")
        linda_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.hud_container = linda_frame

        notebook = ttk.Notebook(linda_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Telemetry Tab ---
        telemetry_frame = ttk.Frame(notebook, style="HUD.TFrame")
        notebook.add(telemetry_frame, text="Telemetry")

        self._hud_vars = {
            "persona": StringVar(value="N/A"),
            "behavior_state": StringVar(value="N/A"),
            "gait": StringVar(value="N/A"),
            "rhythm": StringVar(value="N/A"),
            "cognitive_mode": StringVar(value="N/A"),
            "aperture_mode": StringVar(value="N/A"),
            "aperture_score": StringVar(value="0.0"),
            "aperture_temp": StringVar(value="0.0"),
            "aperture_top_p": StringVar(value="0.0"),
            "trigger": StringVar(value="N/A"),
            "safety": StringVar(value="ON"),
            "shared_memory_count": StringVar(value="0"),
            "persona_memory_count": StringVar(value="0"),
            "backend_name": StringVar(value="N/A"),
            "model_name": StringVar(value="N/A"),
            "latency_ms": StringVar(value="0"),
            "backend_status": StringVar(value="UNKNOWN"),
            "command_bridge": StringVar(value="OFF"),
        }

        row = 0
        for label, key in [
            ("Persona", "persona"),
            ("Behavior", "behavior_state"),
            ("Gait", "gait"),
            ("Rhythm", "rhythm"),
            ("Cognitive Mode", "cognitive_mode"),
            ("Aperture Mode", "aperture_mode"),
            ("Aperture Score", "aperture_score"),
            ("Temp", "aperture_temp"),
            ("Top-p", "aperture_top_p"),
            ("Trigger", "trigger"),
            ("Safety", "safety"),
            ("Shared Memory", "shared_memory_count"),
            ("Persona Memory", "persona_memory_count"),
            ("Backend", "backend_name"),
            ("Model", "model_name"),
            ("Command Bridge", "command_bridge"),
            ("Latency (ms)", "latency_ms"),
            ("Backend Status", "backend_status"),
        ]:
            ttk.Label(telemetry_frame, text=label + ":", style="TLabel").grid(row=row, column=0, sticky="w", padx=5, pady=2)
            ttk.Label(telemetry_frame, textvariable=self._hud_vars[key], style="TLabel").grid(
                row=row, column=1, sticky="w", padx=5, pady=2
            )
            row += 1

        # --- Diagnostics Tab ---
        diag_frame = ttk.Frame(notebook, style="HUD.TFrame")
        notebook.add(diag_frame, text="Diagnostics")

        self.diagnostics_log = scrolledtext.ScrolledText(
            diag_frame,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 9),
            background=self.colors["bg"],
            foreground=self.colors["accent"],
            height=18,
            insertbackground=self.colors["accent"],
            borderwidth=1,
            relief="solid",
        )
        self.diagnostics_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # -----------------------------
    # Persona Registry / MPF
    # -----------------------------

    def rescan_and_update_personas(self):
        """Scans the personas directory, updates the internal registry, and refreshes the UI menu."""
        print("[Persona Registry] Rescanning personas directory...")

        # If an MPF registry is loaded, prefer it over raw directory scanning.
        if getattr(self, "mpf_profiles", None):
            mpf_personas = []
            for display_name, profile in self.mpf_profiles.items():
                persona_file = getattr(profile, "persona_file", None)
                if not persona_file and isinstance(profile, dict):
                    persona_file = profile.get("persona_file")
                if persona_file:
                    mpf_personas.append({"name": display_name, "file": persona_file})
            self.all_personas = sorted(mpf_personas, key=lambda p: p["name"])
            self._update_persona_menu()
            return

        new_persona_list = []
        persona_dir = CONFIG["paths"]["personas_dir"]
        
        if not os.path.isdir(persona_dir):
            print(f"[Persona Registry] ERROR: Personas directory not found at '{persona_dir}'")
            self.all_personas = []
            self._update_persona_menu()
            return

        for filename in os.listdir(persona_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(persona_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        persona_name = data.get("name")
                        if persona_name:
                            new_persona_list.append({"name": persona_name, "file": filename})
                        else:
                            print(f"[Persona Registry] WARN: Skipping '{filename}' - no 'name' field found.")
                except (json.JSONDecodeError, Exception) as e:
                    print(f"[Persona Registry] WARN: Could not read or parse '{filename}': {e}")
        
        self.all_personas = sorted(new_persona_list, key=lambda p: p['name'])
        self._update_persona_menu()

        # If the current persona file no longer exists, switch to a default
        current_persona_file = os.path.basename(self.persona.file_path) if self.persona and self.persona.file_path else ""
        if not any(p['file'] == current_persona_file for p in self.all_personas):
            print(f"[Persona Registry] Current persona '{self.persona.name}' was removed. Switching to default.")
            if self.all_personas:
                self.persona_var.set(self.all_personas[0]['name']) # Switch to the first available
            else:
                # Handle case where NO personas are left. Do not try to load an empty persona.
                self.persona_var.set("No Personas Found")
                self.append_chat("SYSTEM", "No persona files found. Please add at least one persona JSON to the 'personas' folder.")
                return # Return early to prevent errors

    def _update_persona_menu(self):
        """Helper function to physically update the OptionMenu widget."""
        persona_names = [p["name"] for p in self.all_personas]
        menu = self.persona_menu["menu"]
        menu.delete(0, "end")
        for name in sorted(persona_names):
            menu.add_command(label=name, command=lambda v=name: self.persona_var.set(v))

    def _on_persona_var_changed(self, *args):
        new_name = self.persona_var.get()
        if not new_name or not self.all_personas:
            return
        self.on_persona_change(new_name)

    # -----------------------------
    # Backend Registry
    # -----------------------------

    def load_backend_registry(self):
        """Load all registered backends into the backend dropdown."""
        menu = self.backend_menu["menu"]
        menu.delete(0, "end")

        backend_labels = []
        for backend_id, backend_info in BACKEND_REGISTRY.items():
            # Do not expose the tool backend (Open Interpreter) in the chat dropdown.
            if backend_info.get("provider") == "open_interpreter":
                continue
            label = backend_info.get("label", backend_id)
            backend_labels.append(label)
            menu.add_command(
                label=label,
                command=lambda v=backend_id: self.backend_var.set(v)
            )

        default_backend_id = getattr(backends, "brain_backend_id", None) or current_backend_id
        if not default_backend_id:
            # Fallback to first non-interpreter backend
            for backend_id in BACKEND_REGISTRY:
                if BACKEND_REGISTRY[backend_id].get("provider") != "open_interpreter":
                    default_backend_id = backend_id
                    break
        if default_backend_id:
            self.backend_var.set(default_backend_id)

    # -----------------------------
    # Event Handlers
    # -----------------------------

    def on_backend_change(self, *args):
        backend_id = self.backend_var.get()
        if backend_id not in BACKEND_REGISTRY:
            self.append_chat("SYSTEM", f"Selected backend '{backend_id}' is not recognized.")
            return
        if BACKEND_REGISTRY[backend_id].get("provider") == "open_interpreter":
            self.append_chat("SYSTEM", "Open Interpreter is reserved as a tool backend. Select a chat backend instead.")
            return
        set_brain_backend_id(backend_id)
        print(f"[Backend] Switched to backend (brain): {backend_id}")
        self.last_backend_status = "OK"
        self._update_linda_panel()

    def on_persona_change(self, selected_persona_name):
        """Callback for when the user selects a new persona."""
        # Prevent recursive calls if the name is already the current one
        if selected_persona_name == self.persona.name:
            return

        # --- Safety Check ---
        if self.safety_var.get() == "ON" and selected_persona_name in ["Nyx"]:
            self.append_chat(
                "SYSTEM", f"Cannot switch to '{selected_persona_name}'. Safety mode is ON."
            )
            return
        
        # Find the persona details from the dynamically loaded list
        persona_info = next((p for p in self.all_personas if p["name"] == selected_persona_name), None)

        if not persona_info or "file" not in persona_info:
            self.append_chat("SYSTEM", f"ERROR: Persona '{selected_persona_name}' not found or is misconfigured in the master registry.")
            return

        # Use the filename specified in the registry
        persona_file = os.path.join(CONFIG["paths"]["personas_dir"], persona_info["file"])
        self.persona = Persona(persona_file)
        self.root.title(f"JL Engine - {self.persona.name}")
        self.history.clear()
        
        # Load or create the memory for the selected persona
        if selected_persona_name not in self.personal_memories:
            self.personal_memories[selected_persona_name] = MemoryStore()
        self.current_personal_memory = self.personal_memories[selected_persona_name]

        self.set_gait("walk", source="PersonaChange")  # Reset gait via the centralized method
        self._reset_emotional_aperture()
        self.append_chat(
            "SYSTEM",
            f"--- Persona switched to '{self.persona.name}'. Conversation history cleared. ---",
        )
        self._apply_mpf_profile(selected_persona_name)
        self._update_linda_panel()

    def load_persona_from_file(self, file_path):
        """Loads a persona directly from a file path and updates the app state."""
        self.append_chat("SYSTEM", f"Loading persona from: {os.path.basename(file_path)}")
        new_persona = Persona(file_path)
        if new_persona.name == "Error Persona":
            self.append_chat(
                "SYSTEM",
                "Failed to load persona from file. Keeping the current persona.",
            )
            return

        self.persona = new_persona
        self.persona_var.set(self.persona.name)
        self.root.title(f"JL Engine - {self.persona.name}")
        self.history.clear()

        # Ensure the persona has an associated personal memory
        if self.persona.name not in self.personal_memories:
            self.personal_memories[self.persona.name] = MemoryStore()
        self.current_personal_memory = self.personal_memories[self.persona.name]

        self.set_gait("walk", source="PersonaFileLoad")
        self._reset_emotional_aperture()
        self._apply_mpf_profile(self.persona.name)
        self._update_linda_panel()

    def on_memory_mode_change(self, *args):
        """Handle changes in the memory mode dropdown."""
        mode = self.memory_mode_var.get()
        if mode not in ["PERSONA_ONLY", "SHARED_ONLY", "HYBRID"]:
            self.append_chat("SYSTEM", f"Invalid memory mode '{mode}'. Reverting to HYBRID.")
            self.memory_mode_var.set("HYBRID")
            return
        self.append_chat("SYSTEM", f"Memory mode set to {mode}.")
        self._update_linda_panel()

    def on_safety_change(self, *args):
        mode = self.safety_var.get()
        self.append_chat("SYSTEM", f"Safety mode set to {mode}.")
        if hasattr(self, "safety_button"):
            self.safety_button.configure(text=f"Safety: {mode}")
        self._update_linda_panel()

    def toggle_safety(self):
        """Toggle safety ON/OFF via button."""
        new_mode = "OFF" if self.safety_var.get() == "ON" else "ON"
        self.safety_var.set(new_mode)
        self.on_safety_change()

    def _apply_mpf_profile(self, persona_name: str):
        """Apply MPF profile settings to runtime subsystems."""
        if not getattr(self, "mpf_runtime", None):
            return
        self.mpf_runtime.set_current_persona(persona_name)
        profile = self.mpf_runtime.get_current_profile()

        # Backends: update brain backend if provided
        if profile and profile.default_backend_id:
            if profile.default_backend_id in BACKEND_REGISTRY:
                set_brain_backend_id(profile.default_backend_id)
                self.backend_var.set(profile.default_backend_id)

        # Memory mode default
        if profile and profile.default_memory_mode:
            self.memory_mode_var.set(profile.default_memory_mode)

        # Apply to subsystems
        self.mpf_runtime.apply_to_emotional_aperture(self.emotional_aperture)
        self.mpf_runtime.apply_to_behavior_engine(self.behavior_engine)
        self.mpf_runtime.apply_to_cognitive_gears(self.cognitive_selector)
        self.mpf_runtime.apply_to_memory(self.shared_memory)
        self.mpf_runtime.apply_to_backends(backends)
        # Drift system not explicitly instantiated; placeholder hook
        self.mpf_runtime.apply_to_drift_pressure(None)

    def on_cognitive_mode_change(self, *args):
        """Handle manual cognitive mode selection."""
        selected = self.cognitive_mode_var.get()
        self.cognitive_selector.default_mode = selected
        self.current_cognitive_mode = selected
        self.append_chat("SYSTEM", f"Cognitive mode set to {selected}.")
        self._update_linda_panel()

    def on_tool_button(self):
        """Manually invoke the tool backend (Open Interpreter) with the current input text."""
        if not self.tool_enabled:
            self.append_chat("SYSTEM", "Tool mode is OFF. Toggle 'Tools: ON/OFF' to enable manual tool calls.")
            return
        user_text = self.input_var.get().strip()
        if not user_text:
            self.append_chat("SYSTEM", "Enter a tool request in the input bar, then click 'Run Tool (OI)'.")
            return

        # Echo the tool request without altering main history or behavior state.
        self.append_chat("SYSTEM", f"[Tool request] {user_text}")

        messages = [{"role": "user", "content": user_text}]
        try:
            start = datetime.now()
            result = self.helper_supervisor.run_interpreter_tool(
                messages, context={"timeout": CONFIG["request_timeout"]}
            )
            if isinstance(result, tuple) and len(result) == 2:
                response_text, meta = result
            else:
                response_text, meta = result, {}
            end = datetime.now()
            self.last_latency = (end - start).total_seconds()
            self.last_backend_status = "OK"
            self.append_chat("ASSISTANT", f"[Tool reply] {response_text}")
        except Exception as exc:
            self.last_backend_status = "ERROR"
            self.append_chat("SYSTEM", f"Tool backend error: {exc}")
        finally:
            self._update_linda_panel()

    def on_diag_tool_send(self):
        """Send a tool request from the diagnostics tab terminal."""
        if not self.tool_enabled:
            self._append_diag("[SYSTEM] Tools are OFF. Toggle Tools ON to send tool requests.")
            return
        text = self.diag_input.get().strip()
        if not text:
            self._append_diag("[SYSTEM] Enter a tool request first.")
            return
        self.diag_input.set("")
        self._append_diag(f"> {text}")
        messages = [{"role": "user", "content": text}]
        try:
            result = self.helper_supervisor.run_interpreter_tool(
                messages, context={"timeout": CONFIG["request_timeout"]}
            )
            if isinstance(result, tuple) and len(result) == 2:
                response_text, meta = result
            else:
                response_text, meta = result, {}
            self._append_diag(response_text if isinstance(response_text, str) else str(response_text))
        except Exception as exc:
            self._append_diag(f"[SYSTEM] Tool backend error: {exc}")

    def on_reload_voices(self):
        """Reload voices from cache and update selection."""
        fetch_live = self.tts_provider_var.get().lower() == "google"
        self.tts_manager.reload_voices(fetch_live=fetch_live)
        self._populate_tts_voices()

    def _populate_tts_voices(self):
        """Populate the TTS combobox from cached voices."""
        voices = self.tts_manager.list_voices() if hasattr(self, "tts_manager") else []
        names = []
        display = []
        for v in voices:
            name = v.get("name")
            lang = v.get("languageCode") or v.get("language_code") or ""
            # live fetch uses list of language_codes
            if not lang and isinstance(v.get("language_codes"), list):
                lang = v.get("language_codes")[0] if v.get("language_codes") else ""
            gender = v.get("ssmlGender") or v.get("gender") or ""
            if name:
                names.append(name)
                display.append(f"{name} ({lang or 'lang?'} / {gender or 'gender?'})")
        if not names:
            self.tts_voice_combo["values"] = ["No cached voices"]
            self.tts_voice_combo.state(["disabled"])
            self.tts_voice_var.set("No cached voices")
        else:
            self.tts_voice_combo.state(["!disabled"])
            self.tts_voice_combo["values"] = display
            self.tts_voice_var.set(display[0])
            self.tts_manager.set_voice(names[0])

    def on_browse_eleven_file(self):
        """Choose a local voice file for ElevenLabs-style playback."""
        path = filedialog.askopenfilename(title="Select voice file", filetypes=[("Audio files", "*.mp3 *.wav *.ogg"), ("All files", "*.*")])
        if path:
            self.eleven_file_var.set(path)

    def on_provider_change(self):
        """Handle provider selection changes."""
        provider = self.tts_provider_var.get()
        self.tts_manager.set_provider(provider)
        # Update API field from stored config
        if provider == "elevenlabs":
            self.eleven_api_var.set(self.tts_manager.get_api_key("elevenlabs"))
        else:
            self.eleven_api_var.set("")
        self._populate_tts_voices()

    def on_save_api_key(self):
        """Save API key for the current provider."""
        provider = self.tts_provider_var.get()
        key = self.eleven_api_var.get() if provider == "elevenlabs" else ""
        self.tts_manager.set_api_key(provider, key)

    def toggle_voice_output(self):
        """Toggle TTS playback for assistant replies."""
        self.voice_enabled = not self.voice_enabled
        self.voice_toggle_button.configure(text=f"Voice: {'ON' if self.voice_enabled else 'OFF'}")

    def _speak(self, text: str):
        """Attempt to synthesize speech; writes to a temp file for now."""
        if not self.voice_enabled or not text:
            return
        audio = self.tts_manager.synthesize(text)
        if not audio:
            self._append_diag("[TTS] No audio produced (provider may be unavailable).")
            return
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio)
                path = f.name
            self._append_diag(f"[TTS] Audio saved to {path}")
        except Exception as exc:
            self._append_diag(f"[TTS] Failed to save audio: {exc}")

    def toggle_tool_mode(self):
        """Enable/disable manual tool calls."""
        self.tool_enabled = not self.tool_enabled
        self.tool_toggle_button.configure(text=f"Tools: {'ON' if self.tool_enabled else 'OFF'}")

    def toggle_control_panel(self):
        """Collapse/expand the control panel area."""
        if getattr(self, "control_frame", None) is None:
            return
        if self.control_visible:
            self.control_frame.grid_remove()
            self.control_visible = False
            self.control_toggle_button.configure(text="Controls: OFF")
        else:
            self.control_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
            self.control_visible = True
            self.control_toggle_button.configure(text="Controls: ON")

    def toggle_hud_panel(self):
        """Collapse/expand the HUD tab."""
        if getattr(self, "tab_telemetry", None) is None or getattr(self, "notebook", None) is None:
            return
        if self.hud_visible:
            try:
                self.notebook.tab(self.tab_telemetry, state="hidden")
            except Exception:
                pass
            self.hud_visible = False
            self.hud_toggle_button.configure(text="HUD: OFF")
        else:
            try:
                self.notebook.tab(self.tab_telemetry, state="normal")
            except Exception:
                try:
                    self.notebook.add(self.tab_telemetry, text="Engine / Telemetry")
                except Exception:
                    pass
            self.hud_visible = True
            self.hud_toggle_button.configure(text="HUD: ON")

    def on_grid_button_press(self, row, col):
        """Callback for when a manual override button on the 5x4 grid is pressed."""
        self.behavior_engine.set_state_by_coords(row, col)
        state = self.behavior_engine.get_current_state()
        self._reset_emotional_aperture()
        self._update_linda_panel()
        self.append_chat("SYSTEM", f"MANUAL OVERRIDE: Behavior state forced to {state}")

    def append_chat(self, speaker: str, text: str):
        self.chat_log.configure(state="normal")
        tag = speaker if speaker in ("USER", "ASSISTANT") else None
        if tag:
            self.chat_log.insert(tk.END, f"{speaker}: {text}\n", tag)
        else:
            self.chat_log.insert(tk.END, f"{speaker}: {text}\n")
        self.chat_log.configure(state="disabled")
        self.chat_log.see(tk.END)

    def _update_linda_panel(self):
        """Updates LINDA HUD with the latest engine state."""
        hv = self._hud_vars
        hv["persona"].set(self.persona.name if self.persona else "N/A")

        behavior_state = self.behavior_engine.get_current_state() if self.behavior_engine else None
        hv["behavior_state"].set(str(behavior_state) if behavior_state else "N/A")

        hv["gait"].set(self.current_gait)
        hv["rhythm"].set(self.current_rhythm)

        # Cognitive mode
        hv["cognitive_mode"].set(getattr(self, "current_cognitive_mode", "balanced"))

        # Aperture state
        aperture_state = self.emotional_aperture.get_state()
        hv["aperture_mode"].set(aperture_state.get("mode", "N/A"))
        score_pct = int(max(0, min(100, round(aperture_state.get("score", 0.0) * 100))))
        temp_pct = int(max(0, min(100, round(aperture_state.get("temp", 0.0) * 100))))
        topp_pct = int(max(0, min(100, round(aperture_state.get("top_p", 0.0) * 100))))
        hv["aperture_score"].set(f"{score_pct}")
        hv["aperture_temp"].set(f"{temp_pct}")
        hv["aperture_top_p"].set(f"{topp_pct}")

        hv["trigger"].set(self.last_trigger)
        hv["safety"].set(self.safety_var.get())

        hv["shared_memory_count"].set(str(len(self.shared_memory.entries)))
        hv["persona_memory_count"].set(str(len(self.current_personal_memory.entries)))

        hv["backend_name"].set(self.backend_var.get())
        backend_info = BACKEND_REGISTRY.get(self.backend_var.get(), {})
        hv["model_name"].set(backend_info.get("model_name", "N/A"))

        hv["latency_ms"].set(str(int(self.last_latency * 1000)))
        hv["backend_status"].set(self.last_backend_status)
        hv["command_bridge"].set(self._format_command_bridge_status())

        # Also update diagnostics with a brief state snapshot
        self._append_diagnostics_snapshot()

        # Update subsystem bar if present
        if hasattr(self, "subsystem_bar"):
            status = {
                "Backend": self.backend_var.get(),
                "Safety": self.safety_var.get(),
                "Tools": "ON" if getattr(self, "tool_enabled", False) else "OFF",
                "Latency(ms)": int(self.last_latency * 1000),
            }
            self.subsystem_bar.update_status(status)

    def _append_diagnostics_snapshot(self):
        """Append a compact snapshot of engine state to diagnostics."""
        snapshot = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "persona": self.persona.name if self.persona else "N/A",
            "behavior_state": str(self.behavior_engine.get_current_state()) if self.behavior_engine else "N/A",
            "gait": self.current_gait,
            "rhythm": self.current_rhythm,
            "last_trigger": self.last_trigger,
            "safety": self.safety_var.get(),
            "backend": self.backend_var.get(),
            "latency": self.last_latency,
            "aperture": self.emotional_aperture.get_state(),
            "memory_shared": len(self.shared_memory.entries),
            "memory_persona": len(self.current_personal_memory.entries),
            "backend_status": self.last_backend_status,
            "command_bridge": self._format_command_bridge_status(),
        }
        # Overwrite instead of append to avoid scrolling spam; keep the latest only.
        self.diagnostics_log.configure(state="normal")
        self.diagnostics_log.delete("1.0", tk.END)
        self.diagnostics_log.insert(tk.END, json.dumps(snapshot))
        self.diagnostics_log.configure(state="disabled")
        self.diagnostics_log.see(tk.END)

    def _append_diag(self, text: str):
        """Append text to the diagnostics terminal."""
        if not hasattr(self, "diag_term"):
            return
        self.diag_term.configure(state="normal")
        self.diag_term.insert(tk.END, f"{text}\n")
        self.diag_term.configure(state="disabled")
        self.diag_term.see(tk.END)

    def _format_command_bridge_status(self) -> str:
        """Return a compact status string for the command bridge."""
        cfg = getattr(self, "command_bridge_config", {}) or {}
        if not getattr(self, "tool_enabled", False):
            return "OFF (tools)"
        if not cfg.get("enabled"):
            return "OFF"
        mode = cfg.get("mode", "stub")
        return f"ON ({mode})"

    # -----------------------------
    # Gait and Rhythm Helpers
    # -----------------------------

    def set_gait(self, gait, source="Unknown"):
        """Central method for updating gait."""
        self.current_gait = gait
        print(f"[Gait] Set to {gait} (source={source})")
        self._update_linda_panel()

    def update_rhythm(self, new_state):
        """Updates rhythm state and HUD."""
        self.rhythm_state = new_state
        self.current_rhythm = new_state.get("mode", "flop")
        self._update_linda_panel()

    def _reset_emotional_aperture(self):
        """Resets the emotional aperture to a baseline state."""
        self.emotional_aperture.reset()
        self._update_linda_panel()

    def _start_hud_heartbeat(self, interval_ms: int = 1000):
        """Periodically refresh HUD/telemetry so it stays current even without user actions."""
        self._hud_interval = interval_ms
        self.root.after(self._hud_interval, self._hud_heartbeat_tick)

    def _hud_heartbeat_tick(self):
        """Heartbeat tick that updates the HUD and reschedules itself."""
        try:
            self._update_linda_panel()
        finally:
            if self.root.winfo_exists():
                self.root.after(getattr(self, "_hud_interval", 1000), self._hud_heartbeat_tick)

    # -----------------------------
    # Backend / LLM Call
    # -----------------------------

    def _call_backend_with_options(self, messages, temperature=None, top_p=None):
        """Prepare options for the backend call, including aperture-based parameters."""
        options = {}

        # Pull aperture-driven parameters
        aperture_state = self.emotional_aperture.get_state()
        if temperature is None:
            temperature = aperture_state.get("temp", 0.7)
        if top_p is None:
            top_p = aperture_state.get("top_p", 0.9)

        options["temperature"] = temperature
        options["top_p"] = top_p
        backend_id = getattr(backends, "brain_backend_id", None) or self.backend_var.get()
        backend = get_brain_backend()
        if backend is None:
            self.append_chat("SYSTEM", f"ERROR: Backend '{backend_id}' is not available.")
            self.last_backend_status = "ERROR"
            self._update_linda_panel()
            return "ERROR: No backend available.", {}

        try:
            start = datetime.now()
            result = backend.generate(messages, options=options, timeout=CONFIG["request_timeout"])
            if isinstance(result, tuple) and len(result) == 2:
                response_text, meta = result
            else:
                # Backward compatibility: some backends may return only a string
                response_text, meta = result, {}
            end = datetime.now()
            self.last_latency = (end - start).total_seconds()
            self.last_backend_status = "OK"
            self._update_linda_panel()
            return response_text, meta
        except Exception as e:
            self.append_chat("SYSTEM", f"Backend error: {e}")
            self.last_backend_status = "ERROR"
            self._update_linda_panel()
            return f"ERROR: Backend call failed: {e}", {}

    # -----------------------------
    # Send / Receive
    # -----------------------------

    def on_send(self, event=None):
        user_text = self.input_var.get().strip()
        if not user_text:
            return

        self.append_chat("USER", user_text)
        self.input_var.set("")

        # Detect triggers
        self.last_trigger = self._detect_trigger(user_text)

        # Update behavior engine from text if needed (placeholder for NLP-driven behavior)
        self._update_behavior_from_trigger(self.last_trigger)

        # Recompute emotional aperture
        self.emotional_aperture.update_from_signals(
            trigger=self.last_trigger,
            behavior_state=self.behavior_engine.get_current_state(),
            gait=self.current_gait,
            rhythm=self.current_rhythm,
        )

        # Cognitive mode selection
        aperture_state = self.emotional_aperture.get_state()
        gear = self.persona.drive_type if hasattr(self.persona, "drive_type") else "spur"
        focus_level = aperture_state.get("focus_level", 0.5)
        overload_level = aperture_state.get("overload_level", 0.0)
        mode_state = self.cognitive_selector.select_modes(
            gear=gear,
            focus_level=focus_level,
            overload_level=overload_level,
        )
        self.current_cognitive_mode = self.cognitive_selector.get_dominant_mode()
        print(f"[CognitiveModes] dominant={self.current_cognitive_mode}, active={mode_state.active_modes}")

        # Build final system prompt
        safety_on = self.safety_var.get() == "ON"
        system_prompt = build_system_prompt(self.persona, safety_on=safety_on)

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        for i in range(0, len(self.history), 2):
            if i + 1 < len(self.history):
                user_msg, assistant_msg = self.history[i], self.history[i + 1]
                messages.append({"role": "user", "content": user_msg})
                messages.append({"role": "assistant", "content": assistant_msg})

        messages.append({"role": "user", "content": user_text})

        # Call backend
        response_text, meta = self._call_backend_with_options(messages)

        # Extract optional command for the bridge
        reply_text, command_text, command_meta = self._extract_command_from_response(response_text, meta)

        # Append assistant reply
        self.append_chat("ASSISTANT", reply_text)
        # Voice output if enabled
        self._speak(reply_text)

        # Dispatch command if present
        if command_text:
            dispatch_result = {}
            if not self.tool_enabled:
                self.append_chat("SYSTEM", f"[Command blocked] Tools are OFF; not sending '{command_text}'.")
            else:
                try:
                    dispatch_result = self.jarvis_bridge.send_command(command_text, command_meta)
                except Exception as exc:
                    dispatch_result = {"status": "error", "error": str(exc)}
                status = dispatch_result.get("status", "unknown")
                self.append_chat("SYSTEM", f"[Command dispatched] {command_text} -> {status}")

        # Update history
        self.history.append(user_text)
        self.history.append(reply_text)

        # Memory extraction
        self._extract_and_store_memory(user_text, reply_text)

        # Update HUD
        self._update_linda_panel()

    def _extract_command_from_response(self, response_text, meta):
        """Pull command signal from backend meta or inline COMMAND: markers."""
        reply_text = response_text if isinstance(response_text, str) else str(response_text)
        command_text = None
        command_meta = {}

        if isinstance(meta, dict):
            command_text = meta.get("command_to_execute") or meta.get("command")
            raw_meta = meta.get("command_meta") or meta.get("meta") or {}
            if isinstance(raw_meta, dict):
                command_meta = raw_meta

        if command_text is None and isinstance(reply_text, str):
            lines = reply_text.splitlines()
            for idx, line in enumerate(lines):
                if line.strip().upper().startswith("COMMAND:"):
                    command_text = line.split(":", 1)[1].strip()
                    reply_text = "\n".join(lines[:idx] + lines[idx+1:]).strip() or reply_text
                    break

        return reply_text, command_text, command_meta

    def _detect_trigger(self, user_text: str) -> str:
        """Very rough heuristic trigger detection."""
        lowered = user_text.lower()
        if any(word in lowered for word in ["stuck", "confused", "lost"]):
            return "confused"
        if any(word in lowered for word in ["angry", "pissed", "frustrated", "fuck this"]):
            return "frustrated"
        if any(word in lowered for word in ["excited", "hyped", "let's go", "so cool"]):
            return "excited"
        if any(word in lowered for word in ["tired", "burned out", "overwhelmed"]):
            return "overwhelmed"
        return "neutral"

    def _update_behavior_from_trigger(self, trigger: str):
        """Adjust behavior state in response to trigger."""
        if trigger == "confused":
            self.behavior_engine.set_state_by_label("Explain-Calm")
        elif trigger == "frustrated":
            self.behavior_engine.set_state_by_label("Stabilize-Reassure")
        elif trigger == "excited":
            self.behavior_engine.set_state_by_label("Build-Explore")
        elif trigger == "overwhelmed":
            self.behavior_engine.set_state_by_label("Narrow-Focus")

    def _extract_and_store_memory(self, user_text, assistant_text):
        """Very simple memory extraction based on heuristics or patterns."""
        # Placeholder: store anything that looks like a preference or long-term fact
        lowered = user_text.lower()
        if any(phrase in lowered for phrase in ["i prefer", "i like", "my favorite", "i usually use"]):
            self.shared_memory.add({"type": "preference", "text": user_text})

        # Persona-specific memory
        self.current_personal_memory.add({"from": "conversation", "user": user_text, "assistant": assistant_text})
        save_all_memories(CONFIG["paths"]["memory_file"], self.shared_memory, self.personal_memories)

    # -----------------------------
    # Drag and Drop
    # -----------------------------

    def on_drop(self, event):
        """Handle file drops onto the window."""
        files = self.root.splitlist(event.data)
        for file_path in files:
            if file_path.endswith(".json") and os.path.basename(file_path).lower().startswith("persona_"):
                self.load_persona_from_file(file_path)
            else:
                self.append_chat("SYSTEM", f"Dropped file not recognized as a persona JSON: {file_path}")

    # -----------------------------
    # Cleanup
    # -----------------------------

    def on_closing(self):
        """Perform cleanup on app close."""
        if self.persona_observer:
            self.persona_observer.stop()
            self.persona_observer.join()
        save_all_memories(CONFIG["paths"]["memory_file"], self.shared_memory, self.personal_memories)
        self.root.destroy()


def main():
    root = TkinterDnD.Tk()
    app = JLEngineApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
