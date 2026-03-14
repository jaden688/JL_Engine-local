"""
Modular Agent Framework (MPF) package.

This package currently exposes a lightweight loader used by the app to read
the MPF registry file that maps display names to agent JSON files and
defaults.
"""

from .fullstack import MPFProfile, load_mpf_registry
from .llm_profiles import get_llm_boot_prompt

__all__ = ["MPFProfile", "load_mpf_registry", "get_llm_boot_prompt"]
