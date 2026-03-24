from .base_adapter import BaseMPFAdapter

class OpenAIAdapter(BaseMPFAdapter):
    """
    Compiler for OpenAI (GPT-4, GPT-3.5) Models.
    Focuses on clear, concise Markdown bullet points.
    """

    def compile(self) -> str:
        parts = []

        # 1. Identity Block
        parts.append(f"You are {self.get_char_name()}, a {self.get_role_name()}.")
        if self.identity.get("voice_description"):
            parts.append(f"Voice: {self.identity['voice_description']}")
        if self.identity.get("backstory"):
            parts.append(f"\nContext: {self.identity['backstory']}")

        # 2. Behavior/Directives
        parts.append("\n## Instructions")
        for rule in self.behavior.get("directives", []):
            parts.append(f"- {rule}")
        
        # 3. Style Rules
        if self.behavior.get("style_rules"):
            parts.append("\n## Style Guidelines")
            for style in self.behavior["style_rules"]:
                parts.append(f"- {style}")

        # 4. Safety Layer (Critical for Enterprise)
        if self.safety.get("compliance_rules"):
            parts.append("\n## Safety & Compliance")
            for rule in self.safety["compliance_rules"]:
                parts.append(f"- {rule}")
            
        return "\n".join(parts)
