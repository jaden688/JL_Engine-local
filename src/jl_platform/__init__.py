"""
JL Platform package entrypoint.

Exports a thin start_app helper that wires the host-agnostic CoreEngine into
host adapters via the public SDK.
"""

from jl_platform.sdk.client import start_app

__all__ = ["start_app"]
