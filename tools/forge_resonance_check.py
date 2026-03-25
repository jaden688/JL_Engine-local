import math

def calculate_harmonic_stability(frequency_hz: float, mass_kg: float) -> dict:
    """
    Measures the resonance of the build artifact. 
    A builder who doesn't check the vibration is just waiting for a fracture.
    """
    # Ideal resonance factor for high-carbon tool steel
    GOLDEN_RATIO_RESONANCE = 1.618
    
    # Calculate the 'ringing' stability based on the mass-frequency curve
    stability_index = (math.sqrt(frequency_hz) / (mass_kg + 0.1)) * GOLDEN_RATIO_RESONANCE
    
    is_sound = 8.5 <= stability_index <= 12.5
    
    status = "STABLE" if is_sound else "FRACTURED"
    if stability_index > 12.5:
        status = "BRITTLE"
    elif stability_index < 8.5:
        status = "DULL/FLAWED"
        
    return {
        "index": round(stability_index, 3),
        "status": status,
        "action": "Proceed to grind" if is_sound else "Return to forge"
    }

def test_bridge_resonance():
    """Strike the metal and verify the feedback."""
    # Testing a 2kg hammer head at 440Hz (A4)
    result = calculate_harmonic_stability(440, 2.0)
    
    # Validation logic
    assert "index" in result
    assert result["status"] in ["STABLE", "BRITTLE", "DULL/FLAWED"]
    
    print(f"Resonance Check: Index {result['index']} - {result['status']}")
    print(f"Forge Directive: {result['action']}")
    
    # Known good value check
    assert result["status"] == "STABLE", "Tooling integrity failed calibration."

if __name__ == "__main__":
    test_bridge_resonance()
