# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |

## Reporting a Vulnerability

Report security issues to the maintainer via GitHub Security Advisories — do **not** open a public issue for vulnerabilities.

---

## Intentional Design: Shell Execution (`cc.py`)

JL Engine Local includes a **shell command execution tool** (`src/jl_platform/core/tools/cc.py`) that intentionally passes commands to the system shell. This is a core feature — it allows the engine's fat agents (SparkByte, Gremlin, Slappy) to control the local machine as authorized by the user.

**This is opt-in and user-controlled:**

- The launcher (`launcher.bat`) exposes an **"Unsafe Tools"** toggle (`JL_LOCAL_UNSAFE_TOOLS`)
- When `OFF`, shell execution routes are disabled
- When `ON`, the user has explicitly consented to agent-driven shell access
- The engine's built-in **Safety Gate** and **Supervisor Gate** still filter commands at runtime

**CodeQL Alert Reference:** `Uncontrolled command line` in `cc.py:133` — this is a known, intentional pattern. The mitigation is the launcher toggle + runtime safety gates, not input sanitization of the command string itself.

---

## Path Traversal Mitigations

File paths supplied to `load_card()` and `register_mpf_agent()` are:
- Resolved to absolute paths via `Path.resolve()`
- Validated against an allowlist of file extensions (`.json`, `.mpf`, `.png`)
- Checked for file existence before reading

---

## API Keys

API keys are **never committed** to the repository.  
Copy `.env.example` to `.env` and fill in your own keys.  
`.env` is listed in `.gitignore` and will never be tracked.
