import unittest
import os
import sys

# Ensure parent directory is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from persona_manager import PersonaManager
from engine_core import JLEngineCore, EngineConfig


class TestEfficiencyReboot(unittest.TestCase):
    def setUp(self):
        self.pm = PersonaManager()
        self.mock_persona_data = {
            "name": "TestBot",
            "operational_behavioral_traits": {
                "positive": [
                    "Technical logic and code accuracy",
                    "Precise reasoning",
                    "Creative chaos and mischief",
                    "Friendly conversation"
                ],
                "negative": [
                    "Boring robotic response",
                    "Over-engineering"
                ],
                "boundaries": ["No illegal stuff"]
            }
        }
        self.pm.set_active_persona("TestBot", self.mock_persona_data)

    def test_intent_filtering_technical(self):
        """Ensure technical intent prioritizes technical traits."""
        projection = self.pm.get_projection(intent="Technical Debugging")
        traits = projection["operational_behavioral_traits"]
        
        # Should include technical traits
        self.assertTrue(any("technical" in t.lower() or "precise" in t.lower() for t in traits["positive"]))
        # Total positive traits should be limited (max 4: 3 matches + 1 other)
        self.assertLessEqual(len(traits["positive"]), 4)

    def test_intent_filtering_creative(self):
        """Ensure creative intent prioritizes creative traits."""
        projection = self.pm.get_projection(intent="Creative Storytelling")
        traits = projection["operational_behavioral_traits"]
        
        # Should include creative traits
        self.assertTrue(any("creative" in t.lower() or "chaos" in t.lower() for t in traits["positive"]))
        self.assertLessEqual(len(traits["positive"]), 4)

    def test_binary_loading(self):
        """Ensure the engine can load a binary MPF file."""
        # Using SparkByte as it was re-compiled
        engine = JLEngineCore()
        engine.set_persona("SparkByte")
        self.assertEqual(engine.current_persona_name, "SparkByte")
        # current_persona_data should be a dict loaded from binary
        self.assertIsInstance(engine.current_persona_data, dict)
        
        # Consistent check for name across different schemas
        name = engine.current_persona_data.get("name") or \
               engine.current_persona_data.get("identity", {}).get("name")
        self.assertEqual(name, "SparkByte")



if __name__ == "__main__":
    unittest.main()
