from .base_adapter import BaseMPFAdapter

class AnthropicAdapter(BaseMPFAdapter):
    """
    Compiler for Anthropic (Claude 3, 3.5 Sonnet) Models.
    Leverages XML tags for high adherence to complex instructions.
    """

    def compile(self) -> str:
        parts = []

        # 1. Identity
        parts.append(f"You are {self.get_char_name()}.")
        parts.append("<persona_definition>")
        parts.append(f"  <role>{self.get_role_name()}</role>")
        if self.identity.get("voice_description"):
            parts.append(f"  <voice>{self.identity['voice_description']}</voice>")
        if self.identity.get("backstory"):
            parts.append(f"  <backstory>{self.identity['backstory']}</backstory>")
        parts.append("</persona_definition>")

        # 2. Directives (Behavior)
        parts.append("\n<instructions>")
        for rule in self.behavior.get("directives", []):
            parts.append(f"  <rule>{rule}</rule>")
        parts.append("</instructions>")

        # 3. Style
        if self.behavior.get("style_rules"):
            parts.append("\n<style_guide>")
            for style in self.behavior["style_rules"]:
                parts.append(f"  <style>{style}</style>")
            parts.append("</style_guide>")

        # 4. Safety
        if self.safety.get("compliance_rules"):
            parts.append("\n<safety_protocols>")
            for rule in self.safety["compliance_rules"]:
                parts.append(f"  <protocol>{rule}</protocol>")
            parts.append("</safety_protocols>")

        return "\n".join(parts)
