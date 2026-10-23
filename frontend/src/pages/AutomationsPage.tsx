import React, { useEffect, useState } from 'react';
import {
  createTrigger,
  deleteTrigger,
  listRuns,
  listTriggers,
  listWorkflows,
  pollTrigger,
  setTriggerEnabled,
} from '../api';
import { CanonicalWorkflowSpec } from '../types/canonical';
import { Alert, Badge, CAN, Empty, Loading, PageHeader, href, timeAgo, useAction, useLoad, useRoute, useSession } from '../ui';

export const AutomationsPage: React.FC = () => {
  const [, preselect] = useRoute();
  const data = useLoad(async () => {
    const [triggers, workflows, runs] = await Promise.all([listTriggers(), listWorkflows(), listRuns(undefined, 200)]);
    return { triggers, workflows, runs };
  }, [], 20000);
  const action = useAction();
  const canManage = useSession().can(CAN.manageTriggers);

  const automatable = (data.data?.workflows || []).filter(
    (w) => w.approval_state.state === 'approved' && w.steps.some((s) => s.catalog_action === 'gmail.search_email'),
  );
  const title = (id: string) => data.data?.workflows.find((w) => w.workflow_id === id)?.title || 'Workflow';

  const after = async <T,>(p: Promise<T | undefined>) => {
    await p;
    data.reload();
  };

  return (
    <>
      <PageHeader
        title="Automations"
        subtitle="Start an approved workflow whenever a matching email arrives. WorkFlowOS checks Gmail (read-only) on a schedule and puts each new email in your Inbox for approval."
      />
      {data.error && <Alert>{data.error}</Alert>}
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}

      {!canManage && <Alert tone="info">Only admins can create or change email triggers.</Alert>}

      {canManage && <NewTrigger
        workflows={automatable}
        preselect={preselect}
        busy={action.busy !== null}
        onCreate={(input) =>
          after(action.run('create', () => createTrigger(input), 'Saved. New matching emails will show up in your Inbox.'))
        }
      />}

      <section className="card">
        <h2>Email triggers</h2>
        {data.loading && !data.data ? (
          <Loading />
        ) : !data.data?.triggers.length ? (
          <Empty title="No email triggers yet." />
        ) : (
          <ul className="rows">
            {data.data.triggers.map((t) => {
              const runs = data.data!.runs.filter((r) => r.trigger_id === t.trigger_id);
              return (
                <li key={t.trigger_id} className="trigger">
                  <div className="trigger-main">
                    <div className="row-title">
                      {t.name} <Badge status={t.enabled ? 'enabled' : 'paused'} />
                    </div>
                    <code className="query">{t.gmail_query}</code>
                    {isBroadQuery(t.gmail_query) && (
                      <div className="warn-text small">
                        Too broad: this matches unrelated emails. Delete it and create one with a sender or subject.
                      </div>
                    )}
                    <div className="muted small">
                      Runs <a href={href('workflows', t.workflow_id)}>{title(t.workflow_id)}</a> · checks every{' '}
                      {t.poll_interval_seconds}s · last checked {timeAgo(t.last_polled_at)} · {runs.length} email
                      {runs.length === 1 ? '' : 's'} so far
                    </div>
                    {t.last_error && <div className="error-text small">{t.last_error}</div>}
                  </div>
                  {canManage && <div className="actions">
                    <button
                      className="btn-secondary"
                      disabled={action.busy !== null}
                      onClick={() =>
                        after(
                          action.run(`poll-${t.trigger_id}`, async () => {
                            const r = await pollTrigger(t.trigger_id);
                            if (r.error) throw new Error(r.error);
                            return r;
                          }, (r) =>
                            r.new_runs.length
                              ? `${r.new_runs.length} new email${r.new_runs.length === 1 ? '' : 's'} added to your Inbox.`
                              : 'No new matching emails.',
                          ),
                        )
                      }
                    >
                      {action.busy === `poll-${t.trigger_id}` ? 'Checking…' : 'Check now'}
                    </button>
                    <button
                      className="btn-secondary"
                      disabled={action.busy !== null}
                      onClick={() => after(action.run(`toggle-${t.trigger_id}`, () => setTriggerEnabled(t.trigger_id, !t.enabled)))}
                    >
                      {t.enabled ? 'Pause' : 'Turn on'}
                    </button>
                    <button
                      className="btn-danger"
                      disabled={action.busy !== null}
                      onClick={() => {
                        if (window.confirm(`Delete "${t.name}"? Past runs are kept.`)) {
                          after(action.run(`delete-${t.trigger_id}`, () => deleteTrigger(t.trigger_id)));
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {data.data && data.data.runs.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h2>Emails handled</h2>
            <a href={href('inbox')}>Inbox →</a>
          </div>
          <ul className="rows">
            {data.data.runs.slice(0, 20).map((r) => {
              const inner = (
                <>
                  <span className="row-main">
                    <span className="row-title">{r.source_email.subject || '(no subject)'}</span>
                    <span className="muted small">
                      {r.source_email.sender} · {timeAgo(r.updated_at)}
                      {r.decided_by ? ` · by ${r.decided_by}` : ''}
                    </span>
                    {r.error && <span className="error-text small">{r.error}</span>}
                  </span>
                  <span className="row-meta">
                    <Badge status={r.status} />
                    {r.verification_status && <Badge status={r.verification_status} />}
                  </span>
                </>
              );
              return (
                <li key={r.run_id}>
                  {r.execution_id ? (
                    <a className="row-link" href={href('runs', r.execution_id)}>
                      {inner}
                    </a>
                  ) : (
                    <div className="row-link">{inner}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
};

/** True when the query has nothing that narrows it to one kind of email (sender, subject, label…). */
export function isBroadQuery(query: string): boolean {
  const q = query.toLowerCase();
  return !/(^|\s)-?(from|subject|label|to|cc|list|deliveredto|filename):\S/.test(q) && !/"[^"]+"/.test(q);
}

const NewTrigger: React.FC<{
  workflows: CanonicalWorkflowSpec[];
  preselect?: string;
  busy: boolean;
  onCreate: (input: {
    workflow_id: string;
    gmail_query: string;
    name?: string;
    poll_interval_seconds: number;
    include_existing_since?: number;
  }) => void;
}> = ({ workflows, preselect, busy, onCreate }) => {
  const [workflowId, setWorkflowId] = useState('');
  const [query, setQuery] = useState('');
  const [name, setName] = useState('');
  const [interval, setIntervalSeconds] = useState(60);
  const [lookback, setLookback] = useState(0);

  useEffect(() => {
    if (workflowId || workflows.length === 0) return;
    const wanted = workflows.find((w) => w.workflow_id === preselect);
    setWorkflowId((wanted || workflows[0]).workflow_id);
  }, [workflows, preselect, workflowId]);

  if (workflows.length === 0) {
    return (
      <section className="card">
        <h2>New email trigger</h2>
        <Empty title="No workflow can be started by email yet.">
          Approve a workflow that begins by finding an email on the <a href={href('workflows')}>Workflows</a> page.
        </Empty>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>New email trigger</h2>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!workflowId || !query.trim()) return;
          if (
            isBroadQuery(query) &&
            !window.confirm(
              'This search will match many unrelated emails (receipts, newsletters…), and each one lands in your Inbox. Save it anyway?',
            )
          ) {
            return;
          }
          onCreate({
            workflow_id: workflowId,
            gmail_query: query.trim(),
            name: name.trim() || undefined,
            poll_interval_seconds: Math.max(30, interval),
            include_existing_since: lookback ? Math.floor(Date.now() / 1000) - lookback * 3600 : undefined,
          });
          setQuery('');
          setName('');
        }}
      >
        <label className="field">
          When an email matches
          <input
            required
            value={query}
            placeholder='subject:"Customer Replacement Request" has:attachment'
            onChange={(e) => setQuery(e.target.value)}
          />
          {query.trim() && isBroadQuery(query) ? (
            <span className="warn-text small">
              Too broad: add a sender or subject, e.g. <code>from:orders@acme.com</code> or{' '}
              <code>subject:"Replacement Request"</code>, so only real requests are picked up.
            </span>
          ) : (
            <span className="muted small">Any Gmail search works, e.g. from:, subject:, has:attachment, label:.</span>
          )}
        </label>
        <label className="field">
          Run this workflow
          <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
            {workflows.map((w) => (
              <option key={w.workflow_id} value={w.workflow_id}>
                {w.title}
              </option>
            ))}
          </select>
        </label>
        <div className="form-row">
          <label className="field">
            Name (optional)
            <input value={name} placeholder="Replacement requests" onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            Check every
            <select value={interval} onChange={(e) => setIntervalSeconds(Number(e.target.value))}>
              <option value={30}>30 seconds</option>
              <option value={60}>1 minute</option>
              <option value={300}>5 minutes</option>
              <option value={900}>15 minutes</option>
            </select>
          </label>
          <label className="field">
            Include emails already received
            <select value={lookback} onChange={(e) => setLookback(Number(e.target.value))}>
              <option value={0}>No, only new ones</option>
              <option value={1}>From the last hour</option>
              <option value={24}>From the last day</option>
              <option value={168}>From the last week</option>
            </select>
          </label>
        </div>
        <div className="actions">
          <button type="submit" disabled={busy || !query.trim()}>
            Save trigger
          </button>
        </div>
      </form>
    </section>
  );
};
