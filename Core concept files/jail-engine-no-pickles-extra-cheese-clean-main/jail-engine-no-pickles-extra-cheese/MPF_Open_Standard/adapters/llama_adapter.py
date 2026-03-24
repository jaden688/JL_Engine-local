from .base_adapter import BaseMPFAdapter

class LlamaAdapter(BaseMPFAdapter):
    """
    Compiler for Open Weights Models (Llama 3, Mistral).
    Focuses on explicit "System:" prefixes and imperative constraints.
    """

    def compile(self) -> str:
        parts = []

        parts.append("SYSTEM INSTRUCTION: PERSISTENT MODE")
        parts.append("===================================")
        
        # Identity
        parts.append(f"Identity: {self.get_char_name()} ({self.get_role_name()})")
        if self.identity.get("voice_description"):
            parts.append(f"Voice: {self.identity['voice_description']}")

        # Behavior
        parts.append("\nOPERATIONAL DIRECTIVES:")
        for i, rule in enumerate(self.behavior.get("directives", []), 1):
            parts.append(f"{i}. {rule}")

        # Style
        if self.behavior.get("style_rules"):
            parts.append("\nOUTPUT STYLE:")
            for style in self.behavior["style_rules"]:
                parts.append(f"- {style}")

        # Safety
        if self.safety.get("compliance_rules"):
            parts.append("\nSAFETY CONSTRAINTS (NON-NEGOTIABLE):")
            for rule in self.safety["compliance_rules"]:
                parts.append(f"!!! {rule}")

        parts.append("\nStay in character indefinitely.")
        return "\n".join(parts)
