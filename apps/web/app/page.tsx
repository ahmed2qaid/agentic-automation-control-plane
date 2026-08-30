'use client';

import {
  Activity,
  Check,
  CircleDollarSign,
  Clock3,
  FileClock,
  Gauge,
  GitBranch,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  ShieldX,
  Workflow as WorkflowIcon,
  X,
} from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

type Workflow = {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  webhook_url: string;
  risk_level: string;
  enabled: boolean;
  created_at: string;
};

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
};

type Approval = {
  id: string;
  execution_id: string;
  status: string;
  requested_at: string;
  decided_by?: string | null;
};

type Policy = {
  id: string;
  name: string;
  action: string;
  risk_levels: string[];
  min_cost_usd?: number | null;
  priority: number;
  enabled: boolean;
};

type AuditEvent = {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  data: Record<string, unknown>;
  created_at: string;
};

type Dashboard = {
  metrics: {
    workflows: number;
    enabled_workflows: number;
    pending_approvals: number;
    recent_failures: number;
    active_policies: number;
  };
  workflows: Workflow[];
  executions: Execution[];
  approvals: Approval[];
  policies: Policy[];
};

type Section = 'overview' | 'workflows' | 'policies' | 'audit';

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

function when(value: string) {
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function badgeClass(value: string) {
  return `badge badge-${value.replaceAll('_', '-')}`;
}

export default function Home() {
  const [section, setSection] = useState<Section>('overview');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const [workflowId, setWorkflowId] = useState('');
  const [payloadText, setPayloadText] = useState('{\n  "task": "prepare weekly operations summary"\n}');
  const [estimatedCost, setEstimatedCost] = useState('0.02');
  const [dryRun, setDryRun] = useState(true);
  const [requestedBy, setRequestedBy] = useState('dashboard-user');

  const [newWorkflow, setNewWorkflow] = useState({
    slug: '',
    name: '',
    webhook_url: 'http://n8n:5678/webhook/guarded-action',
    risk_level: 'medium',
    description: '',
  });

  const refresh = useCallback(async () => {
    try {
      setError('');
      const data = await request<Dashboard>('/api/dashboard');
      setDashboard(data);
      setWorkflowId((current) => current || data.workflows[0]?.id || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load FlowGuard API');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (section !== 'audit') return;
    request<AuditEvent[]>('/api/audit?limit=100').then(setAudit).catch((err) => setError(err.message));
  }, [section]);

  const workflowMap = useMemo(
    () => new Map((dashboard?.workflows || []).map((workflow) => [workflow.id, workflow])),
    [dashboard?.workflows],
  );
  const executionMap = useMemo(
    () => new Map((dashboard?.executions || []).map((execution) => [execution.id, execution])),
    [dashboard?.executions],
  );

  async function submitExecution(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const parsed = JSON.parse(payloadText);
      const result = await request<Execution>('/api/executions', {
        method: 'POST',
        body: JSON.stringify({
          workflow_id: workflowId,
          input: parsed,
          estimated_cost_usd: Number(estimatedCost || 0),
          dry_run: dryRun,
          requested_by: requestedBy,
        }),
      });
      setMessage(`Execution ${shortId(result.id)} → ${result.status}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to request execution');
    } finally {
      setBusy(false);
    }
  }

  async function decideApproval(approval: Approval, approved: boolean) {
    setBusy(true);
    setError('');
    try {
      await request(`/api/approvals/${approval.id}/decision`, {
        method: 'POST',
        body: JSON.stringify({
          approved,
          decided_by: 'dashboard-approver',
          note: approved ? 'Approved from FlowGuard dashboard' : 'Rejected from FlowGuard dashboard',
        }),
      });
      setMessage(approved ? 'Execution approved and released.' : 'Execution rejected.');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval decision failed');
    } finally {
      setBusy(false);
    }
  }

  async function registerWorkflow(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await request('/api/workflows', {
        method: 'POST',
        body: JSON.stringify(newWorkflow),
      });
      setNewWorkflow({
        slug: '',
        name: '',
        webhook_url: 'http://n8n:5678/webhook/guarded-action',
        risk_level: 'medium',
        description: '',
      });
      setMessage('Workflow registered.');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to register workflow');
    } finally {
      setBusy(false);
    }
  }

  const nav = [
    { id: 'overview' as const, label: 'Control room', icon: Gauge },
    { id: 'workflows' as const, label: 'Workflows', icon: WorkflowIcon },
    { id: 'policies' as const, label: 'Policies', icon: ShieldCheck },
    { id: 'audit' as const, label: 'Audit trail', icon: ScrollText },
  ];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><ShieldCheck size={22} /></div>
          <div><strong>FlowGuard</strong><span>Control Plane</span></div>
        </div>

        <nav className="nav-list">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={section === item.id ? 'nav-item active' : 'nav-item'} onClick={() => setSection(item.id)}>
                <Icon size={18} /><span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-status">
          <span className="live-dot" />
          <div><strong>Policy enforcement</strong><span>Active locally</span></div>
        </div>
      </aside>

      <section className="main-column">
        <header className="topbar">
          <div>
            <p className="eyebrow">AGENTIC AUTOMATION CONTROL PLANE</p>
            <h1>{section === 'overview' ? 'Control room' : nav.find((item) => item.id === section)?.label}</h1>
          </div>
          <button className="button secondary" onClick={refresh} disabled={busy} title="Refresh dashboard">
            <RefreshCw size={16} /> Refresh
          </button>
        </header>

        <div className="content">
          {error && <div className="notice error"><ShieldX size={18} />{error}</div>}
          {message && <div className="notice success"><Check size={18} />{message}</div>}
          {loading && <div className="loading">Loading control plane…</div>}

          {!loading && dashboard && section === 'overview' && (
            <>
              <div className="metrics-grid">
                <Metric icon={GitBranch} label="Registered workflows" value={dashboard.metrics.workflows} detail={`${dashboard.metrics.enabled_workflows} enabled`} />
                <Metric icon={Clock3} label="Pending approvals" value={dashboard.metrics.pending_approvals} detail="Human gate" tone="warn" />
                <Metric icon={ListChecks} label="Active policies" value={dashboard.metrics.active_policies} detail="Ordered by priority" />
                <Metric icon={Activity} label="Recent failures" value={dashboard.metrics.recent_failures} detail="Last 12 executions" tone={dashboard.metrics.recent_failures ? 'danger' : 'default'} />
              </div>

              <div className="overview-grid">
                <section className="panel composer-panel">
                  <PanelHeading title="Request execution" subtitle="Evaluate policy before any n8n side effect" icon={Play} />
                  <form className="form-stack" onSubmit={submitExecution}>
                    <label>Workflow
                      <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} required>
                        {dashboard.workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name} · {workflow.risk_level}</option>)}
                      </select>
                    </label>
                    <label>Input payload
                      <textarea rows={7} value={payloadText} onChange={(e) => setPayloadText(e.target.value)} spellCheck={false} />
                    </label>
                    <div className="form-row">
                      <label>Estimated cost (USD)
                        <input type="number" min="0" step="0.01" value={estimatedCost} onChange={(e) => setEstimatedCost(e.target.value)} />
                      </label>
                      <label>Requested by
                        <input value={requestedBy} onChange={(e) => setRequestedBy(e.target.value)} />
                      </label>
                    </div>
                    <label className="toggle-row">
                      <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
                      <span><strong>Dry-run first</strong><small>Evaluate and audit without calling n8n.</small></span>
                    </label>
                    <button className="button primary" disabled={busy || !workflowId}><Play size={16} /> Evaluate request</button>
                  </form>
                </section>

                <section className="panel">
                  <PanelHeading title="Approval queue" subtitle="High-risk and over-budget operations" icon={Clock3} />
                  <div className="approval-list">
                    {dashboard.approvals.length === 0 && <Empty text="No executions are waiting for approval." />}
                    {dashboard.approvals.map((approval) => {
                      const execution = executionMap.get(approval.execution_id);
                      const workflow = execution ? workflowMap.get(execution.workflow_id) : undefined;
                      return (
                        <article className="approval-card" key={approval.id}>
                          <div className="approval-top">
                            <div><strong>{workflow?.name || 'Workflow execution'}</strong><span>{when(approval.requested_at)} · #{shortId(approval.execution_id)}</span></div>
                            <span className={badgeClass(execution?.risk_level || 'high')}>{execution?.risk_level || 'high'}</span>
                          </div>
                          <div className="approval-meta"><CircleDollarSign size={15} /> Estimated ${execution?.estimated_cost_usd.toFixed(2) || '0.00'}</div>
                          <div className="approval-actions">
                            <button className="button approve" disabled={busy} onClick={() => decideApproval(approval, true)}><Check size={15} /> Approve</button>
                            <button className="button reject" disabled={busy} onClick={() => decideApproval(approval, false)}><X size={15} /> Reject</button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              </div>

              <section className="panel">
                <PanelHeading title="Recent executions" subtitle="Decision and runtime state in one timeline" icon={FileClock} />
                <ExecutionTable executions={dashboard.executions} workflowMap={workflowMap} />
              </section>
            </>
          )}

          {!loading && dashboard && section === 'workflows' && (
            <div className="two-column">
              <section className="panel">
                <PanelHeading title="Workflow registry" subtitle="Authority and risk live outside n8n payloads" icon={WorkflowIcon} />
                <div className="registry-list">
                  {dashboard.workflows.map((workflow) => (
                    <article className="registry-card" key={workflow.id}>
                      <div className="registry-main">
                        <div className="workflow-icon"><WorkflowIcon size={18} /></div>
                        <div><strong>{workflow.name}</strong><code>{workflow.slug}</code><span>{workflow.description || 'No description'}</span></div>
                      </div>
                      <div className="registry-side"><span className={badgeClass(workflow.risk_level)}>{workflow.risk_level}</span><small>{workflow.enabled ? 'Enabled' : 'Disabled'}</small></div>
                    </article>
                  ))}
                </div>
              </section>

              <section className="panel compact-panel">
                <PanelHeading title="Register workflow" subtitle="Add an n8n webhook to the control plane" icon={Plus} />
                <form className="form-stack" onSubmit={registerWorkflow}>
                  <label>Name<input required value={newWorkflow.name} onChange={(e) => setNewWorkflow({ ...newWorkflow, name: e.target.value })} placeholder="Outbound customer email" /></label>
                  <label>Slug<input required value={newWorkflow.slug} onChange={(e) => setNewWorkflow({ ...newWorkflow, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') })} placeholder="outbound-customer-email" /></label>
                  <label>Webhook URL<input required value={newWorkflow.webhook_url} onChange={(e) => setNewWorkflow({ ...newWorkflow, webhook_url: e.target.value })} /></label>
                  <label>Risk level<select value={newWorkflow.risk_level} onChange={(e) => setNewWorkflow({ ...newWorkflow, risk_level: e.target.value })}><option>low</option><option>medium</option><option>high</option><option>critical</option></select></label>
                  <label>Description<textarea rows={4} value={newWorkflow.description} onChange={(e) => setNewWorkflow({ ...newWorkflow, description: e.target.value })} /></label>
                  <button className="button primary" disabled={busy}><Plus size={16} /> Register workflow</button>
                </form>
              </section>
            </div>
          )}

          {!loading && dashboard && section === 'policies' && (
            <section className="panel">
              <PanelHeading title="Policy stack" subtitle="Highest priority matching policy wins" icon={ShieldCheck} />
              <div className="policy-list">
                {dashboard.policies.map((policy, index) => (
                  <article className="policy-row" key={policy.id}>
                    <div className="policy-priority">{String(index + 1).padStart(2, '0')}</div>
                    <div className="policy-copy"><strong>{policy.name}</strong><span>{policy.risk_levels.length ? `Risk: ${policy.risk_levels.join(', ')}` : 'All risk levels'}{policy.min_cost_usd != null ? ` · cost ≥ $${policy.min_cost_usd.toFixed(2)}` : ''}</span></div>
                    <span className={badgeClass(policy.action)}>{policy.action.replaceAll('_', ' ')}</span>
                    <small>P{policy.priority}</small>
                  </article>
                ))}
              </div>
            </section>
          )}

          {!loading && section === 'audit' && (
            <section className="panel">
              <PanelHeading title="Audit trail" subtitle="Who requested, decided, and executed what" icon={ScrollText} />
              <div className="audit-list">
                {audit.length === 0 && <Empty text="No audit events yet." />}
                {audit.map((event) => (
                  <article className="audit-row" key={event.id}>
                    <div className="audit-dot" />
                    <div className="audit-copy"><strong>{event.event_type}</strong><span>{event.actor} · {event.entity_type} #{shortId(event.entity_id)}</span></div>
                    <time>{when(event.created_at)}</time>
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

function Metric({ icon: Icon, label, value, detail, tone = 'default' }: { icon: typeof Gauge; label: string; value: number; detail: string; tone?: string }) {
  return <article className={`metric metric-${tone}`}><div className="metric-icon"><Icon size={18} /></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>;
}

function PanelHeading({ title, subtitle, icon: Icon }: { title: string; subtitle: string; icon: typeof Gauge }) {
  return <div className="panel-heading"><div className="heading-icon"><Icon size={18} /></div><div><h2>{title}</h2><p>{subtitle}</p></div></div>;
}

function Empty({ text }: { text: string }) {
  return <div className="empty-state"><ShieldCheck size={22} /><span>{text}</span></div>;
}

function ExecutionTable({ executions, workflowMap }: { executions: Execution[]; workflowMap: Map<string, Workflow> }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Execution</th><th>Workflow</th><th>Risk</th><th>Decision</th><th>Status</th><th>Cost</th><th>Requested</th></tr></thead>
        <tbody>
          {executions.map((execution) => (
            <tr key={execution.id}>
              <td><code>#{shortId(execution.id)}</code>{execution.dry_run && <small className="table-note">dry-run</small>}</td>
              <td>{workflowMap.get(execution.workflow_id)?.name || shortId(execution.workflow_id)}</td>
              <td><span className={badgeClass(execution.risk_level)}>{execution.risk_level}</span></td>
              <td><span className={badgeClass(execution.decision)}>{execution.decision.replaceAll('_', ' ')}</span></td>
              <td><span className={badgeClass(execution.status)}>{execution.status.replaceAll('_', ' ')}</span></td>
              <td>${execution.estimated_cost_usd.toFixed(2)}</td>
              <td>{when(execution.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
