import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import card2mpf


class DescriptionDecomposerTests(unittest.TestCase):
    def test_decompose_description_complete(self):
        text = (
            "NAME\n(\"Test\")\n\n"
            "VOICE\n(\"Soft and steady.\")\n\n"
            "PERSONALITY\n(\"Kind, brave, and calm.\")\n\n"
            "SETTING\n(\"A quiet city.\")\n\n"
            "LIKES\n(\"Tea, rain\")\n\n"
            "DISLIKES\n(\"Lies, noise\")"
        )
        sections = card2mpf.decomposeDescription(text)
        self.assertEqual(sections["name"], "Test")
        self.assertEqual(sections["voice"], "Soft and steady.")
        self.assertEqual(sections["personality"], "Kind, brave, and calm.")
        self.assertEqual(sections["setting"], "A quiet city.")
        self.assertEqual(sections["likes"], "Tea, rain")
        self.assertEqual(sections["dislikes"], "Lies, noise")

    def test_decompose_description_partial(self):
        text = "PERSONALITY\nBrave and witty.\n\nBACKSTORY\nGrew up on the coast."
        sections = card2mpf.decomposeDescription(text)
        self.assertEqual(sections["personality"], "Brave and witty.")
        self.assertEqual(sections["backstory"], "Grew up on the coast.")
        self.assertNotIn("setting", sections)

    def test_decompose_description_messy(self):
        text = (
            "  SCENARIO:  \n"
            "(\"A remote outpost.\\n\\nStorms roll in.\")\n\n"
            "  DISLIKES  \n"
            "\"Noise; crowds; delays\""
        )
        sections = card2mpf.decomposeDescription(text)
        self.assertIn("scenario", sections)
        self.assertEqual(sections["scenario"], "A remote outpost.\n\nStorms roll in.")
        self.assertEqual(sections["dislikes"], "Noise; crowds; delays")

    def test_vaggie_golden_description(self):
        mpf_path = ROOT / "personas" / "Vaggie_Fallen_Exorcist_Angel.mpf"
        data = json.loads(mpf_path.read_text(encoding="utf-8"))
        original = data["identity"]["description"]
        sections = card2mpf.decomposeDescription(original)
        mapped = card2mpf.buildJLFieldsFromSections(sections)
        card = {
            "identity": {
                "name": "Vaggie",
                "role": "Persona",
                "description": original,
            },
            "communication_style": {
                "personality": mapped["communication_style"]["personality"],
                "greeting": "",
            },
            "emotional_posture": mapped["emotional_posture"],
            "behavior": mapped["behavior"],
            "meta": {
                "original_description": original,
                "warnings": [],
            },
        }
        normalized = card2mpf.normalizeJLCard(card)
        normalized = card2mpf.normalizeFinal(normalized)
        personality_struct = normalized["communication_style"]["personality"]
        self.assertIsInstance(personality_struct, dict)
        self.assertTrue(normalized["behavior"]["scenario"])
        self.assertTrue(normalized["emotional_posture"]["baseline"])
        shortened = normalized["identity"]["description"]
        self.assertLess(len(shortened), len(original) * 0.2)
        warnings = normalized["meta"]["warnings"]
        self.assertNotIn("Missing personality/communication style.", warnings)
        self.assertNotIn("Missing setting/scenario.", warnings)

    def test_final_polish(self):
        card = {
            "identity": {
                "description": "Species: Test.. Appearance is sharp. Another line.",
            },
            "communication_style": {
                "personality": {
                    "voice": "Low and calm",
                    "temperament": "Protective and loyal",
                    "interaction_style": ["Direct"],
                    "trust_model": "Slow to trust",
                },
                "voice": "Low and calm",
            },
            "emotional_posture": {
                "baseline": "Baseline is guarded.",
                "stressors": [" people threatening Charlie or the hotel.", "Noise;"],
                "comforts": [" Calm.", "Music!"],
            },
            "behavior": {
                "scenario": "Hostile streets, on guard at the hotel.",
            },
        }
        normalized = card2mpf.normalizeFinal(card)
        self.assertNotIn("Species:", normalized["identity"]["description"])
        self.assertNotIn("..", normalized["identity"]["description"])
        for item in normalized["emotional_posture"]["stressors"]:
            self.assertFalse(item.endswith((".", "!", ",", ";", ":")))
        for item in normalized["emotional_posture"]["comforts"]:
            self.assertFalse(item.endswith((".", "!", ",", ";", ":")))

    def test_signal_pipeline_v2_like(self):
        card = {
            "name": "Mina",
            "description": (
                "Mina is a clown girl with bright hair, a colorful costume, and a playful grin. "
                "She speaks in an overly cheerful voice and tries to cheer people up when they look sad."
            ),
            "first_mes": "Hello {{user}} I'm Mina. Let me be the sun that will shine your day.",
            "tags": ["clown", "cheerful", "playful"],
        }
        mpf, _warnings = card2mpf.normalize_card(card)
        personality = mpf["communication_style"]["personality"]
        self.assertTrue(personality.get("voice"))
        self.assertTrue(personality.get("temperament"))
        self.assertTrue(mpf["emotional_posture"]["baseline"])
        self.assertTrue(mpf["behavior"]["directives"])
        self.assertTrue(mpf["behavior"]["boundaries"])

    def test_signal_pipeline_v3_headings(self):
        mpf_path = ROOT / "personas" / "Vaggie_Fallen_Exorcist_Angel.mpf"
        data = json.loads(mpf_path.read_text(encoding="utf-8"))
        description = data["identity"]["description"]
        card = {"name": "Vaggie", "description": description}
        mpf, _warnings = card2mpf.normalize_card(card)
        personality = mpf["communication_style"]["personality"]
        self.assertTrue(personality.get("voice"))
        self.assertTrue(personality.get("temperament"))
        self.assertTrue(mpf["emotional_posture"]["baseline"])
        self.assertTrue(mpf["behavior"]["scenario"])

    def test_signal_pipeline_raw_prompt(self):
        raw_prompt = (
            "Rin is a fox spirit who speaks in a soft, playful tone. "
            "She lives in a mountain shrine and will never harm innocents. "
            "She enjoys tea and quiet nights, and she is protective of visitors."
        )
        card = {"name": "Rin", "description": raw_prompt}
        mpf, _warnings = card2mpf.normalize_card(card)
        personality = mpf["communication_style"]["personality"]
        self.assertTrue(personality.get("voice"))
        self.assertTrue(personality.get("temperament"))
        self.assertTrue(mpf["emotional_posture"]["baseline"])
        self.assertTrue(mpf["behavior"]["directives"])
        self.assertTrue(mpf["behavior"]["boundaries"])


if __name__ == "__main__":
    unittest.main()
