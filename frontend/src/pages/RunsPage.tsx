import React from 'react';
import { getVerification, listExecutions, listWorkflows, verifyExecution } from '../api';
import { RunSteps } from '../components/RunSteps';
import { Alert, Badge, Empty, Loading, PageHeader, formatTime, href, timeAgo, useAction, useLoad } from '../ui';

export const RunsPage: React.FC<{ executionId?: string }> = ({ executionId }) =>
  executionId ? <RunDetail executionId={executionId} /> : <RunList />;

const RunList: React.FC = () => {
  const data = useLoad(async () => {
    const [runs, workflows] = await Promise.all([listExecutions(undefined, 200), listWorkflows()]);
    return { runs, titles: Object.fromEntries(workflows.map((w) => [w.workflow_id, w.title])) };
  }, [], 20000);

  return (
    <>
      <PageHeader title="Runs" subtitle="Every time a workflow ran, what each step did, and whether the result was checked afterwards." />
      {data.error && <Alert>{data.error}</Alert>}
      <section className="card">
        {data.loading && !data.data ? (
          <Loading />
        ) : !data.data?.runs.length ? (
          <Empty title="No runs yet.">Approve a workflow and run it, or approve an email from your Inbox.</Empty>
        ) : (
          <ul className="rows">
            {data.data.runs.map((r) => (
              <li key={r.execution_id}>
                <a className="row-link" href={href('runs', r.execution_id)}>
                  <span className="row-main">
                    <span className="row-title">{data.data!.titles[r.workflow_id] || r.workflow_id}</span>
                    <span className="muted small">
                      {timeAgo(r.start_time)}
                      {r.execution_mode === 'DRY_RUN' ? ' · test run' : ''}
                      {r.idempotency_key?.startsWith('workflow-run:') ? ' · started by email' : ''}
                    </span>
                  </span>
                  <span className="row-meta">
                    <Badge status={r.status} />
                    {r.verification_status && <Badge status={r.verification_status} />}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
};

const RunDetail: React.FC<{ executionId: string }> = ({ executionId }) => {
  const data = useLoad(async () => {
    const [runs, workflows] = await Promise.all([listExecutions(undefined, 200), listWorkflows()]);
    const record = runs.find((r) => r.execution_id === executionId) || null;
    const verification = record ? await getVerification(executionId).catch(() => null) : null;
    const workflow = record ? workflows.find((w) => w.workflow_id === record.workflow_id) : undefined;
    return { record, verification, workflow };
  }, [executionId]);
  const action = useAction();

  const back = (
    <a href={href('runs')} className="back">
      ← Runs
    </a>
  );
  if (data.loading && !data.data) return <Loading />;
  if (data.error || !data.data?.record) {
    return (
      <>
        {back}
        <Alert>{data.error || 'Run not found.'}</Alert>
      </>
    );
  }
  const { record, verification, workflow } = data.data;

  return (
    <>
      {back}
      <PageHeader
        title={workflow?.title || record.workflow_id}
        subtitle={`Started ${formatTime(record.start_time)}${record.end_time ? ` · finished ${formatTime(record.end_time)}` : ''}`}
        actions={
          <>
            <Badge status={record.status} />
            {verification && <Badge status={verification.overall_status} />}
          </>
        }
      />
      {action.error && <Alert>{action.error}</Alert>}
      {record.status === 'NEEDS_INPUT' && (
        <Alert tone="info">
          This run is waiting for your answer in the <a href={href('inbox')}>Inbox</a>.
        </Alert>
      )}
      {record.error_summary && record.status !== 'NEEDS_INPUT' && <Alert>{record.error_summary}</Alert>}

      <section className="card">
        <div className="card-head">
          <h2>Steps</h2>
          {record.status === 'COMPLETED' && (
            <button
              className="btn-secondary"
              disabled={action.busy !== null}
              onClick={() => action.run('verify', () => verifyExecution(record.execution_id)).then(() => data.reload())}
            >
              {action.busy === 'verify' ? 'Checking…' : verification ? 'Check again' : 'Check results'}
            </button>
          )}
        </div>
        <RunSteps record={record} verification={verification} />
        {verification && (
          <p className="muted small">
            After the run, WorkFlowOS re-read each system independently: {verification.verified_count} confirmed,{' '}
            {verification.failed_count} failed, {verification.unknown_count} could not be checked.
          </p>
        )}
      </section>

      <details className="card details">
        <summary>Technical details</summary>
        <dl className="kv-grid small">
          <dt>Run id</dt>
          <dd>
            <code>{record.execution_id}</code>
          </dd>
          <dt>Workflow</dt>
          <dd>
            <a href={href('workflows', record.workflow_id)}>
              <code>{record.workflow_id}</code>
            </a>
          </dd>
          <dt>Approved by</dt>
          <dd>{record.approved_by || '—'}</dd>
          <dt>Changed</dt>
          <dd>{record.affected_resources.length ? record.affected_resources.join(', ') : 'nothing'}</dd>
        </dl>
      </details>
    </>
  );
};
