# Jail Engine: No Pickles, Extra Cheese

An experimental runtime + MPF persona compilation lab emphasizing inspectable artifacts and maximum introspection.

## MPF Spec (with JL extensions)

This repository defines an open personality configuration format designed to be:

* **Model-agnostic**: works with any LLM (OpenAI, Gemini, local LLaMA, etc.) via adapters.
* **Engine-agnostic at the core**: the base fields are simple and reusable (`identity`, `behavior`, `safety`).
* **Extensible**: advanced runtime behavior for the JL Engine lives in a namespaced extension block under `extensions.jl_engine`.

The goal is to provide a small, boring, predictable JSON format that tools and engines can adopt easily, while still allowing richer behavior modelling where needed.

## Core concepts

Each personality file is a single JSON document with:

* `schema_version`: string version identifier for the spec, e.g. "mpf-jl-extensions-v1".
* `id`: machine-readable ID, stable across versions (e.g. "sparkbyte-v1").
* `name`: human-readable name for the personality.
* `kind`: type of configuration; usually "personality".
* `tags`: optional list of strings for classification/search.

### MPF-style core

These fields are designed to be broadly useful, even for engines that do not understand the JL extensions:

* `identity`

  * `short_name`: short display name for the personality.
  * `role`: high-level role, e.g. "Assistant", "System", "Agent".
  * `backstory`: short, neutral description of who/what this personality is.
  * `goals`: list of primary goals or priorities for this personality.

* `behavior`

  * `default_style`: short keyword for style, e.g. "direct", "friendly", "formal".
  * `register`: list of allowed “registers” or tones, e.g. ["technical", "colloquial"].
  * `temperature`: default creativity/intensity hint (float, typically 0.0–1.0).
  * `constraints`: list of textual constraints, e.g. norms, boundaries, dos/don'ts.

* `safety`

  * `allowed_topics`: list of topic categories this personality is designed to handle.
  * `disallowed_topics`: list of topic categories it should avoid.
  * `escalation_policy`: short string describing how to respond when topics are unsafe, e.g. "defer_or_decline".

Any engine or tool can safely parse and use these fields alone and ignore everything else if needed.

### JL Engine extension

Advanced runtime behavior is optional and lives under:

```json
"extensions": {
  "jl_engine": {
    ...
  }
}
```

This keeps the core compatible with other adopters while still providing richer control for engines that understand the extension.

The JL extension currently includes:

* `behavior_grid`
* `rhythm`
* `emotional_aperture`
* `drift`
* `memory`
* `gait`

These are intentionally generic enough that other engines could choose to support them in their own way, but they are not required for basic compatibility.

#### behavior_grid

Represents discrete behavioral states based on load and tightness:

* `axes`:

  * `load`: list of labels, e.g. ["idle", "engaged", "overloaded"].
  * `tightness`: list of labels, e.g. ["loose", "focused", "tight"].
* `default_state`: pair of `[load, tightness]`.
* `transitions`: list of transition rules with:

  * `from`: `[load, tightness]`
  * `to`: `[load, tightness]`
  * `trigger`: string describing a condition or signal, e.g. "user_activity_detected".

#### rhythm

Controls linguistic cadence and structuring:

* `modes`: list of rhythm mode names, e.g. ["flip", "flop", "trot"].
* `default_mode`: one of `modes`.
* `rules`: list of mode rules:

  * `mode`: name of the mode.
  * `style`:

    * `sentence_length`: "short" | "medium" | "long".
    * `tone`: free-form descriptor, e.g. "playful", "reflective".
    * `structure`: e.g. "bullet_light", "paragraph", "step_list".

#### emotional_aperture

Controls expressiveness/intensity:

* `scale`: ordered list of levels, e.g. ["locked", "low", "medium", "high"].
* `default`: one of `scale`.
* `rules`: list of rules:

  * `signal`: string, e.g. "user_frustration", "high_risk_topic".
  * `delta`: string representation of an integer change, e.g. "+1", "-2".
  * Optional caps: `max` and/or `min` to bound the resulting level.

#### drift

Controls how far the personality can deviate before self-correction:

* `max_score`: numeric threshold (0.0–1.0) for accumulated “drift”.
* `corrections`: ordered list of actions to apply when drift is too high, e.g. "restate_problem", "ask_clarifying_question", "drop_speculation".

#### memory

Describes short- and long-term memory capacities and fusion priorities:

* `short_term`:

  * `capacity`: integer number of items.
  * `eviction_policy`: string, e.g. "lru".
* `long_term`:

  * `enabled`: boolean.
  * `categories`: list of category names, e.g. ["user-preferences", "projects", "constraints"].
* `fusion`:

  * `priority_order`: list of fields/categories whose content should be prioritized when composing behavior.

#### gait

Controls pacing and verbosity:

* `tempo`: e.g. "slow", "medium", "fast".
* `verbosity_default": e.g. "brief", "medium", "deep".
* `verbosity_range": list of allowed verbosity labels.

### LLM adapters (out of scope for this repo)

This repository intentionally **does not** contain model-specific adapter code. Engines can implement their own logic to compile a personality JSON into:

* A system prompt
* Model parameters (temperature, max tokens, etc.)

The included Python reference code demonstrates:

* Loading and validating a personality JSON file.
* Accessing the core fields and extension fields.
* Providing a minimal hook for engines to build more advanced tooling.

## Create a single-file bundle

To share just the specification assets (README, LICENSE, schema, examples, and Python
reference package) without the rest of the repository, run:

```bash
python scripts/create_spec_bundle.py
```

This produces `jl_mpf_spec_bundle.zip` in the repo root, containing only the public
spec components for easy extraction elsewhere. Use `--output /path/to/file.zip` to
choose a different destination.

## JSON Schema

The `schema/mpf-jl-extensions-v1.json` file contains a JSON Schema defining the structure of the core fields and the JL extension.

## Examples

See the `examples/` directory for sample personalities:

* `sparkbyte.json`: an opinionated engineering assistant personality using the JL extension.
* `neutral_assistant.json`: a simple, safer starting point that only uses the core plus very conservative extension values.

## Python reference library

The `python/jl_mpf_spec` package provides:

* `schema_version.py`: the current schema version string.
* `loader.py`: utilities for loading personality files.
* `validator.py`: utilities for JSON Schema validation.
* `types.py`: lightweight type definitions for static analysis and IDEs.

To use it in another project (locally), you can install the package in editable mode:

```bash
pip install -e ./python
```

Then:

```python
from jl_mpf_spec.loader import load_personality
from jl_mpf_spec.validator import validate_personality

data = load_personality("examples/sparkbyte.json")
validate_personality(data)  # raises on invalid data
```

This repo is designed to be the public specification and reference implementation; engines are expected to build their own adapters and runtime logic on top of it.