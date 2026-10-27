using Pkg
Pkg.instantiate()
include(joinpath(ENV["JL_ENGINE_APP_DIR"], "sparkbyte.jl"))
