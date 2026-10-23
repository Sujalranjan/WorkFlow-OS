import React, { useContext, useState } from 'react';
import { approveRun, listRuns, listWorkflows, rejectRun, resumeRun } from '../api';
import { WorkflowRun } from '../types/automation';
import { Alert, Badge, Empty, Loading, OperatorContext, PageHeader, formatTime, href, useAction, useLoad } from '../ui';

function outcome(run: WorkflowRun): string {
  const subject = run.source_email.subject || 'the email';
  if (run.status === 'COMPLETED') {
    return `“${subject}” processed${run.verification_status === 'VERIFIED' ? ' and verified' : ''}.`;
  }
  if (run.status === 'NEEDS_INPUT') return `“${subject}” paused: ${run.intervention?.reason || 'input needed'}`;
  const ended: Record<string, string> = { BLOCKED: 'stopped', FAILED: 'failed', REJECTED: 'dismissed' };
  const word = ended[run.status] || run.status.toLowerCase().replace(/_/g, ' ');
  return run.status === 'REJECTED'
    ? `“${subject}” dismissed.`
    : `“${subject}” ${word}${run.error ? `: ${run.error}` : '.'} See Runs for details.`;
}

export const InboxPage: React.FC<{ onChange: () => void }> = ({ onChange }) => {
  const data = useLoad(async () => {
    const [runs, workflows] = await Promise.all([listRuns(['PENDING_APPROVAL', 'NEEDS_INPUT'], 200), listWorkflows()]);
    return { runs, titles: Object.fromEntries(workflows.map((w) => [w.workflow_id, w.title])) };
  }, [], 10000);
  const operator = useContext(OperatorContext);
  const action = useAction();

  const act = async (key: string, fn: () => Promise<WorkflowRun>) => {
    await action.run(key, fn, outcome);
    data.reload();
    onChange();
  };

  return (
    <>
      <PageHeader
        title="Inbox"
        subtitle="New emails that matched an automation, and runs that stopped to ask you something. Nothing runs until you approve it."
      />
      {data.error && <Alert>{data.error}</Alert>}
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}

      {data.loading && !data.data ? (
        <Loading />
      ) : !data.data?.runs.length ? (
        <section className="card">
          <Empty title="You're all caught up.">
            New matching emails appear here once an <a href={href('automations')}>email trigger</a> is set up.
          </Empty>
        </section>
      ) : (
        <ul className="inbox">
          {data.data.runs.map((run) => (
            <InboxItem
              key={run.run_id}
              run={run}
              workflowTitle={data.data!.titles[run.workflow_id] || 'Workflow'}
              busy={action.busy}
              onApprove={() => act(`approve-${run.run_id}`, () => approveRun(run.run_id, operator))}
              onReject={() => act(`reject-${run.run_id}`, () => rejectRun(run.run_id, operator))}
              onResume={(inputs) => act(`resume-${run.run_id}`, () => resumeRun(run.run_id, inputs, operator))}
            />
          ))}
        </ul>
      )}
    </>
  );
};

const InboxItem: React.FC<{
  run: WorkflowRun;
  workflowTitle: string;
  busy: string | null;
  onApprove: () => void;
  onReject: () => void;
  onResume: (inputs: Record<string, string>) => void;
}> = ({ run, workflowTitle, busy, onApprove, onReject, onResume }) => {
  const [selected, setSelected] = useState('');
  const [typed, setTyped] = useState('');
  const email = run.source_email;
  const candidates = run.intervention?.candidates || [];
  // A picked candidate is looked up by its exact id; typed text searches the CRM by name, email or id.
  const inputs: Record<string, string> | null = selected
    ? { selected_customer_id: selected }
    : typed.trim()
      ? { customer_query: typed.trim() }
      : null;

  return (
    <li className={`card inbox-item${run.status === 'NEEDS_INPUT' ? ' inbox-item-attention' : ''}`}>
      <div className="inbox-head">
        <Badge status={run.status} />
        <span className="muted small">
          {workflowTitle} · {formatTime(email.received_at || run.created_at)}
        </span>
      </div>
      <h3 className="inbox-subject">{email.subject || '(no subject)'}</h3>
      <div className="muted small">From {email.sender}</div>
      {email.snippet && <p className="snippet">{email.snippet}</p>}
      {email.attachment_names.length > 0 && <div className="muted small">Attachments: {email.attachment_names.join(', ')}</div>}

      {run.status === 'PENDING_APPROVAL' && (
        <div className="actions">
          <button disabled={busy !== null} onClick={onApprove}>
            {busy === `approve-${run.run_id}` ? 'Running…' : 'Approve and run'}
          </button>
          <button className="btn-secondary" disabled={busy !== null} onClick={onReject}>
            Dismiss
          </button>
        </div>
      )}

      {run.status === 'NEEDS_INPUT' && (
        <div className="question">
          <p className="question-text">{run.intervention?.reason || 'This run needs your input to continue.'}</p>
          {candidates.length > 0 && (
            <div className="choices" role="radiogroup" aria-label="Which customer is this?">
              {candidates.map((c) => (
                <label key={c.customer_id} className="choice">
                  <input
                    type="radio"
                    name={`customer-${run.run_id}`}
                    checked={selected === c.customer_id}
                    onChange={() => {
                      setSelected(c.customer_id);
                      setTyped('');
                    }}
                  />
                  <span>
                    <strong>{c.name || c.customer_id}</strong>{' '}
                    <span className="muted small">
                      {[c.email, c.company, c.customer_id].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
          <div className="inline-form">
            <input
              value={typed}
              aria-label="Search the CRM"
              placeholder={candidates.length ? 'or search by name, email or id' : 'Search the CRM by name, email or id'}
              onChange={(e) => {
                setTyped(e.target.value);
                setSelected('');
              }}
            />
            <button disabled={busy !== null || !inputs} onClick={() => inputs && onResume(inputs)}>
              {busy === `resume-${run.run_id}` ? 'Checking…' : selected ? 'Use this customer' : 'Search and continue'}
            </button>
            <button className="btn-secondary" disabled={busy !== null} onClick={onReject}>
              Cancel run
            </button>
          </div>
        </div>
      )}
    </li>
  );
};
