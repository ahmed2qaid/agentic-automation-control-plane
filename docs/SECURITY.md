# Security model

FlowGuard V0.1 is a local-first reference implementation. It demonstrates the control boundaries required for safer agentic automation but it is not a complete production security perimeter.

## Current controls

- Workflow risk is stored server-side.
- High-risk actions require a durable approval record.
- Critical workflows are denied by default.
- Expensive executions require approval by default.
- Dry-run mode never calls n8n.
- FlowGuard attaches `X-FlowGuard-Secret` when invoking n8n.
- n8n callbacks to the control plane must present the same shared secret.
- Audit events record requester, decision, approval, and execution transitions.

## Before production

1. Replace the shared secret with HMAC-signed requests containing timestamp, nonce, and body digest.
2. Add replay protection and idempotency keys.
3. Put FlowGuard, workers, n8n, Redis, and PostgreSQL on private networks.
4. Store credentials in a secret manager and rotate them.
5. Add authentication and workspace-scoped RBAC to the API and dashboard.
6. Require step-up approval for critical categories instead of relying only on risk labels.
7. Add outbound host allowlists for automation runtimes.
8. Encrypt sensitive execution inputs and redact audit payloads.
9. Add rate limits, concurrency limits, and per-workflow budgets.
10. Export audit events to immutable external storage / SIEM.

## Threats the control plane is meant to reduce

- Prompt-induced unauthorized tool calls
- Accidental bulk actions
- Unreviewed destructive operations
- Runaway API or LLM costs
- Hidden workflow side effects
- Poor attribution after automation failures
