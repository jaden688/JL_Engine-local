# MPF Open Standard in This Repo

## Purpose

JL Engine uses MPF as a short registry plus full payload system.

- the registry names the available profiles
- the payload files hold the actual fat-agent or JL-agent configuration

In this checkout, the active registry path is:

`jl_engine_core/data/agents/JL_Agents.mpf.json`

That `agents` tree is the canonical runtime source of truth.

## Registry versus payload

The registry is the pointer layer. A typical entry maps a display name to a payload file and runtime defaults.

Common payload families in this repo:

- `fat_agents/*.json`
- `jl_agents/*.json`
- `generated/*.json`

Examples:

- `SparkByte` -> `fat_agents/SparkByte_Full.json`
- `SparkByte Modular` -> modular payload resolved from its shell config at load time

## What the engine actually loads

When a session selects an agent:

1. `JLEngineCore` reads the registry entry.
2. The engine resolves the referenced payload file.
3. If the payload is modular, it is expanded first.
4. The resolved payload becomes the active session profile.

That means the registry should stay small and stable, while the detailed behavior lives in the payload files.

## Schema layers

This repository keeps two schema references:

- `config/agent_schema.json`
- `config/mpf_registry_schema.json`

The runtime still accepts older JL payload shapes for compatibility, but new builders should prefer explicit MPF-style identity and behavior blocks where possible.

## Practical guidance

- treat `jl_engine_core/data/...` as the canonical runtime tree
- treat `jl_engine_core/data/agents/` as the canonical runtime agent tree
- the old root `personas/` mirror has been retired
- `jl_engine_core/data/personas/` remains only as a legacy compatibility mirror and should not be edited directly
- keep registry entries readable and move large behavior definitions into payload files
- use modular fat agents when you want a reusable shell with generated or composed layers
