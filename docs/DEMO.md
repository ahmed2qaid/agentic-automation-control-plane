# FlowGuard end-to-end demo

This walkthrough demonstrates the reason FlowGuard exists: a caller requests an automation, policy decides whether it is safe to run, a human can approve it, n8n performs the side effect, and FlowGuard keeps the execution trace.

## Scenario

A production-style outbound action is classified as **high risk**. An AI agent or application wants to trigger it. Instead of receiving the n8n webhook URL directly, the caller requests execution through FlowGuard.

Expected path:

```text
Caller → FlowGuard → Policy Engine → Pending Approval → Human Approval → n8n → Trace
```

## 1. Start the stack

```bash
cp .env.example .env
docker compose up --build -d
```

Open:

- Control Room: `http://localhost:3000`
- Runtime Console: `http://localhost:3000/runtime`
- API docs: `http://localhost:8000/docs`
- n8n: `http://localhost:5678`

## 2. Import the guarded n8n workflow

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/guarded-action.json
```

Open n8n and activate **FlowGuard - Guarded Action Demo**.

The seeded FlowGuard registry points its demo workflow at:

```text
http://n8n:5678/webhook/guarded-action
```

The workflow verifies `X-FlowGuard-Secret` before processing the payload.

## 3. Find the workflow ID

```bash
curl http://localhost:8000/api/workflows
```

Copy the `id` for **Guarded Action Demo**.

## 4. Prove dry-run is side-effect free

```bash
curl -X POST http://localhost:8000/api/executions \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow_id":"<workflow-id>",
    "input":{"recipient":"demo@example.com","message":"Weekly operations update"},
    "estimated_cost_usd":0.02,
    "dry_run":true,
    "requested_by":"demo-operator"
  }'
```

Expected result: the execution enters `dry_run`. FlowGuard records the request and policy decision but does not call n8n.

## 5. Request a real high-risk execution

Run the same request with `dry_run` set to `false`:

```bash
curl -X POST http://localhost:8000/api/executions \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow_id":"<workflow-id>",
    "input":{"recipient":"demo@example.com","message":"Weekly operations update"},
    "estimated_cost_usd":0.02,
    "dry_run":false,
    "requested_by":"demo-operator"
  }'
```

Because the demo workflow is high risk, the expected status is:

```text
pending_approval
```

Nothing should have executed in n8n yet.

## 6. Approve from the Control Room

Open `http://localhost:3000` and approve the pending execution.

FlowGuard will then:

1. persist the approval decision;
2. release the execution;
3. call the registered n8n webhook with the FlowGuard secret;
4. persist the result;
5. append execution/audit events.

## 7. Inspect the execution trace

Open the Runtime Console at `http://localhost:3000/runtime`, choose the execution, and inspect the timeline.

Or use the API:

```bash
curl http://localhost:8000/api/executions/<execution-id>/trace
```

The trace is assembled from durable records rather than one mutable log object:

```text
Execution
├── AuditEvent[]
├── CostEvent[]
└── ExecutionRelation[]
```

## 8. Record provider cost

A worker, agent adapter or n8n step can append actual provider usage:

```bash
curl -X POST http://localhost:8000/api/executions/<execution-id>/costs \
  -H 'Content-Type: application/json' \
  -H 'X-FlowGuard-Secret: change-me-in-production' \
  -d '{
    "provider":"openai",
    "model":"example-model",
    "input_tokens":1200,
    "output_tokens":300,
    "cost_usd":0.0134,
    "metadata":{"step":"generate-message"}
  }'
```

The Runtime Console now shows estimated cost beside accumulated actual cost.

## 9. Demonstrate safe replay

Replay the historical execution:

```bash
curl -X POST http://localhost:8000/api/executions/<execution-id>/replay \
  -H 'Content-Type: application/json' \
  -d '{"requested_by":"demo-operator"}'
```

Replay creates a **new** execution linked to the source and defaults to dry-run. The original history is never overwritten.

## 10. Demonstrate the MCP guardrail

List MCP tools:

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

An AI agent can call `flowguard.request_execution`, but the request still enters the same Policy Engine. MCP is another entry point, not a policy bypass.

## What this demo proves

A successful demo should make these properties visible:

- the automation runtime does not decide its own authority;
- dry-run produces no n8n side effect;
- high-risk work waits for durable human approval;
- MCP callers share the same policy path;
- retries/replays do not rewrite execution history;
- estimated and actual cost are distinct;
- operators can reconstruct what happened from the trace and audit trail.
