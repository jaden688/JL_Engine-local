# JL Engine — Compliance & Audit Execution Plan
# Alberta PIPA + Operator Audit Log
# drafted: 2026-04-30

---

## PRIORITY ORDER

### P0 — Data Protection (PIPA required, do first)
- [x] 1. PII scrubber — redact emails, phones, IPs, names before writing to DB
- [x] 2. IP hashing in A2A — hash raw IPs with daily salt, never store plaintext
- [x] 3. Data retention — auto-purge telemetry/thoughts/turns older than 90 days

### P1 — Audit Log (operator-only, full fidelity)
- [x] 4. Human-readable audit log per session — full chain of thought, full tool args, full output, zero truncation
- [x] 5. LLM reasoning between tool calls captured (the "why" before each tool)
- [x] 6. Audit log is operator-only, never mixed with user data tables

### P2 — Consent & Disclosure (PIPA required before public launch)
- [x] 7. A2A agent card includes privacy_policy field + data_collected disclosure
- [x] 8. Privacy policy document (plain English, Alberta PIPA compliant) — PRIVACY.md
- [x] 9. A2A endpoint serves policy at GET /privacy; agent card links to it

### P3 — User Rights (PIPA required)
- [x] 10. Data subject access — POST /privacy/request {"type":"access",...} returns record counts
- [x] 11. Deletion endpoint — POST /privacy/request {"type":"deletion",...} purges matching records immediately

---

## IMPLEMENTATION NOTES

### PII Scrubber (item 1)
Location: `BYTE/src/Telemetry.jl` — extend `_redact_sensitive_text`
Patterns to catch:
  - Email: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b/
  - Phone: /(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/
  - IP: /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/
  - SIN (Canada): /\b\d{3}[-\s]\d{3}[-\s]\d{3}\b/
  - Credit card: /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/
Applied to: all text before it hits SQLite (user messages, tool args, thoughts, replies)

### IP Hashing (item 2)
Location: `a2a_server.jl`
Method: SHA256(ip + date_bucket + SPARKBYTE_IP_SALT) → store hash only
Free-call quota works on hash, never on raw IP

### Data Retention (item 3)
Location: new function `_run_retention_sweep!(db)` called on boot + daily
Tables: telemetry, thoughts, turn_snapshots, web_cache
Default: 90 days (configurable via SPARKBYTE_DATA_RETENTION_DAYS)
Intentions and memory table: NOT purged (user's own data, different rules)

### Audit Log (items 4-6)
Location: `BYTE/src/Telemetry.jl` — new `audit_*` functions
Output: `logs/audit_<session_id>.log` (human readable, operator-only)
Format:
  ═══ TURN N [timestamp] session=X ═══
  USER: <full message>
  STATE: gait=X aperture=X temp=X drift=X
  MODEL: X  temp=X
  [LOOP 1]
  REASONING: <full LLM text before tool call>
  TOOL: <name>
    <full args as pretty JSON>
  RESULT: (Nms)
    <full output, no truncation>
  [LOOP N] FINAL REPLY
  REPLY: <full text>
  ════════════════════════════════════

### Privacy Policy (item 8)
Location: `PRIVACY.md` in root + served at /privacy on the A2A server
Must cover: what's collected, why, how long, who can access, how to delete

---

## STATUS
Started: 2026-04-30  
**COMPLETE: 2026-04-30** — all 11 items shipped. Engine restart required to activate.
