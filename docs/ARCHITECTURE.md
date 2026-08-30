# Architecture

FlowGuard is an execution control plane placed between callers and automation runtimes such as n8n. V0.2 also exposes a guarded MCP surface so AI agents can discover and request automation without receiving direct authority over privileged workflow endpoints.

## Core boundaries

### Control API
Owns workflow registration, execution requests, policy evaluation, approvals, audit events, retry/replay lineage, cost events and callbacks. External callers should request work through this layer rather than calling privileged n8n webhooks directly.

### Policy Engine
Pure deterministic logic. It receives workflow risk, estimated cost, dry-run state and persisted policies and returns one of: `allow`, `require_approval`, `deny`, or `dry_run`.

### MCP Gateway
Exposes a small tool surface at `POST /mcp`: workflow discovery, guarded execution requests and trace inspection. MCP execution requests call the same execution service as the REST API, so an agent cannot bypass risk, cost or approval policy by choosing MCP instead of HTTP endpoints.

### n8n Adapter + Registry Sync
The control plane does not embed workflow logic. It invokes registered n8n webhook endpoints only after policy allows execution. Registry sync uses the n8n API to discover workflows containing Webhook nodes and maps them to stable `n8n-<workflow-id>` slugs. Newly synchronized workflows default to `medium` risk so authority remains controlled by FlowGuard.

### Execution lineage
Retries and replays create new execution records rather than mutating historical runs. The `execution_relations` table links source and derived executions with `retry` or `replay`, preserving provenance and making replay visible in the runtime trace.

### Cost ledger
Actual provider usage is append-only in `cost_events`. Each entry stores provider, model, input/output tokens, cost and metadata. Estimated cost remains part of the execution request while actual cost is derived by summing cost events.

### Persistence
PostgreSQL stores workflows, policies, approvals, executions, execution relations, cost events and audit events. Redis is included so durable background workers, locks, rate limits and caching can be introduced without redesigning the stack.

## State machine

```text
requested
  ├─ dry_run
  ├─ denied
  ├─ pending_approval ── approved ── running ── completed | failed
  │                    └─ rejected
  └─ running ── completed | failed

failed ── retry ──> new execution ── policy evaluation...
any run ── replay ──> new dry-run by default ── policy evaluation...
```

## Trace model

An execution trace is assembled from independent durable records:

```text
Execution
  ├─ AuditEvent[]
  ├─ CostEvent[]
  └─ ExecutionRelation[]
```

Keeping these records separate prevents retries, cost updates or callback events from rewriting historical execution state.

## Design principles

1. **The agent never grants itself authority.** Risk and policy live outside prompts and workflow payloads.
2. **All entry points share the same guardrails.** REST, dashboard and MCP requests converge on the same policy path.
3. **Dry-run is a first-class execution state.** Evaluation can be tested without side effects.
4. **Human approval is a durable object.** It is not a transient UI confirmation.
5. **History is append-oriented.** Retry/replay creates lineage instead of overwriting the original execution.
6. **Estimated and actual cost are separate.** Budget policy can act before execution while provider usage is recorded afterward.
7. **Every decision emits an audit event.** Audit data is separate from current execution state.
8. **Automation runtime is replaceable.** n8n is the first adapter, not the control plane itself.

## Next architecture steps

- Queue execution work in Redis-backed durable workers.
- Add idempotency keys, dead-letter handling and exponential retry policy.
- Upgrade MCP transport with authenticated sessions and tool scopes.
- Add automatic provider adapters for token and cost accounting.
- Introduce workspace and tenant boundaries.
- Add workflow version diffing during n8n synchronization.
- Add OpenTelemetry spans covering FlowGuard, MCP clients and n8n execution IDs.
