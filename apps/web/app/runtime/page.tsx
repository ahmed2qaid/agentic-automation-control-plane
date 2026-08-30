'use client';

import {
  ArrowLeft,
  Bot,
  CircleDollarSign,
  GitBranch,
  RefreshCw,
  Repeat2,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import styles from './runtime.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

type Execution = {
  id: string;
  workflow_id: string;
  status: string;
  decision: string;
  risk_level: string;
  dry_run: boolean;
  estimated_cost_usd: number;
  requested_by: string;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type Workflow = {
  id: string;
  name: string;
  slug: string;
  risk_level: string;
  enabled: boolean;
  webhook_url: string;
};

type AuditEvent = {
  id: string;
  event_type: string;
  actor: string;
  data: Record<string, unknown>;
  created_at: string;
};

type CostEvent = {
  id: string;
  provider: string;
  model?: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  created_at: string;
};

type Relation = {
  id: string;
  source_execution_id: string;
  target_execution_id: string;
  relation_type: string;
  actor: string;
  created_at: string;
};

type Trace = {
  execution: Execution;
  workflow: Workflow;
  events: AuditEvent[];
  costs: CostEvent[];
  relations: Relation[];
  actual_cost_usd: number;
};

type Dashboard = {
  metrics: {
    workflows: number;
    enabled_workflows: number;
    pending_approvals: number;
    recent_failures: number;
    active_policies: number;
    actual_cost_usd?: number;
  };
  workflows: Workflow[];
  executions: Execution[];
};

type SyncResult = {
  discovered: number;
  imported: number;
  updated: number;
  skipped: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function shortId(id: string) {
  return id.slice(0, 8);
}

function when(value?: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

export default function RuntimePage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [trace, setTrace] = useState<Trace | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const workflowMap = useMemo(
    () => new Map((dashboard?.workflows || []).map((workflow) => [workflow.id, workflow])),
    [dashboard?.workflows],
  );

  const load = useCallback(async () => {
    try {
      setError('');
      const [dashboardData, executionData] = await Promise.all([
        request<Dashboard>('/api/dashboard'),
        request<Execution[]>('/api/executions?limit=100'),
      ]);
      setDashboard(dashboardData);
      setExecutions(executionData);
      setSelectedId((current) => current || executionData[0]?.id || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load runtime data.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setTrace(null);
      return;
    }
    request<Trace>(`/api/executions/${selectedId}/trace`)
      .then(setTrace)
      .catch((err: Error) => setError(err.message));
  }, [selectedId]);

  async function syncN8n() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await request<SyncResult>('/api/workflows/sync/n8n', { method: 'POST' });
      setMessage(
        `n8n sync: ${result.imported} imported, ${result.updated} updated, ${result.skipped} unchanged.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'n8n sync failed.');
    } finally {
      setBusy(false);
    }
  }

  async function deriveExecution(kind: 'retry' | 'replay') {
    if (!selectedId) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const execution = await request<Execution>(`/api/executions/${selectedId}/${kind}`, {
        method: 'POST',
        body: JSON.stringify({
          requested_by: 'runtime-console',
          ...(kind === 'replay' ? { dry_run: true } : {}),
        }),
      });
      setMessage(`${kind === 'retry' ? 'Retry' : 'Safe replay'} created: #${shortId(execution.id)}.`);
      await load();
      setSelectedId(execution.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${kind} failed.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div>
          <Link href="/" className={styles.back}><ArrowLeft size={15} /> Control room</Link>
          <p className={styles.eyebrow}>FLOWGUARD V0.2 · AGENTIC RUNTIME</p>
          <h1>Execution observability</h1>
          <p className={styles.lead}>
            Trace policy decisions, approvals, n8n runtime events, retry/replay lineage and real AI cost.
          </p>
        </div>
        <div className={styles.headerActions}>
          <button onClick={() => void load()} disabled={busy}><RefreshCw size={16} /> Refresh</button>
          <button className={styles.primary} onClick={syncN8n} disabled={busy}>
            <WorkflowIcon size={16} /> Sync n8n
          </button>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {message && <div className={styles.message}>{message}</div>}

      <section className={styles.metrics}>
        <Metric icon={<GitBranch size={17} />} label="Executions loaded" value={String(executions.length)} />
        <Metric
          icon={<CircleDollarSign size={17} />}
          label="Recorded AI cost"
          value={`$${(dashboard?.metrics.actual_cost_usd || 0).toFixed(4)}`}
        />
        <Metric
          icon={<ShieldCheck size={17} />}
          label="Pending approvals"
          value={String(dashboard?.metrics.pending_approvals || 0)}
        />
        <Metric icon={<Bot size={17} />} label="MCP tools" value="3" />
      </section>

      <div className={styles.grid}>
        <section className={styles.panel}>
          <div className={styles.panelTitle}>
            <div><h2>Executions</h2><p>Select a run to inspect its complete trace.</p></div>
          </div>
          <div className={styles.executionList}>
            {executions.map((execution) => {
              const workflow = workflowMap.get(execution.workflow_id);
              return (
                <button
                  key={execution.id}
                  className={`${styles.executionItem} ${selectedId === execution.id ? styles.active : ''}`}
                  onClick={() => setSelectedId(execution.id)}
                >
                  <div>
                    <strong>{workflow?.name || `Workflow ${shortId(execution.workflow_id)}`}</strong>
                    <span>#{shortId(execution.id)} · {when(execution.created_at)}</span>
                  </div>
                  <div className={styles.executionSide}>
                    <span data-status={execution.status}>{execution.status.replaceAll('_', ' ')}</span>
                    <small>{execution.risk_level}</small>
                  </div>
                </button>
              );
            })}
            {executions.length === 0 && <div className={styles.empty}>No executions yet.</div>}
          </div>
        </section>

        <section className={styles.tracePanel}>
          {!trace && <div className={styles.empty}>Select an execution to open its trace.</div>}
          {trace && (
            <>
              <div className={styles.traceHeader}>
                <div>
                  <p className={styles.eyebrow}>EXECUTION #{shortId(trace.execution.id)}</p>
                  <h2>{trace.workflow.name}</h2>
                  <div className={styles.tags}>
                    <span>{trace.execution.status}</span>
                    <span>{trace.execution.decision}</span>
                    <span>{trace.execution.risk_level} risk</span>
                    {trace.execution.dry_run && <span>dry-run</span>}
                  </div>
                </div>
                <div className={styles.traceActions}>
                  <button
                    onClick={() => deriveExecution('retry')}
                    disabled={busy || trace.execution.status !== 'failed'}
                    title="Retry is available only for failed executions"
                  >
                    <RotateCcw size={15} /> Retry
                  </button>
                  <button onClick={() => deriveExecution('replay')} disabled={busy}>
                    <Repeat2 size={15} /> Replay dry-run
                  </button>
                </div>
              </div>

              <div className={styles.traceStats}>
                <div><span>Estimated</span><strong>${trace.execution.estimated_cost_usd.toFixed(4)}</strong></div>
                <div><span>Actual</span><strong>${trace.actual_cost_usd.toFixed(4)}</strong></div>
                <div><span>Started</span><strong>{when(trace.execution.started_at)}</strong></div>
                <div><span>Finished</span><strong>{when(trace.execution.finished_at)}</strong></div>
              </div>

              <div className={styles.timeline}>
                {trace.events.map((event, index) => (
                  <article key={event.id} className={styles.timelineItem}>
                    <div className={styles.timelineRail}>
                      <span>{index + 1}</span>
                      {index < trace.events.length - 1 && <i />}
                    </div>
                    <div className={styles.timelineBody}>
                      <div><strong>{event.event_type}</strong><time>{when(event.created_at)}</time></div>
                      <p>{event.actor}</p>
                      <pre>{JSON.stringify(event.data, null, 2)}</pre>
                    </div>
                  </article>
                ))}
                {trace.events.length === 0 && <div className={styles.empty}>No trace events recorded.</div>}
              </div>

              <div className={styles.lowerGrid}>
                <section className={styles.subpanel}>
                  <h3><CircleDollarSign size={15} /> Cost events</h3>
                  {trace.costs.map((cost) => (
                    <div key={cost.id} className={styles.costRow}>
                      <div><strong>{cost.provider}</strong><span>{cost.model || 'unclassified model'}</span></div>
                      <div><strong>${cost.cost_usd.toFixed(4)}</strong><span>{cost.input_tokens + cost.output_tokens} tokens</span></div>
                    </div>
                  ))}
                  {trace.costs.length === 0 && <p className={styles.muted}>No actual cost events yet.</p>}
                </section>

                <section className={styles.subpanel}>
                  <h3><GitBranch size={15} /> Lineage</h3>
                  {trace.relations.map((relation) => (
                    <div key={relation.id} className={styles.relationRow}>
                      <Sparkles size={14} />
                      <div>
                        <strong>{relation.relation_type}</strong>
                        <span>#{shortId(relation.source_execution_id)} → #{shortId(relation.target_execution_id)}</span>
                      </div>
                    </div>
                  ))}
                  {trace.relations.length === 0 && <p className={styles.muted}>Original execution; no retry/replay lineage.</p>}
                </section>
              </div>

              {trace.execution.error && <div className={styles.executionError}>{trace.execution.error}</div>}
            </>
          )}
        </section>
      </div>

      <section className={styles.mcp}>
        <div className={styles.mcpIcon}><Bot size={20} /></div>
        <div>
          <p className={styles.eyebrow}>MCP GATEWAY</p>
          <h2>Agents can use FlowGuard without bypassing policy.</h2>
          <p>
            Connect an MCP client to <code>POST /mcp</code>. The gateway exposes workflow discovery,
            guarded execution requests and trace inspection. Execution tools still pass through the same
            policy engine and approval gates as dashboard requests.
          </p>
        </div>
        <code className={styles.endpoint}>{API_URL}/mcp</code>
      </section>
    </main>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <article className={styles.metric}>
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
