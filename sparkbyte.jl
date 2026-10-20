ENV["JULIA_CONDAPKG_BACKEND"] = "Null"
ENV["JULIA_PYTHONCALL_EXE"] = "python"

# ── Early .env loading ─────────────────────────────────────────────────────────
let env_path = joinpath(@__DIR__, ".env")
    if isfile(env_path)
        for raw_line in eachline(env_path)
            line = strip(raw_line)
            (isempty(line) || startswith(line, "#")) && continue
            m = match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            m !== nothing && (ENV[m[1]] = strip(m[2], ['"', '\'']))
        end
    end
end

import Pkg

function _env_true(name::AbstractString; default::Bool=false)
    value = lowercase(strip(get(ENV, name, default ? "1" : "0")))
    return !(value in ("", "0", "false", "no", "off"))
end

Pkg.activate(@__DIR__)
if !_env_true("SPARKBYTE_SKIP_PKG_INSTANTIATE")
    Pkg.instantiate()
end

include(joinpath(@__DIR__, "health_check.jl"))
run_health_check()

using JLEngine

try
    JLEngine.app_main()
catch err
    if err isa JLEngine.RuntimePortConflict
        println(stderr, "SparkByte startup stopped: ", sprint(showerror, err))
        exit(1)
    end
    rethrow()
end
