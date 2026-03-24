from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseMPFAdapter(ABC):
    """
    Abstract Base Class for MPF Adapters.
    Responsible for converting a standardized MPF JSON object into
    a model-specific system prompt or message list.
    """

    def __init__(self, mpf_data: Dict[str, Any]):
        self.mpf_data = mpf_data
        self.identity = mpf_data.get("identity", {})
        self.behavior = mpf_data.get("behavior", {})
        self.safety = mpf_data.get("safety_layer", {})

    @abstractmethod
    def compile(self) -> str:
        """
        Transpile the MPF data into the final system prompt string.
        """
        pass

    def get_role_name(self) -> str:
        return self.identity.get("role", "Assistant")

    def get_char_name(self) -> str:
        return self.identity.get("name", "AI")
