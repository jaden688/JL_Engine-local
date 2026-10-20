# Privacy Policy — JL Engine / SparkByte

**Jurisdiction:** Alberta, Canada  
**Governing law:** *Personal Information Protection Act* (PIPA), SA 2003, c P-6.5  
**Operator:** Jaden Lindenbach — jadenlindenbach@gmail.com  
**Effective date:** 2026-04-30  
**Last updated:** 2026-04-30

---

## 1. Who this covers

This policy applies to anyone who interacts with the JL Engine or SparkByte AI agent — whether through the web UI, the A2A (agent-to-agent) API, or any third-party integration that routes requests through these services.

---

## 2. What we collect

When you send a message or invoke a tool, the system may record:

| Data | Purpose | How it's stored |
|------|---------|-----------------|
| Message content | Powering responses and memory | PII is scrubbed before write (see §4) |
| Session identifier | Linking turns in a conversation | Temporary — purged after 90 days |
| Hashed IP address | Free-call quota enforcement | SHA-256 hash with daily-rotating salt — raw IP is **never** stored |
| Tool call names and arguments | Debugging and audit trail | PII scrubbed; full detail in operator-only audit log |
| Task outcomes and errors | Reliability monitoring | Stored in telemetry DB, purged after 90 days |

We do **not** collect:

- Names, addresses, or government ID numbers (unless you type them in a message — in which case they are scrubbed before storage)
- Payment card numbers or bank details
- Passwords or authentication secrets

---

## 3. How we use it

- **To answer your requests** — message history lets the agent maintain context across turns.
- **To improve reliability** — telemetry helps identify errors and slow tools.
- **To enforce fair-use limits** — the hashed IP prevents a single caller from consuming unlimited free calls; it is never used to track behaviour across days (daily salt rotation ensures this).
- **Operator audit trail** — Alberta PIPA and general accountability principles require us to keep a full record of what the agent did and why. This log lives in an operator-only directory and is never exposed to users or third parties.

We do **not** sell, rent, or share your information with advertisers or data brokers.

---

## 4. How we protect it

**PII scrubbing** — before any user-supplied text is written to the database, it is scanned for and redacted:

- Email addresses
- Phone numbers (Canadian and US formats)
- IPv4 addresses
- Canadian Social Insurance Numbers (SINs)
- Credit / debit card numbers
- Canadian postal codes

**IP hashing** — raw IP addresses are hashed with SHA-256 using a daily salt (`SPARKBYTE_IP_SALT` + date). The hash is stored; the plaintext IP is discarded immediately.

**Encryption at rest** — the SQLite database file lives on the operator's server. At-rest encryption is the operator's responsibility; production deployments should use encrypted volumes.

**Access control** — the audit log directory (`logs/`) is operator-only. No API endpoint exposes audit log contents. The telemetry database is read only by the local Julia process.

---

## 5. How long we keep it

| Table | Retention |
|-------|-----------|
| `telemetry` | 90 days (configurable via `SPARKBYTE_DATA_RETENTION_DAYS`) |
| `thoughts` | 90 days |
| `turn_snapshots` | 90 days |
| `web_cache` | 90 days |
| `intentions` | Kept until manually cleared (operator's own goal queue) |
| `memory` | Kept until you request deletion (it's your data) |
| Operator audit logs | Operator's discretion — minimum 90 days recommended |

A retention sweep runs automatically on engine start and once per day thereafter.

---

## 6. Your rights under Alberta PIPA

You have the right to:

1. **Access** — request a copy of everything stored that relates to you.
2. **Correction** — ask us to correct inaccurate information.
3. **Deletion** — ask us to delete your data. We will wipe all records keyed to your IP hash or session identifier within 7 business days.
4. **Withdraw consent** — stop using the service at any time; we will honour deletion requests even after you stop.
5. **Lodge a complaint** — if you believe we've violated PIPA, you may contact the [Office of the Information and Privacy Commissioner of Alberta](https://www.oipc.ab.ca/).

---

## 7. How to exercise your rights

Send a request to the endpoint below **or** email directly:

```
POST /privacy/request
Content-Type: application/json

{
  "type": "access" | "deletion" | "correction",
  "identifier": "<your IP address or session ID>",
  "details": "<optional free-text>"
}
```

Or email: **jadenlindenbach@gmail.com** with subject line `PIPA Request`.

We will acknowledge within **2 business days** and fulfil within **30 calendar days** as required by PIPA s. 25.

---

## 8. Third-party services

The engine may call external APIs (OpenAI, Anthropic, Google Gemini, Fetch.ai, GitHub, etc.) on your behalf. Those providers have their own privacy policies. We pass only the content necessary to complete your request — we do not send your IP address or session identifier to third parties.

---

## 9. Changes to this policy

Material changes will be noted with an updated "Last updated" date at the top of this document. Continued use of the service after the update constitutes acceptance of the revised policy.

---

## 10. Contact

**Operator:** Jaden Lindenbach  
**Email:** jadenlindenbach@gmail.com  
**Location:** Alberta, Canada
