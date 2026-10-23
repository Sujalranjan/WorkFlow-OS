import React from 'react';
import { getStatus, listEvents, listExecutions, listTriggers, listWorkflows } from '../api';
import { Alert, Badge, PageHeader, href, timeAgo, useLoad } from '../ui';

interface Props {
  inboxCount: number;
}

const INTEGRATIONS: { key: 'gmail' | 'crm' | 'slack' | 'ai'; name: string; role: string }[] = [
  { key: 'gmail', name: 'Gmail', role: 'Reads request emails and attachments' },
  { key: 'crm', name: 'CRM', role: 'Looks up and updates customers' },
  { key: 'slack', name: 'Slack', role: 'Notifies your team' },
  { key: 'ai', name: 'AI interpreter', role: 'Describes discovered routines' },
];

export const OverviewPage: React.FC<Props> = ({ inboxCount }) => {
  const status = useLoad(getStatus, [], 30000);
  const summary = useLoad(
    async () => {
      const [events, workflows, triggers, executions] = await Promise.all([
        listEvents(500),
        listWorkflows(),
        listTriggers(),
        listExecutions(undefined, 20),
      ]);
      return { events, workflows, triggers, executions };
    },
    [],
    30000,
  );

  const s = summary.data;
  const approved = s?.workflows.filter((w) => w.approval_state.state === 'approved') || [];
  const toReview = s?.workflows.filter((w) => w.approval_state.state === 'requires_review') || [];
  const liveRuns = s?.executions.filter((e) => e.execution_mode === 'LIVE') || [];

  const steps = [
    {
      done: (s?.events.length || 0) > 0,
      title: 'Record your routine',
      body: (
        <>
          Run the desktop agent and browser extension, then do your usual task a few times. No setup yet? Load sample
          activity on the <a href={href('activity')}>Activity</a> page.
        </>
      ),
    },
    {
      done: (s?.workflows.length || 0) > 0,
      title: 'Turn a repeated routine into a workflow',
      body: (
        <>
          WorkFlowOS finds routines you repeat. Pick one on the <a href={href('activity')}>Activity</a> page and
          create a workflow from it.
        </>
      ),
    },
    {
      done: approved.length > 0,
      title: 'Review and approve it',
      body: (
        <>
          Check each step and what it changes, then approve it on the <a href={href('workflows')}>Workflows</a> page.
          Nothing runs before you approve.
        </>
      ),
    },
    {
      done: (s?.triggers.length || 0) > 0,
      title: 'Let new emails start it',
      body: (
        <>
          Add an email trigger on the <a href={href('automations')}>Automations</a> page. Each new matching email lands
          in your Inbox for approval.
        </>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="WorkFlowOS learns the routines you repeat across apps and runs them for you, with your approval."
      />
      {summary.error && <Alert>{summary.error}</Alert>}

      {inboxCount > 0 && (
        <a className="callout" href={href('inbox')}>
          <strong>{inboxCount} item{inboxCount === 1 ? '' : 's'} waiting for you</strong>
          <span>Review in Inbox →</span>
        </a>
      )}

      <div className="stats">
        <Stat label="Activity recorded" value={s?.events.length} hint="most recent 500" />
        <Stat label="Workflows to review" value={toReview.length} link={href('workflows')} />
        <Stat label="Approved workflows" value={approved.length} link={href('workflows')} />
        <Stat label="Email triggers" value={s?.triggers.filter((t) => t.enabled).length} link={href('automations')} />
      </div>

      <div className="grid-2">
        <section className="card">
          <h2>Getting started</h2>
          <ol className="checklist">
            {steps.map((step) => (
              <li key={step.title} className={step.done ? 'check-done' : ''}>
                <span className="check-mark" aria-hidden="true">
                  {step.done ? '✓' : ''}
                </span>
                <div>
                  <div className="check-title">
                    {step.title}
                    {step.done && <span className="sr-only"> (done)</span>}
                  </div>
                  {!step.done && <p className="muted">{step.body}</p>}
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="card">
          <h2>Connections</h2>
          {status.error && <Alert>{status.error}</Alert>}
          <ul className="integrations">
            {INTEGRATIONS.map((i) => {
              const st = status.data?.[i.key];
              return (
                <li key={i.key}>
                  <span className={`dot ${st ? (st.connected ? 'dot-on' : 'dot-off') : ''}`} aria-hidden="true" />
                  <div>
                    <div className="integration-name">
                      {i.name}{' '}
                      <span className="muted">
                        {st
                          ? st.connected
                            ? 'connected'
                            : i.key === 'ai'
                              ? 'offline mode'
                              : 'not connected'
                          : status.loading
                            ? 'checking…'
                            : ''}
                      </span>
                    </div>
                    <div className="muted small">{st?.detail || i.role}</div>
                  </div>
                </li>
              );
            })}
          </ul>
          {status.data && !status.data.email_polling && (
            <p className="muted small">Email triggers are paused on this server (TRIGGER_POLLER_ENABLED=false).</p>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Recent runs</h2>
          <a href={href('runs')}>All runs →</a>
        </div>
        {liveRuns.length === 0 ? (
          <p className="muted">No workflow has run yet.</p>
        ) : (
          <ul className="rows">
            {liveRuns.slice(0, 5).map((e) => {
              const wf = s?.workflows.find((w) => w.workflow_id === e.workflow_id);
              return (
                <li key={e.execution_id}>
                  <a className="row-link" href={href('runs', e.execution_id)}>
                    <span className="row-main">{wf?.title || e.workflow_id}</span>
                    <span className="row-meta">
                      <Badge status={e.status} />
                      {e.verification_status && <Badge status={e.verification_status} />}
                      <span className="muted small">{timeAgo(e.start_time)}</span>
                    </span>
                  </a>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );
};

const Stat: React.FC<{ label: string; value?: number; hint?: string; link?: string }> = ({ label, value, hint, link }) => {
  const body = (
    <>
      <span className="stat-value">{value ?? '–'}</span>
      <span className="stat-label">{label}</span>
      {hint && <span className="muted small">{hint}</span>}
    </>
  );
  return link ? (
    <a className="stat" href={link}>
      {body}
    </a>
  ) : (
    <div className="stat">{body}</div>
  );
};
