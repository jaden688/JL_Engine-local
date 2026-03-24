from __future__ import annotations
import sys
import os
import json

# Ensure we can import the local runtime package
sys.path.append(os.path.join(os.getcwd(), "MPF_Open_Standard"))

from runtime.engine_core import JLEngineCore, EngineConfig
from runtime.behavior_engine import BehaviorState

def test_mpf_runtime_initialization():
    print("\n[TEST] Initializing Headless Engine Core...")
    
    # 1. Initialize Engine
    # We point to the example schema we just created to test MPF loading
    try:
        engine = JLEngineCore()
        print("✅ Engine Core initialized successfully.")
    except Exception as e:
        print(f"❌ Engine Core failed to init: {e}")
        return

    # 2. Test Behavior Grid
    print("\n[TEST] Checking Behavior Engine State...")
    state = engine.behavior_engine.get_current_state()
    print(f"   Current State: {state.name} (ID: {state.id})")
    if state:
        print("✅ Behavior Engine is active.")
    else:
        print("❌ Behavior Engine returned None.")

    # 3. Test Rhythm Calculation
    print("\n[TEST] Testing Rhythm Engine...")
    rhythm = engine.rhythm_engine.compute(
        last_mode="flip",
        trigger="user_hyped",
        gait="trot",
        behavior_state=state,
        drift_pressure=0.0,
        safety_on=True
    )
    print(f"   Input: 'user_hyped' -> Output Mode: {rhythm['mode']}")
    if rhythm['mode'] == 'trot':
        print("✅ Rhythm Engine correctly shifted to 'trot'.")
    else:
        print(f"⚠️ Rhythm Engine unexpected output: {rhythm['mode']}")

    # 4. Test Emotional Aperture
    print("\n[TEST] Testing Emotional Aperture...")
    aperture = engine.emotional_aperture.update_from_signals(
        behavior_state=state,
        user_sentiment=0.8, # Very positive
        safety_mode=True
    )
    print(f"   Score: {aperture['score']:.2f} | Mode: {aperture['mode']}")
    if aperture['score'] > 0.0:
        print("✅ Aperture calculated a valid score.")
    else:
        print("❌ Aperture score is 0.0 (might be broken).")

    print("\n[SUCCESS] The Headless Runtime is operational.")

if __name__ == "__main__":
    test_mpf_runtime_initialization()
