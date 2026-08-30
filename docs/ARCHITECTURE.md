# Architecture

FlowGuard is an execution control plane placed between callers and automation runtimes such as n8n.

## Core boundaries

### Control API
Owns workflow registration, execution requests, policy evaluation, approvals, audit events, and callbacks. External callers should request work through this layer rather than calling privileged n8n webhooks directly.

### Policy Engine
Pure deterministic logic. It receives workflow risk, estimated cost, dry-run state, and persisted policies and returns one of: `allow`, `require_approval`, `deny`, or `dry_run`.

### n8n Adapter
The control plane does not embed workflow logic. It invokes registered n8n webhook endpoints only after a policy decision allows execution. A shared secret is attached to calls in V0.1.

### Persistence
PostgreSQL stores workflows, policies, approvals, executions, and audit events. Redis is included now so the architecture can add durable background workers, locks, rate limits, and cache without redesigning the stack.

## State machine

```text
requested
  ├─ dry_run
  ├─ denied
  ├─ pending_approval ── approved ── running ── completed | failed
  │                    └─ rejected
  └─ running ── completed | failed
```

## Design principles

1. **The agent never grants itself authority.** Risk and policy live outside prompts and workflow payloads.
2. **Dry-run is a first-class execution state.** Evaluation can be tested without side effects.
3. **Human approval is a durable object.** It is not a transient UI confirmation.
4. **Every decision emits an audit event.** Audit data is separate from the current execution state.
5. **Automation runtime is replaceable.** n8n is the first adapter, not the control plane itself.

## Next architecture steps

- Queue execution work in Redis-backed workers.
- Add idempotency keys and replay protection.
- Add MCP tool registry with per-tool policies.
- Introduce workspace and tenant boundaries.
- Add OpenTelemetry spans covering control-plane and n8n execution IDs.
