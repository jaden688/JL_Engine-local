"""
Utilities for working with MPF llm_profiles.

The MPF agent JSON can optionally include a top-level `llm_profiles` object
that stores one or more boot prompts tuned for specific LLM targets.
"""

from __future__ import annotations

from typing import Any, Dict


def get_llm_boot_prompt(agent_config: Dict[str, Any] | None, target: str = "generic_llm") -> str:
    """
    Resolve the correct boot prompt for an external LLM target.

    The lookup order is:
    1) Use the target-specific profile if present and it has a boot_prompt.
    2) Fallback to the generic_llm profile if present.
    3) Return an empty string if nothing is available.
    """
    if not isinstance(agent_config, dict):
        return ""

    profiles = agent_config.get("llm_profiles")
    if not isinstance(profiles, dict):
        return ""

    if target in profiles and isinstance(profiles[target], dict):
        prompt = profiles[target].get("boot_prompt")
        if isinstance(prompt, str):
            return prompt

    generic = profiles.get("generic_llm")
    if isinstance(generic, dict):
        prompt = generic.get("boot_prompt")
        if isinstance(prompt, str):
            return prompt

    return ""
