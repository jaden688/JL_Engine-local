# Canonical cross-platform JL Engine entrypoint.
# Run from the repository root: julia --project=. start.jl

ENV["JULIA_CONDAPKG_BACKEND"] = get(ENV, "JULIA_CONDAPKG_BACKEND", "Null")
ENV["JULIA_PYTHONCALL_EXE"] = get(ENV, "JULIA_PYTHONCALL_EXE", "python")

import Pkg
Pkg.activate(@__DIR__)
if lowercase(strip(get(ENV, "SPARKBYTE_SKIP_PKG_INSTANTIATE", "0"))) ∉ ("1", "true", "yes", "on")
    Pkg.instantiate()
end

using JLEngine
exit(JLEngine.julia_main())
