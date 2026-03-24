"""
Modular Persona Framework (MPF) package.

This package currently exposes a lightweight loader used by the app to read
the MPF registry file that maps display names to persona JSON files and
defaults.
"""

from .fullstack import MPFProfile, load_mpf_registry

__all__ = ["MPFProfile", "load_mpf_registry"]
