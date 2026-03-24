# Persona Normalization + Expansion Notes

This engine now uses a format-agnostic normalization layer before any expansion.

## Normalization rules (summary)
- Inputs of any shape are mapped into a single JL schema (identity, communication_style, emotional_posture, behavior, meta).
- Common aliases are supported (name/description/scenario/greeting/voice/tags/directives/boundaries).
- Text is normalized with newline cleanup, whitespace collapse, and deduping of duplicate lines/paragraphs.
- Field discipline:
  - `identity.description` is static description only; second-person scene narration and *stage directions* are removed.
  - `communication_style.personality.voice` is speaking style only; stage directions and narration are stripped.
  - `communication_style.greeting` keeps scene narration and opening dialogue.

## Firewall rules (raw/original/source)
- Raw/original/source fields are quarantined under `meta.raw_source` for debugging only.
- These fields never appear in user-facing persona fields.
- These fields are never included in expansion prompts.
- Quarantined keys include (case-insensitive): `original_*`, `raw_*`, `source_*`, `system_prompt`, `creator_notes`, `post_history_instructions`.

## Expansion rules
- Expansion uses **only** the normalized persona, not raw input.
- Expansion may add to: `example_dialogues`, `style_notes`, `stressors`, `comforts`, `directives`, `boundaries`.
- Expansion never rewrites `identity.description` or `communication_style.greeting` by default.
- Expansion output is deduped and scrubbed for unsafe content (illicit drugs, self-harm, graphic violence).
- Any scrub event adds a warning in `meta.warnings`.

## Append-only expansion rule (update)
- Expansion now fills `emotional_posture.stressors`, `comforts`, and `notes` with append-only merges.
- If expansion output is empty, a local fallback heuristic fills 3–8 stressors/comforts and 2–6 notes.
- Expansion prompt only uses normalized fields; raw/original/source metadata never enters the prompt.
