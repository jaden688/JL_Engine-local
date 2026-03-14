import json
from typing import Optional

from .logging_setup import get_logger

logger = get_logger(__name__)


class BehaviorState:
    """A simple data class to hold the properties of a single behavioral state."""

    def __init__(self, state_data: dict):
        self.id = state_data.get("id", "0,0")
        self.name = state_data.get("name", "Unknown")
        self.expressiveness = state_data.get("expressiveness", 0.5)
        self.pacing = state_data.get("pacing", "normal")
        self.tone_bias = state_data.get("tone_bias", "neutral")
        self.memory_strictness = state_data.get("memory_strictness", "medium")

    def __str__(self) -> str:
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
        """Initialize the state machine from a JSON config."""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.states = [[BehaviorState(s) for s in row] for row in config["states"]]
            self.trigger_mappings = config["trigger_mappings"]
            self.rows = config["grid_dimensions"]["rows"]
            self.columns = config["grid_dimensions"]["columns"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.exception("Failed to load behavior states from %s: %s", config_path, e)
            self.states = [[BehaviorState({}) for _ in range(4)] for _ in range(5)]
            self.trigger_mappings = {}
            self.rows = 5
            self.columns = 4

        # Default state is Engaged-Disciplined
        self.current_row = 2
        self.current_col = 0
        # Advisory gating + blending
        self._gating_advice = {"level": "allow", "weight": 0.0, "reason": None}
        self._blend_weight = 0.0
        self._last_blend = None

    def get_current_state(self) -> BehaviorState:
        """Returns the current BehaviorState object."""
        return self.states[self.current_row][self.current_col]

    def get_current_blend(self) -> dict | None:
        """Return the last computed blend bundle for telemetry."""
        return self._last_blend

    def set_state_by_coords(self, row: int, col: int) -> None:
        """Sets the machine to a specific state using grid coordinates."""
        self.current_row = max(0, min(row, self.rows - 1))
        self.current_col = max(0, min(col, self.columns - 1))
        logger.info("[Behavior Engine] State set to: %s", self.get_current_state())
        self._compute_blend()

    def set_state_by_label(self, label: Optional[str]) -> bool:
        """
        Sets the machine to the first state matching the given name or id.
        Returns True if a match is found, else False.
        """
        if not label:
            return False
        label_lower = label.lower()
        for r, row in enumerate(self.states):
            for c, state in enumerate(row):
                if state.name.lower() == label_lower or state.id.lower() == label_lower:
                    self.set_state_by_coords(r, c)
                    return True
        logger.warning("[Behavior Engine] No state found matching '%s'.", label)
        return False

    def transition_by_trigger(
        self, trigger: str | None, gait: str, gating_advice: dict | None = None
    ) -> None:
        """
        Sets the state based on a user trigger, influenced by the current gait.
        Gating is advisory: it can bias us toward safer states but not hard-block
        (safety filters elsewhere still hard-block).
        """
        advice = gating_advice or self._gating_advice or {}
        if isinstance(advice, dict):
            # normalize any hard blocks into weak, unless explicitly marked safety
            level = str(advice.get("level", "allow")).lower()
            if level == "block":
                level = "weak_block"
            is_safety = level == "safety_block"
            advice = {
                "level": level,
                "weight": max(0.0, min(1.0, float(advice.get("weight", 0.0) or 0.0))),
                "safety": is_safety,
                "reason": advice.get("reason"),
            }
        else:
            advice = {"level": "allow", "weight": 0.0, "reason": None}

        if advice.get("level") == "weak_block":
            self._gating_advice = advice
        else:
            self._gating_advice = {"level": "allow", "weight": 0.0, "reason": advice.get("reason")}

        if trigger and trigger in self.trigger_mappings:
            target_row, target_col = self.trigger_mappings[trigger]

            # --- Gait Influence Hook ---
            # High-energy gaits can push the state towards higher intensity (rows).
            if gait in ["trot", "gallop"]:
                target_row = min(self.rows - 1, target_row + 1)  # Increase intensity by 1
            elif gait == "sprint":
                target_row = min(self.rows - 1, target_row + 2)  # Increase intensity by 2
            elif gait == "idle":
                target_row = max(0, target_row - 1)  # Decrease intensity by 1

            # Advisory gating pulls intensity back toward the neutral attractor
            if advice.get("level") == "weak_block":
                pull = advice.get("weight", 0.3)
                target_row = int(round(target_row * (1 - pull) + 2 * pull))
            if advice.get("safety"):
                target_row = 1
                target_col = 0

            self.set_state_by_coords(target_row, target_col)
        else:
            # If no trigger, default to a neutral state
            self.set_state_by_coords(2, 1)
        # compute blend after transition (may use gating weight)
        self._blend_weight = advice.get("weight", 0.0)
        self._compute_blend()

    def apply_state_to_memory(self, memory_manager: object):
        """Hook for influencing the memory system."""
        current_state = self.get_current_state()
        strictness = current_state.memory_strictness
        logger.info("[Behavior Engine] Memory hook called. Strictness level: '%s'", strictness)

    # --- internal helpers ---

    def _compute_blend(self) -> None:
        """
        Build a soft blend between the current state and a stabilizer (Engaged-Loose)
        when gating bias is active or blend weight is set.
        """
        primary = self.get_current_state()
        stabilizer = self.states[2][1]  # Engaged-Loose
        weight = max(0.0, min(1.0, self._blend_weight))
        if weight <= 0.05 or primary is stabilizer:
            self._last_blend = {
                "primary": {"id": primary.id, "name": primary.name},
                "secondary": None,
                "weights": (1.0, 0.0),
            }
            return

        # choose a nearby neighbor to mix with the stabilizer for smoother transitions
        secondary = stabilizer
        if self.current_col > 0:
            secondary = self.states[self.current_row][self.current_col - 1]
        self._last_blend = {
            "primary": {"id": primary.id, "name": primary.name},
            "secondary": {"id": secondary.id, "name": secondary.name},
            "weights": (round(1.0 - weight, 2), round(weight, 2)),
        }
