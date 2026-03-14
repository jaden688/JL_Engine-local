Canonical JL agents live in this folder.

Intent:
- These are first-class JL agents, not mothership fat-agent agents.
- They are not generated throwaways.
- They may still spin tools up, run operator workflows, and participate in quest runtime flows.

Rules:
- Registry entries for these payloads use `classification: "jl_agent"`.
- Keep them separate from `fat_agents/` and `generated/`.
- Runtime support payloads like deck-only helpers should not be mixed into this folder unless they are promoted into real JL agents.
