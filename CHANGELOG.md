# Changelog

All notable changes to FlowGuard are documented here.

## [0.2.0] - 2026-08-30

### Added

- Guarded MCP gateway with `initialize`, `tools/list`, and `tools/call` JSON-RPC flow.
- MCP tools for workflow discovery, guarded execution requests, and execution traces.
- n8n API synchronization for workflows containing Webhook nodes.
- Retry for failed executions with policy re-evaluation.
- Safe replay that creates a new related execution and defaults to dry-run.
- Durable retry/replay lineage through `execution_relations`.
- Provider/model cost events with input/output token counts.
- Estimated-versus-actual cost aggregation.
- Runtime Console for execution trace, lineage, and cost inspection.
- v0.2 architecture and security documentation.
- End-to-end guarded automation demo.

### Safety behavior

- MCP does not bypass the Policy Engine.
- High-risk work still requires human approval.
- Critical work remains denied by default.
- Replay defaults to dry-run to avoid silently repeating historical side effects.
- Cost events are append-oriented instead of rewriting execution history.

## [0.1.0] - 2026-08-30

### Added

- FastAPI control plane.
- Next.js operator dashboard.
- n8n webhook execution adapter.
- Workflow Registry.
- Policy Engine with `allow`, `require_approval`, `deny`, and `dry_run` outcomes.
- Human-in-the-loop approval queue.
- Audit events and execution history.
- PostgreSQL and Redis-ready Docker Compose stack.
- Example guarded n8n workflow.
- GitHub Actions CI for Python lint/tests and Next.js production build.
