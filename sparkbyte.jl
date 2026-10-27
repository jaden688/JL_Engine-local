# SparkByte's supported repository-root entrypoint.
# Run with: julia sparkbyte.jl
# The shared startup implementation configures the Julia project and starts JLEngine.
include(joinpath(@__DIR__, "start.jl"))
