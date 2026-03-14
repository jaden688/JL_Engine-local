# Security Notes

## Local-first boundary

The full API in `jl_platform.services.api.main:app` is designed for trusted local use.

Do not expose it directly to the public internet without adding your own authentication, authorization, and network controls.

## Sensitive route groups

These route families can operate the local machine or workspace directly:

- `/tools/*`
- `/browser/*`
- `/workspace/*`
- `/self-edit/*`

They are useful for local operator workflows, but they should be treated as admin surfaces.

## Safer default posture

- bind to `127.0.0.1`
- keep the standalone UI local to the same machine
- put any remote exposure behind explicit auth and a reverse proxy
- avoid sharing live config files that contain provider keys or private endpoints

## User-facing engine flow

For the main conversational path, prefer the engine-mediated quest routes:

- `/quest/chat`
- `/quest/run`
- `/quest/mission`

Those keep the request inside the engine, quest runtime, and interpreter approval flow instead of calling local operator tools directly.

## Reporting

If you find a security issue, avoid posting full exploit details publicly before a fix exists. Share it privately with the maintainer first when possible.
