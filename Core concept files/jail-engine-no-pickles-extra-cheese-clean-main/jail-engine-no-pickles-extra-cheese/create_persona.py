import json
import os
import sys

def create_persona():
    """
    Interactive CLI to generate a new JL Engine Persona file.
    """
    print("==========================================")
    print("   JL ENGINE - PERSONA GENERATION TOOL    ")
    print("==========================================")
    
    # 1. Basic Metadata
    print("\n[1] IDENTITY")
    display_name = input("   Display Name (e.g., 'The Architect'): ").strip()
    if not display_name:
        print("   ! Error: Name is required.")
        return

    persona_id = display_name.lower().replace(" ", "_")
    print(f"   > ID set to: {persona_id}")
    
    role = input("   Role (e.g., 'System Architect'): ").strip()
    description = input("   Description (Short bio): ").strip()
    
    # 2. Voice & Tone
    print("\n[2] VOICE & TONE")
    voice_desc = input("   Voice Description (e.g., 'Calm, analytical'): ").strip()
    
    # 3. Configuration
    print("\n[3] CONFIGURATION")
    engine_profile = input("   Engine Profile (default: 'STANDARD_MK1'): ").strip() or "STANDARD_MK1"
    
    # Construct the MPF-compliant dictionary
    # Based on Jason_Sketched_Full.json structure
    persona_data = {
        "mpf_version": "1.0.0",
        "engine_profile": engine_profile,
        "id": persona_id,
        "label": display_name,
        "persona_id": persona_id,
        "identity": {
            "name": display_name,
            "role": role,
            "description": description,
            "voice": voice_desc
        },
        "emotional_layer": {
            "enabled": True,
            "signals_used": ["neutral", "curiosity", "focus"],
            "rules": [
                {
                    "condition": "focus == high",
                    "behavior": "deep_analysis"
                }
            ]
        },
        "coding_capabilities": {
            "allowed_tasks": ["analysis", "generation", "refactoring"],
            "response_format": ["structured", "concise"]
        },
        "scope_control": {
            "default_scope": "standard",
            "max_scope_without_confirmation": "session",
            "confirmation_required_for": ["file_deletion", "system_reset"]
        },
        "knowledge": {
            "system_description": "A generated persona for the JL Engine."
        }
    }

    # Save to file
    output_dir = os.path.join(os.path.dirname(__file__), "personas")
    os.makedirs(output_dir, exist_ok=True)
    
    filename = os.path.join(output_dir, f"{persona_id}.json")
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(persona_data, f, indent=2)
        print(f"\n[SUCCESS] Persona saved to: {filename}")
    except Exception as e:
        print(f"\n[ERROR] Could not save file: {e}")

if __name__ == "__main__":
    create_persona()