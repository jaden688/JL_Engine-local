
JL-Engine Modular Fat Agent Architecture

Structure Overview:

fat_agents/
    Full fat agent shells (SparkByte, Slappy, etc.)

profiles/
    Swappable internal components
    - tone
    - gates
    - tools
    - state
    - behavior
    - tasks

helpers/
    Small quick helper routines (not full agents)

loadouts/
    Preconfigured combinations of profiles

docs/
    Architecture explanations

Concept:
Fat agents remain stable shells while internal behavior is composed from
modular profile registries and loadouts.
