import json

class BehaviorState:
    """A simple data class to hold the properties of a single behavioral state."""
    def __init__(self, state_data: dict):
        self.id = state_data.get("id", "0,0")
        self.name = state_data.get("name", "Unknown")
        self.expressiveness = state_data.get("expressiveness", 0.5)
        self.pacing = state_data.get("pacing", "normal")
        self.tone_bias = state_data.get("tone_bias", "neutral")
        self.memory_strictness = state_data.get("memory_strictness", "medium")

    def __str__(self):
        return f"[{self.id}] {self.name}"

    def get_instructions(self) -> str:
        """Generates a string of instructions for the LLM based on the state's metadata."""
        return (
            f"Current Behavior State: {self.name} ({self.id}).\n"
            f"- Expressiveness Level: {self.expressiveness * 100}%\n"
            f"- Conversational Pacing: {self.pacing}\n"
            f"- Dominant Tone: {self.tone_bias}\n"
            f"- Adherence to Memory: {self.memory_strictness}"
        )

class BehaviorStateMachine:
    """
    Manages the 5x4 grid of behavioral states for the JL Engine.
    """
    def __init__(self, config_path: str):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.states = [[BehaviorState(s) for s in row] for row in config["states"]]
            self.trigger_mappings = config["trigger_mappings"]
            self.rows = config["grid_dimensions"]["rows"]
            self.columns = config["grid_dimensions"]["columns"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            print(f"FATAL: Could not load behavior states from {config_path}: {e}")
            self.states = [[BehaviorState({}) for _ in range(4)] for _ in range(5)]
            self.trigger_mappings = {}
            self.rows = 5
            self.columns = 4

        # Default state is Engaged-Disciplined
        self.current_row = 2
        self.current_col = 0

    def get_current_state(self) -> BehaviorState:
        """Returns the current BehaviorState object."""
        return self.states[self.current_row][self.current_col]

    def set_state_by_coords(self, row: int, col: int):
        """Sets the machine to a specific state using grid coordinates."""
        self.current_row = max(0, min(row, self.rows - 1))
        self.current_col = max(0, min(col, self.columns - 1))
        print(f"[Behavior Engine] State set to: {self.get_current_state()}")

    def transition_by_trigger(self, trigger: str | None, gait: str):
        """
        Sets the state based on a user trigger, influenced by the current gait.
        """
        if trigger and trigger in self.trigger_mappings:
            target_row, target_col = self.trigger_mappings[trigger]
            
            # --- Gait Influence Hook ---
            # High-energy gaits can push the state towards higher intensity (rows).
            if gait in ["trot", "gallop"]:
                target_row = min(self.rows - 1, target_row + 1) # Increase intensity by 1
            elif gait == "sprint":
                target_row = min(self.rows - 1, target_row + 2) # Increase intensity by 2
            elif gait == "idle":
                target_row = max(0, target_row - 1) # Decrease intensity by 1

            self.set_state_by_coords(target_row, target_col)
        else:
            # If no trigger, default to a neutral state
            self.set_state_by_coords(2, 1)

    def apply_state_to_memory(self, memory_manager: object):
        """Hook for influencing the memory system."""
        current_state = self.get_current_state()
        strictness = current_state.memory_strictness
        print(f"[Behavior Engine] Memory hook called. Strictness level: '{strictness}'")


class RhythmStateMachine:
    """
    Manages the rhythm state for the JL Engine.
    This provides a more dynamic rhythm than a simple toggle, allowing for variability.
    """
    def __init__(self, rhythm_transitions: dict):
        self.rhythm_map = {
            "user_hyped": "sprint",
            "user_joking": "trot",
            "user_frustrated": "flop",
            "user_anxious": "flop",
            "user_distressed": "flop",
            "user_confused": "flip",
            "user_directive": "flip",
            "neutral": "flop",
        }
        self.current_rhythm = "flop"
        self.rhythm_history = []

    def transition(self, trigger: str | None):
        """Transitions the rhythm based on the user trigger."""
        if trigger in self.rhythm_map:
            self.current_rhythm = self.rhythm_map[trigger]
        else:
            self.current_rhythm = "flop" # Default
        
        # Update history
        self.rhythm_history.append(self.current_rhythm)
        if len(self.rhythm_history) > 5: # Keep a short history
            self.rhythm_history.pop(0)

    def get_current_rhythm(self) -> str:
        return self.current_rhythm

    def get_rhythm_variability(self) -> float:
        """
        Calculates variability based on the diversity of recent rhythms.
        Returns a score from 0.0 (no variability) to 1.0 (high variability).
        """
        if not self.rhythm_history:
            return 0.0
        
        unique_rhythms = len(set(self.rhythm_history))
        total_rhythms = len(self.rhythm_history)
        
        # Scale score: 1 unique = 0.0, 2 unique = 0.5, 3+ unique = 1.0
        if unique_rhythms <= 1:
            return 0.0
        elif unique_rhythms == 2:
            return 0.5
        else:
            return 1.0