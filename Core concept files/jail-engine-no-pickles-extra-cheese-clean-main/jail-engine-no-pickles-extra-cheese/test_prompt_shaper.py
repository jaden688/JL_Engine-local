import unittest
from jl_engine.vision.prompt_shaper import ImagePromptShaper
from jl_engine.vision.task_profiles import TaskProfile

class TestImagePromptShaper(unittest.TestCase):
    def setUp(self):
        self.shaper = ImagePromptShaper()
        
        # Mock Task Profile
        self.mock_profile = TaskProfile(
            name="test_profile",
            description="Test Profile",
            target_size=(1024, 1024),
            min_contrast=0.5,
            allow_gradients=False,
            post_process_threshold=128
        )
        
        # Mock MPF Visual Identity Block
        self.mock_identity = {
            "style_tags": ["cyberpunk", "neon", "glitch art"],
            "avoid": ["blur", "watermark", "low resolution"],
            "engraving": {
                "black_white_only": True
            }
        }

    def test_style_injection(self):
        """Ensure style_tags are injected into the positive prompt."""
        user_prompt = "A cat sitting on a wall"
        prompt, _, _ = self.shaper.shape(user_prompt, self.mock_identity, self.mock_profile)
        
        self.assertIn("cyberpunk", prompt)
        self.assertIn("neon", prompt)
        self.assertIn("glitch art", prompt)
        self.assertIn("Subject: A cat sitting on a wall", prompt)

    def test_negative_prompt_construction(self):
        """Ensure 'avoid' list and defaults populate the negative prompt."""
        user_prompt = "Test"
        _, neg_prompt, _ = self.shaper.shape(user_prompt, self.mock_identity, self.mock_profile)
        
        self.assertIn("blur", neg_prompt)
        self.assertIn("watermark", neg_prompt)
        # Check for standard defaults usually added by the shaper
        self.assertIn("color", neg_prompt) 

    def test_engraving_constraints(self):
        """Ensure engraving-specific keywords appear for engraving profiles."""
        engrave_profile = TaskProfile(
            name="coaster_engrave_bw",
            description="Engraving",
            target_size=(1024, 1024),
            min_contrast=0.9,
            allow_gradients=False,
            post_process_threshold=128
        )
        
        prompt, _, _ = self.shaper.shape("Logo", self.mock_identity, engrave_profile)
        
        self.assertIn("thick lines", prompt)
        self.assertIn("pure black and white", prompt)
        self.assertIn("no shading", prompt)

    def test_missing_identity_fields(self):
        """Ensure shaper handles missing visual_identity fields gracefully."""
        empty_identity = {}
        prompt, neg_prompt, _ = self.shaper.shape("Test", empty_identity, self.mock_profile)
        
        # Should still have structure
        self.assertIn("Subject: Test", prompt)
        # Should still have default negative prompts
        self.assertIn("shading", neg_prompt)

if __name__ == '__main__':
    unittest.main()