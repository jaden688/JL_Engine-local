import json
import os
from typing import Dict, Any, Type
from ..adapters.base_adapter import BaseMPFAdapter
from ..adapters.openai_adapter import OpenAIAdapter
from ..adapters.anthropic_adapter import AnthropicAdapter
from ..adapters.llama_adapter import LlamaAdapter

ADAPTER_MAP = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "llama": LlamaAdapter,
    "mistral": LlamaAdapter
}

def load_and_compile(file_path: str, target_model: str) -> str:
    """
    Main entry point:
    1. Loads the MPF JSON.
    2. Validates minimal structure (full schema validation can be added).
    3. Selects the correct adapter.
    4. Returns the compiled system prompt.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"MPF file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Basic Check
    if "mpf_version" not in data:
        raise ValueError("Invalid MPF file: missing 'mpf_version'.")

    adapter_cls = ADAPTER_MAP.get(target_model.lower())
    if not adapter_cls:
        raise ValueError(f"No adapter found for target: {target_model}")

    adapter = adapter_cls(data)
    return adapter.compile()

if __name__ == "__main__":
    # Test run
    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "digital_ronin.mpf.json")
    print("--- OpenAI Output ---")
    print(load_and_compile(example_path, "openai"))
    print("\n--- Anthropic Output ---")
    print(load_and_compile(example_path, "anthropic"))
