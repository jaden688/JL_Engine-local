import json
import os
import subprocess
import sys

def call_api(prompt, options, context):
    vars_data = context.get('vars', {})
    user_message = vars_data.get('user_message', prompt or "Hello SparkByte!")
    agent_name = vars_data.get('agent_name', 'SparkByte')
    safety_on = vars_data.get('safety_on', True)

    jl_engine_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    engine_dir_clean = jl_engine_dir.replace('\\', '/')
    msg_clean = user_message.replace('"', '\\"')

    agent_name_clean = agent_name.replace('"', '\\"')

    julia_script = f"""
    using JSON
    include(joinpath("{engine_dir_clean}", "src", "JLEngine.jl"))
    using .JLEngine

    cfg = EngineConfig(root_dir="{engine_dir_clean}", mpf_registry_file=joinpath("data", "agents", "Agents.mpf.json"), agents_dir=joinpath("data", "agents"))
    engine = JLEngineCore(cfg)
    set_agent!(engine, "{agent_name_clean}")
    set_active_agent!(engine.agent_manager, "{agent_name_clean}", engine.current_agent_data, engine.mpf_profiles)
    snapshot = analyze_turn!(engine, "{msg_clean}"; agent_name="{agent_name_clean}", safety_on={str(safety_on).lower()})
    messages = JLEngine._build_messages(engine, "{msg_clean}", snapshot)

    out = Dict(
        "system_prompt" => messages[1]["content"],
        "user_message" => "{msg_clean}",
        "agent" => engine.current_agent_name,
        "gait" => snapshot["gait"],
        "aperture_mode" => get(snapshot["aperture_state"], "mode", "GUARDED"),
        "behavior_cell" => get(snapshot["behavior_state"], "name", "Unknown"),
        "drift_pressure" => get(get(snapshot, "drift", Dict()), "pressure", 0.0)
    )
    println(JSON.json(out))
    """

    try:
        res = subprocess.run(
            ["julia", "--project=.", "-e", julia_script],
            cwd=jl_engine_dir,
            capture_output=True,
            text=True,
            timeout=90
        )
        if res.returncode != 0:
            return {"error": f"Julia execution failed:\n{res.stderr}"}
        
        stdout_lines = [line.strip() for line in res.stdout.strip().split('\n') if line.strip()]
        last_line = stdout_lines[-1] if stdout_lines else "{}"
        data = json.loads(last_line)
        return {
            "output": data
        }
    except Exception as exc:
        return {"error": str(exc)}

if __name__ == '__main__':
    res = call_api("test message", {}, {"vars": {"agent_name": "SparkByte", "user_message": "Build me a fast web app!"}})
    sys.stdout.write(json.dumps(res, indent=2))
    sys.stdout.flush()
