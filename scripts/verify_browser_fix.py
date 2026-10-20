import os, subprocess, pathlib, json
root = pathlib.Path(__file__).resolve().parents[1]
env = os.environ.copy()
env["JULIA_CONDAPKG_BACKEND"] = "Null"
env["JULIA_PYTHONCALL_EXE"] = "python"
julia = pathlib.Path.home()/".julia/juliaup/julia-1.12.6+0.x64.w64.mingw32/bin/julia.exe"
results = {}
for name, script in [("browser", "test/test_browser_lifecycle.jl"), ("suite", "test/runtests.jl")]:
    with (root/"tmp"/f"{name}-browser-fix.log").open("w",encoding="utf-8") as out:
        result = subprocess.run([str(julia),"--project=.",script],cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=240)
    results[name] = result.returncode
    print(name, "exit", result.returncode, flush=True)
(root/"tmp/browser-fix-results.json").write_text(json.dumps(results))
