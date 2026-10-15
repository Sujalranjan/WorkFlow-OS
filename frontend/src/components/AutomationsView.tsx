import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CanonicalWorkflowSpec } from '../types/canonical';
import { EmailTrigger, RunStatus, WorkflowRun } from '../types/automation';
import {
  approveRun,
  createTrigger,
  deleteTrigger,
  listRuns,
  listTriggers,
  pollTrigger,
  rejectRun,
  resumeRun,
  setTriggerEnabled,
} from '../services/automation';
import './automations.css';

interface AutomationsViewProps {
  specifications: CanonicalWorkflowSpec[];
}

const INBOX_STATUSES: RunStatus[] = ['PENDING_APPROVAL', 'NEEDS_INPUT'];
const REFRESH_MS = 10000;
const OPERATOR_KEY = 'workflowos.operator';

function readOperator(): string {
  try {
    return localStorage.getItem(OPERATOR_KEY) || '';
  } catch {
    return '';
  }
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function describeOutcome(run: WorkflowRun): string {
  const subject = run.source_email.subject || 'the email';
  switch (run.status) {
    case 'COMPLETED':
      return `Run for "${subject}" completed${run.verification_status ? ` (verification: ${run.verification_status})` : ''}.`;
    case 'NEEDS_INPUT':
      return `Run for "${subject}" paused: ${run.intervention?.reason || 'input needed'}`;
    default:
      return `Run for "${subject}" ended as ${run.status}. See run history for details.`;
  }
}

const StatusPill: React.FC<{ status: string }> = ({ status }) => (
  <span className={`auto-pill auto-pill-${status.toLowerCase()}`}>{status.replace(/_/g, ' ')}</span>
);

export const AutomationsView: React.FC<AutomationsViewProps> = ({ specifications }) => {
  const [triggers, setTriggers] = useState<EmailTrigger[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [operator, setOperator] = useState<string>(readOperator);

  const automatable = useMemo(
    () =>
      specifications.filter(
        (s) =>
          s.approval_state?.state === 'approved' &&
          s.steps.some((st) => st.catalog_action === 'gmail.search_email'),
      ),
    [specifications],
  );
  const titleById = useMemo(
    () => Object.fromEntries(specifications.map((s) => [s.workflow_id, s.title])),
    [specifications],
  );

  const refresh = useCallback(async () => {
    try {
      const [t, r] = await Promise.all([listTriggers(), listRuns(undefined, 100)]);
      setTriggers(t);
      setRuns(r);
      setLoadError(null);
    } catch (e) {
      setLoadError(`Cannot reach the WorkFlowOS backend: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const actingAs = operator.trim() || 'operator';
  const updateOperator = (value: string) => {
    setOperator(value);
    try {
      localStorage.setItem(OPERATOR_KEY, value);
    } catch {
      /* storage unavailable: keep in memory only */
    }
  };

  const act = async (key: string, fn: () => Promise<unknown>, success?: string) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      if (success) setNotice(success);
      else if (typeof result === 'string') setNotice(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  const inbox = runs.filter((r) => INBOX_STATUSES.includes(r.status));
  const history = runs.filter((r) => !INBOX_STATUSES.includes(r.status));

  return (
    <div className="auto-root">
      <header className="auto-header">
        <div>
          <h1>Automations</h1>
          <p>
            Email triggers watch Gmail (read-only) for new matching messages. Each one becomes a run that waits for
            your approval; a run pauses and asks you when it cannot decide safely.
          </p>
        </div>
        <label className="auto-operator">
          Acting as
          <input value={operator} placeholder="your name" onChange={(e) => updateOperator(e.target.value)} />
        </label>
      </header>

      {loadError && <div className="auto-banner auto-banner-error">{loadError}</div>}
      {error && <div className="auto-banner auto-banner-error">{error}</div>}
      {notice && <div className="auto-banner auto-banner-ok">{notice}</div>}

      <TriggerForm
        workflows={automatable}
        disabled={busy !== null}
        onCreate={(input) => act('create', () => createTrigger(input), 'Trigger created. It will check Gmail on its interval.')}
      />

      <section className="auto-card">
        <div className="auto-card-head">
          <h2>Email triggers</h2>
          <span className="auto-muted">{triggers.length} configured</span>
        </div>
        {triggers.length === 0 ? (
          <p className="auto-empty">No triggers yet. Create one above for an approved workflow.</p>
        ) : (
          <ul className="auto-list">
            {triggers.map((t) => (
              <li key={t.trigger_id} className="auto-trigger">
                <div className="auto-trigger-main">
                  <div className="auto-trigger-title">
                    <strong>{t.name}</strong>
                    <StatusPill status={t.enabled ? 'ENABLED' : 'PAUSED'} />
                  </div>
                  <code className="auto-query">{t.gmail_query}</code>
                  <div className="auto-muted">
                    {titleById[t.workflow_id] || t.workflow_id} · every {t.poll_interval_seconds}s · last checked{' '}
                    {formatTime(t.last_polled_at)}
                  </div>
                  {t.last_error && <div className="auto-inline-error">{t.last_error}</div>}
                </div>
                <div className="auto-actions">
                  <button
                    disabled={busy !== null}
                    onClick={() =>
                      act(`poll-${t.trigger_id}`, async () => {
                        const res = await pollTrigger(t.trigger_id);
                        if (res.error) throw new Error(res.error);
                        setNotice(`Checked Gmail: ${res.matched} matching, ${res.new_runs.length} new run(s) queued.`);
                      })
                    }
                  >
                    {busy === `poll-${t.trigger_id}` ? 'Checking…' : 'Check now'}
                  </button>
                  <button
                    className="auto-btn-secondary"
                    disabled={busy !== null}
                    onClick={() => act(`toggle-${t.trigger_id}`, () => setTriggerEnabled(t.trigger_id, !t.enabled))}
                  >
                    {t.enabled ? 'Pause' : 'Resume'}
                  </button>
                  <button
                    className="auto-btn-danger"
                    disabled={busy !== null}
                    onClick={() => {
                      if (window.confirm(`Delete trigger "${t.name}"? Existing runs are kept.`)) {
                        act(`delete-${t.trigger_id}`, () => deleteTrigger(t.trigger_id));
                      }
                    }}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="auto-card">
        <div className="auto-card-head">
          <h2>Inbox</h2>
          <span className="auto-muted">{inbox.length} waiting on you</span>
        </div>
        {inbox.length === 0 ? (
          <p className="auto-empty">Nothing needs your attention.</p>
        ) : (
          <ul className="auto-list">
            {inbox.map((run) => (
              <InboxItem
                key={run.run_id}
                run={run}
                workflowTitle={titleById[run.workflow_id] || run.workflow_id}
                busy={busy}
                onApprove={() =>
                  act(`approve-${run.run_id}`, async () => describeOutcome(await approveRun(run.run_id, actingAs)))
                }
                onReject={() => act(`reject-${run.run_id}`, () => rejectRun(run.run_id, actingAs), 'Run rejected.')}
                onResume={(inputs) =>
                  act(`resume-${run.run_id}`, async () => describeOutcome(await resumeRun(run.run_id, inputs, actingAs)))
                }
              />
            ))}
          </ul>
        )}
      </section>

      <section className="auto-card">
        <div className="auto-card-head">
          <h2>Run history</h2>
          <button className="auto-btn-secondary" onClick={refresh} disabled={busy !== null}>
            Refresh
          </button>
        </div>
        {history.length === 0 ? (
          <p className="auto-empty">No finished runs yet.</p>
        ) : (
          <div className="auto-table-wrap">
            <table className="auto-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Email</th>
                  <th>Workflow</th>
                  <th>Verification</th>
                  <th>Decided by</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {history.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <StatusPill status={run.status} />
                    </td>
                    <td>
                      <div className="auto-cell-strong">{run.source_email.subject || '(no subject)'}</div>
                      <div className="auto-muted">{run.source_email.sender}</div>
                      {run.error && <div className="auto-inline-error">{run.error}</div>}
                    </td>
                    <td>{titleById[run.workflow_id] || run.workflow_id}</td>
                    <td>{run.verification_status ? <StatusPill status={run.verification_status} /> : '—'}</td>
                    <td>{run.decided_by || '—'}</td>
                    <td className="auto-muted">{formatTime(run.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};

interface TriggerFormProps {
  workflows: CanonicalWorkflowSpec[];
  disabled: boolean;
  onCreate: (input: {
    workflow_id: string;
    gmail_query: string;
    name?: string;
    poll_interval_seconds: number;
    include_existing_since?: number;
  }) => void;
}

const TriggerForm: React.FC<TriggerFormProps> = ({ workflows, disabled, onCreate }) => {
  const [workflowId, setWorkflowId] = useState('');
  const [query, setQuery] = useState('');
  const [name, setName] = useState('');
  const [interval, setIntervalSeconds] = useState(60);
  const [lookbackHours, setLookbackHours] = useState(0);

  useEffect(() => {
    if (!workflowId && workflows.length > 0) setWorkflowId(workflows[0].workflow_id);
  }, [workflows, workflowId]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!workflowId || !query.trim()) return;
    onCreate({
      workflow_id: workflowId,
      gmail_query: query.trim(),
      name: name.trim() || undefined,
      poll_interval_seconds: Math.max(30, interval),
      include_existing_since:
        lookbackHours > 0 ? Math.floor(Date.now() / 1000) - lookbackHours * 3600 : undefined,
    });
    setQuery('');
    setName('');
  };

  return (
    <section className="auto-card">
      <div className="auto-card-head">
        <h2>New email trigger</h2>
      </div>
      {workflows.length === 0 ? (
        <p className="auto-empty">
          No approved workflow starts with a Gmail search yet. Approve one in the Pipeline view first.
        </p>
      ) : (
        <form className="auto-form" onSubmit={submit}>
          <label>
            Workflow
            <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
              {workflows.map((w) => (
                <option key={w.workflow_id} value={w.workflow_id}>
                  {w.title} ({w.workflow_id})
                </option>
              ))}
            </select>
          </label>
          <label className="auto-form-wide">
            Gmail query
            <input
              value={query}
              required
              placeholder='subject:"Customer Replacement Request" has:attachment'
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label>
            Name (optional)
            <input value={name} placeholder="Replacement requests" onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Check every (seconds)
            <input
              type="number"
              min={30}
              value={interval}
              onChange={(e) => setIntervalSeconds(Number(e.target.value) || 30)}
            />
          </label>
          <label>
            Also include emails from the last
            <select value={lookbackHours} onChange={(e) => setLookbackHours(Number(e.target.value))}>
              <option value={0}>Only new emails</option>
              <option value={1}>1 hour</option>
              <option value={24}>24 hours</option>
              <option value={168}>7 days</option>
            </select>
          </label>
          <div className="auto-form-submit">
            <button type="submit" disabled={disabled || !query.trim()}>
              Create trigger
            </button>
          </div>
        </form>
      )}
    </section>
  );
};

interface InboxItemProps {
  run: WorkflowRun;
  workflowTitle: string;
  busy: string | null;
  onApprove: () => void;
  onReject: () => void;
  onResume: (inputs: Record<string, string>) => void;
}

const InboxItem: React.FC<InboxItemProps> = ({ run, workflowTitle, busy, onApprove, onReject, onResume }) => {
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const email = run.source_email;
  const intervention = run.intervention;
  const candidates = intervention?.candidates || [];
  const isBusy = busy !== null;

  return (
    <li className={`auto-run auto-run-${run.status.toLowerCase()}`}>
      <div className="auto-run-head">
        <StatusPill status={run.status} />
        <span className="auto-muted">
          {workflowTitle} · received {formatTime(email.received_at)}
        </span>
      </div>
      <div className="auto-email">
        <div className="auto-cell-strong">{email.subject || '(no subject)'}</div>
        <div className="auto-muted">From {email.sender}</div>
        {email.snippet && <p className="auto-snippet">{email.snippet}</p>}
        {email.attachment_names.length > 0 && (
          <div className="auto-muted">📎 {email.attachment_names.join(', ')}</div>
        )}
      </div>

      {run.status === 'PENDING_APPROVAL' && (
        <div className="auto-actions">
          <button disabled={isBusy} onClick={onApprove}>
            {busy === `approve-${run.run_id}` ? 'Running…' : 'Approve & run'}
          </button>
          <button className="auto-btn-secondary" disabled={isBusy} onClick={onReject}>
            Reject
          </button>
        </div>
      )}

      {run.status === 'NEEDS_INPUT' && (
        <div className="auto-intervention">
          <div className="auto-intervention-reason">
            <strong>Paused at {intervention?.step || 'a step'}:</strong> {intervention?.reason}
          </div>
          {candidates.length > 0 && (
            <div className="auto-candidates" role="radiogroup" aria-label="Matching customers">
              {candidates.map((c) => (
                <label key={c.customer_id} className="auto-candidate">
                  <input
                    type="radio"
                    name={`cand-${run.run_id}`}
                    value={c.customer_id}
                    checked={selected === c.customer_id}
                    onChange={() => {
                      setSelected(c.customer_id);
                      setSearch('');
                    }}
                  />
                  <span>
                    <span className="auto-cell-strong">{c.name || c.customer_id}</span>{' '}
                    <span className="auto-muted">
                      {c.email} · {c.company} · {c.customer_id}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
          <div className="auto-resume-row">
            <input
              value={search}
              placeholder={candidates.length ? 'or enter a customer id' : 'Customer id (e.g. cust-001)'}
              onChange={(e) => {
                setSearch(e.target.value);
                setSelected('');
              }}
            />
            <button
              disabled={isBusy || !(selected || search.trim())}
              onClick={() => onResume({ selected_customer_id: selected || search.trim() })}
            >
              {busy === `resume-${run.run_id}` ? 'Resuming…' : 'Continue run'}
            </button>
            <button className="auto-btn-secondary" disabled={isBusy} onClick={onReject}>
              Cancel run
            </button>
          </div>
        </div>
      )}
    </li>
  );
};
