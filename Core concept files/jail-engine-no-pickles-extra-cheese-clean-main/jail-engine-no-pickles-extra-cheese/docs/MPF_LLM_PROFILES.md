# MPF LLM Profiles

The Modular Persona Framework now supports a top-level `llm_profiles` section on each persona JSON. This keeps the structured engine layer (gait, rhythm, states, safety, etc.) as the source of truth while also shipping plain-text boot prompts for external LLMs.

## Structure

- `llm_profiles` (object): keys are LLM targets (e.g., `generic_llm`, `microsoft_copilot`, `openai_gpt`).
- Each profile entry is an object with:
  - `description` (string): quick note on the target.
  - `boot_prompt` (string): the plain-text behavior script to prepend as the first/system message for that target.

Example:

```json
{
  "mpf_version": "1.1.0",
  "id": "sparkbyte_core",
  "label": "Spark Byte",
  "llm_profiles": {
    "generic_llm": {
      "description": "Default behavior script for any instruction-tuned LLM.",
      "boot_prompt": "..."
    },
    "microsoft_copilot": {
      "description": "Compressed Spark Byte script for tight Copilot contexts.",
      "boot_prompt": "..."
    }
  }
}
```

## Lookup helper

Use the shared helper to fetch the correct prompt with fallback to `generic_llm`:

```python
from framework.mpf.llm_profiles import get_llm_boot_prompt

prompt = get_llm_boot_prompt(persona_config, target="microsoft_copilot")
```

`JLEngineCore` also exposes `engine.get_llm_boot_prompt(target)` so bridges can reuse the current persona’s boot prompt without re-reading files.

## Engine usage pattern

When sending a request to an external LLM:
1. Pick the persona as usual (engine layer unchanged).
2. Resolve the boot prompt via the helper.
3. Prepend that string as the first/system message, then send the user’s query.
