# Error Handling Notes

## Current response patterns

The repo currently uses three common error styles:

1. FastAPI/framework errors
   These usually return standard HTTP status codes with a `detail` field.
2. Action-style responses
   These usually return JSON with `status: "ok"` or `status: "error"` and a stable short `error` code.
3. Approval-gated responses
   These return a confirmation-required status when a privileged action needs user approval before execution.

## What clients should expect

- validation errors may come back as FastAPI `detail` payloads
- local operator tools usually return `status`, `error`, and optional `message`
- quest/interpreter calls may return success data plus pending confirmation metadata

## Guidance for new work

- prefer stable machine-readable `error` codes for action endpoints
- reserve free-form `message` text for human diagnostics
- keep `status` explicit on non-framework action routes
- use HTTP exceptions for transport or validation failures, not for normal local workflow branching
- keep approval-required flows distinct from hard failures

## Why this matters

This repo mixes UI routes, quest runtime, browser bridge, workspace operations, and tool-forge endpoints. A stable error contract helps the web UIs and future clients behave predictably without changing engine behavior.
