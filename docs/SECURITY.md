# Security model

FlowGuard V0.2 is a local-first reference implementation. It demonstrates control boundaries for safer agentic automation, but it is not a complete production security perimeter.

## Current controls

- Workflow risk is stored server-side rather than trusted from agent input.
- High-risk actions require a durable approval record.
- Critical workflows are denied by default.
- Expensive executions require approval by default.
- Dry-run mode never calls n8n.
- Retry and replay re-enter policy evaluation instead of bypassing previous decisions.
- Replay defaults to dry-run to reduce accidental repeated side effects.
- Retry/replay lineage is persisted separately from the source execution.
- FlowGuard attaches `X-FlowGuard-Secret` when invoking n8n.
- n8n callbacks and cost-ingestion calls must present the same shared secret.
- Actual provider costs are append-only cost events rather than client-controlled execution totals.
- MCP execution requests use the same policy path as REST/dashboard requests.
- Audit events record requester, decision, approval, execution, replay and cost transitions.

## Important V0.2 limitations

### MCP authentication
The MCP endpoint does not yet authenticate clients. It is intended for local/private-network development in V0.2. Do not expose `/mcp` directly to the public Internet in this version.

### Shared-secret callbacks
n8n callbacks and cost ingestion use a static shared secret. This authenticates a cooperating service but does not provide request freshness, replay protection or per-client identity.

### n8n API key
`N8N_API_KEY` grants workflow-read access for registry synchronization. Treat it as a server-side secret, never expose it to the browser, and grant only the minimum n8n permissions available.

### Payload storage
Execution input/output and audit metadata may contain sensitive information. V0.2 does not automatically classify, encrypt or redact those fields.

## Before production

1. Replace the shared secret with HMAC-signed requests containing timestamp, nonce and body digest.
2. Add replay protection and idempotency keys for execution requests and callbacks.
3. Authenticate MCP clients and issue per-client scopes for read vs execution tools.
4. Add authentication and workspace-scoped RBAC to the API and dashboard.
5. Put FlowGuard, workers, n8n, Redis and PostgreSQL on private networks.
6. Store n8n/API/provider credentials in a secret manager and rotate them.
7. Require step-up or multi-stage approval for critical categories instead of relying only on risk labels.
8. Add outbound host allowlists for automation runtimes and agent tools.
9. Encrypt sensitive execution inputs and redact audit/trace payloads.
10. Add rate limits, concurrency limits and per-workflow/provider budgets.
11. Sign cost events or ingest them only from authenticated provider adapters/workers.
12. Export audit events to immutable external storage / SIEM.
13. Add tenant/workspace boundaries before serving multiple organizations.
14. Add OpenTelemetry/alerting for unusual retry storms, approval bypass attempts and cost spikes.

## Threats the control plane is meant to reduce

- Prompt-induced unauthorized tool calls
- Agent attempts to bypass approval by switching interfaces
- Accidental bulk actions
- Unreviewed destructive operations
- Replaying historical side effects unintentionally
- Runaway API or LLM costs
- Hidden workflow side effects
- Poor attribution after automation failures
- Silent mutation of execution history
