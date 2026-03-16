# Security Policy

## Supported Versions

The following versions of JL Engine are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.0   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please **do not** open a public GitHub issue.

Instead, report it privately by following these steps:

1. Go to the [Security Advisories](../../security/advisories/new) page for this repository and submit a new draft advisory.
2. Include as much detail as possible:
   - A description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact
   - Any suggested mitigations or fixes

You can expect an initial response within **72 hours**. Once the issue is confirmed, we will work on a fix and coordinate a disclosure timeline with you before making any details public.

Please avoid posting full exploit details publicly before a fix is available.

## Security Notes

### Local-first boundary

The full API in `jl_platform.services.api.main:app` is designed for trusted local use.

Do not expose it directly to the public internet without adding your own authentication, authorization, and network controls.

### Sensitive route groups

These route families can operate the local machine or workspace directly:

- `/tools/*`
- `/browser/*`
- `/workspace/*`
- `/self-edit/*`

They are useful for local operator workflows, but they should be treated as admin surfaces.

### Safer default posture

- Bind to `127.0.0.1`
- Keep the standalone UI local to the same machine
- Put any remote exposure behind explicit auth and a reverse proxy
- Avoid sharing live config files that contain provider keys or private endpoints

### User-facing engine flow

For the main conversational path, prefer the engine-mediated quest routes:

- `/quest/chat`
- `/quest/run`
- `/quest/mission`

Those keep the request inside the engine, quest runtime, and interpreter approval flow instead of calling local operator tools directly.
