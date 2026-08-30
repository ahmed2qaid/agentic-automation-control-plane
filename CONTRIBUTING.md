# Contributing to FlowGuard

FlowGuard is an early-stage reference implementation for safer n8n and agentic automation. Focused contributions that strengthen execution safety, reliability, observability, or developer experience are welcome.

## Good areas to contribute

- durable Redis-backed execution workers;
- dead-letter queue and retry strategy;
- idempotency and webhook replay protection;
- authenticated MCP clients and per-tool scopes;
- OpenTelemetry traces and metrics;
- provider-specific token/cost adapters;
- n8n workflow version diffing;
- tests for policy, lineage, approval, and callback edge cases;
- documentation and reproducible demo scenarios.

## Local development

Start infrastructure:

```bash
cp .env.example .env
docker compose up --build -d
```

API checks:

```bash
cd apps/api
pip install -e '.[dev]'
ruff check app tests
pytest -q
```

Web checks:

```bash
cd apps/web
npm install
npm run build
```

The same API and web checks run in GitHub Actions.

## Contribution principles

1. **Do not create policy bypasses.** Dashboard, REST, MCP, retries, and replays should converge on the same authority model.
2. **Preserve history.** Prefer append-oriented events/relations over mutating prior execution facts.
3. **Default to safe behavior.** New replay, bulk, external, or destructive actions should be dry-run/approval oriented by default.
4. **Keep secrets server-side.** Never expose n8n API keys or shared secrets in browser bundles.
5. **Add tests for control-plane behavior.** Security-sensitive changes should include deterministic tests where practical.
6. **Document production limitations.** A local demo capability should not be described as production hardened unless the required controls exist.

## Pull requests

Keep pull requests focused. Explain:

- the problem being solved;
- the control-plane behavior before and after the change;
- security or side-effect implications;
- how the change was tested.

For architecture-level changes, open an issue first so the execution and trust boundaries can be discussed before implementation.
