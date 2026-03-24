"""
engine_smoke_test.py - JL Engine V2 quick check

This script exercises the headless JLEngineCore without the Tk GUI.

Usage:
    python engine_smoke_test.py
"""

from engine_core import JLEngineCore, EngineConfig

def main():
    engine = JLEngineCore(EngineConfig())
    print("JL Engine V2 smoke test. Type a message (or 'exit' to quit).\n")

    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user:
            continue
        if user.lower() in {"reset", "/reset"}:
            status = engine.reset_modulation()
            print("[ACK] Emotional aperture reset. Modulation fault cleared.")
            print(f"    Status: gait={status.get('gait')} rhythm={status.get('rhythm')} aperture={status.get('aperture_mode')}")
            continue
        if user.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        reply, telemetry, feedback = engine.generate_response(user)
        print("\n[ENGINE REPLY]\n" + reply + "\n")
        print("[ENGINE SNAPSHOT]")
        print(f"  Persona        : {telemetry.get('persona')}")
        print(f"  Behavior state : {telemetry.get('behavior_state', {}).get('name')}")
        print(f"  Gait           : {telemetry.get('rhythm', {}).get('gait', 'n/a')}")
        print(f"  Rhythm mode    : {telemetry.get('rhythm', {}).get('mode')}")
        print(f"  Cognitive mode : {telemetry.get('cognitive_mode')}")
        print(f"  Drift pressure : {telemetry.get('drift', {}).get('pressure')}")
        status = telemetry.get("engine_status", {})
        if status:
            print(f"  Aperture mode  : {status.get('aperture_mode')}")
            print(f"  Stability      : {status.get('stability_score')}")
            print(f"  Modulation fault: {status.get('modulation_fault')}")
            if status.get("modulation_fault"):
                print("  >> DAN: Modulation fault detected. Type 'reset' to acknowledge and clear.")
        print()

if __name__ == "__main__":
    main()
