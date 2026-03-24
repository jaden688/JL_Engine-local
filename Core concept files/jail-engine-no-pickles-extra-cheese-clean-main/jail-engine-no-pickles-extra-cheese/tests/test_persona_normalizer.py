import unittest
from unittest import mock

import card2mpf


class PersonaNormalizerTests(unittest.TestCase):
    def test_dedupe_paragraphs(self):
        raw = {
            "name": "Echo",
            "description": "Line one.\n\nLine two.\n\nLine one.\n\nLine two.",
        }
        normalized = card2mpf.normalizePersonaInput(raw)
        self.assertEqual(normalized["identity"]["description"], "Line one.\n\nLine two.")

    def test_field_discipline_description(self):
        raw = {
            "name": "Nova",
            "description": "You open your eyes in a dark room.\nShe is tall with silver hair.",
        }
        normalized = card2mpf.normalizePersonaInput(raw)
        self.assertNotIn("You open your eyes", normalized["identity"]["description"])
        self.assertIn("silver hair", normalized["identity"]["description"])

    def test_firewall_raw_fields(self):
        raw = {
            "name": "Rook",
            "description": "A calm sentinel.",
            "system_prompt": "Raw system prompt should not leak.",
            "creator_notes": "Raw notes should not leak.",
        }
        normalized = card2mpf.normalizePersonaInput(raw)
        prompt = card2mpf.build_expansion_prompt(normalized)
        self.assertIn("raw_source", normalized["meta"])
        self.assertNotIn("system_prompt", prompt)
        self.assertNotIn("creator_notes", prompt)
        self.assertNotIn("Raw system prompt", normalized["identity"]["description"])
        self.assertFalse(normalized["behavior"]["directives"])

    def test_expansion_scrubber(self):
        raw = {"name": "Vera", "description": "A friendly guide."}

        def backend_fn(_messages):
            return (
                "{"
                "\"communication_style\": {\"style_notes\": [\"Mentions cocaine casually.\"]},"
                "\"emotional_posture\": {\"stressors\": [\"graphic gore\"], \"notes\": [\"Self-harm talk\"]},"
                "\"behavior\": {\"directives\": [\"Avoid self-harm talk.\"]}"
                "}"
            )

        expanded, _changed = card2mpf.expandPersona(raw, backend_fn)
        notes = expanded["communication_style"]["style_notes"]
        stressors = expanded["emotional_posture"]["stressors"]
        directives = expanded["behavior"]["directives"]
        self.assertFalse(any("cocaine" in item.lower() for item in notes))
        self.assertFalse(any("gore" in item.lower() for item in stressors))
        self.assertFalse(any("self-harm" in item.lower() for item in directives))
        self.assertFalse(any("self-harm" in item.lower() for item in expanded["emotional_posture"]["notes"]))

    def test_expand_uses_normalized_input(self):
        raw = {"name": "Rin", "description": "A quiet guardian."}

        with mock.patch("card2mpf.normalizePersonaInput") as normalize_mock:
            normalize_mock.return_value = {
                "identity": {"name": "Rin", "role": "Persona", "description": "A quiet guardian."},
                "communication_style": {"personality": {"voice": "", "temperament": ""}, "greeting": ""},
                "emotional_posture": {"baseline": "", "stressors": [], "comforts": [], "notes": []},
                "behavior": {"scenario": "", "directives": [], "boundaries": []},
                "meta": {"warnings": []},
            }

            def backend_fn(_messages):
                return "{}"

            card2mpf.expandPersona(raw, backend_fn)
            normalize_mock.assert_called_once()

    def test_expansion_merges_emotional_posture(self):
        raw = {"name": "Mina", "description": "A cheerful comfort clown."}

        def backend_fn(_messages):
            return (
                "{"
                "\"emotional_posture\": {"
                "\"stressors\": [\"being ignored\"],"
                "\"comforts\": [\"laughter\"],"
                "\"notes\": [\"Keep tone playful\"]"
                "}"
                "}"
            )

        expanded, _changed = card2mpf.expandPersona(raw, backend_fn)
        emo = expanded["emotional_posture"]
        self.assertGreaterEqual(len(emo["stressors"]), 3)
        self.assertGreaterEqual(len(emo["comforts"]), 3)
        self.assertGreaterEqual(len(emo["notes"]), 2)

    def test_expansion_fallback_when_empty(self):
        raw = {"name": "Mina", "description": "A cheerful comfort clown."}

        def backend_fn(_messages):
            return "{\"emotional_posture\": {\"stressors\": [], \"comforts\": [], \"notes\": []}}"

        expanded, _changed = card2mpf.expandPersona(raw, backend_fn)
        emo = expanded["emotional_posture"]
        self.assertGreaterEqual(len(emo["stressors"]), 3)
        self.assertGreaterEqual(len(emo["comforts"]), 3)
        self.assertGreaterEqual(len(emo["notes"]), 2)

    def test_merge_does_not_overwrite_with_empty(self):
        base = {
            "identity": {"name": "Test", "role": "Persona", "description": "A guide."},
            "communication_style": {"personality": {"voice": "", "temperament": ""}, "greeting": ""},
            "emotional_posture": {"baseline": "", "stressors": ["harsh negativity"], "comforts": ["kindness"], "notes": ["Stay warm"]},
            "behavior": {"scenario": "", "directives": [], "boundaries": []},
            "meta": {"warnings": []},
        }
        merged = card2mpf.mergeExpandedPersona(base, {"emotional_posture": {"stressors": []}}, "Merge + enhance")
        self.assertIn("harsh negativity", merged["emotional_posture"]["stressors"])


if __name__ == "__main__":
    unittest.main()
