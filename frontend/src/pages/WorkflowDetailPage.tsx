import React, { useContext, useState } from 'react';
import {
  approveWorkflow,
  dryRunPlan,
  executePlan,
  getReliability,
  getWorkflow,
  listExecutions,
  planWorkflow,
  rejectWorkflow,
  verifyExecution,
} from '../api';
import { RunSteps } from '../components/RunSteps';
import { CanonicalWorkflowSpec } from '../types/canonical';
import { DryRunResult, ExecutionAuditRecord, ExecutionPlan, VerificationResult } from '../types/execution';
import {
  Alert,
  Badge,
  Loading,
  OperatorContext,
  PageHeader,
  actionLabel,
  formatTime,
  href,
  pct,
  riskLabel,
  riskTone,
  useAction,
  useLoad,
} from '../ui';

export const WorkflowDetailPage: React.FC<{ workflowId: string }> = ({ workflowId }) => {
  const wf = useLoad(() => getWorkflow(workflowId), [workflowId]);
  const operator = useContext(OperatorContext);
  const action = useAction();

  if (wf.loading && !wf.data) return <Loading />;
  if (wf.error || !wf.data) {
    return (
      <>
        <a href={href('workflows')} className="back">
          ← Workflows
        </a>
        <Alert>{wf.error || 'Workflow not found.'}</Alert>
      </>
    );
  }

  const spec = wf.data;
  const state = spec.approval_state.state;
  const executable = spec.steps.filter((s) => s.catalog_action);
  const steps = executable.length ? executable : spec.steps;
  const context = executable.length ? spec.steps.filter((s) => !s.catalog_action) : [];

  return (
    <>
      <a href={href('workflows')} className="back">
        ← Workflows
      </a>
      <PageHeader
        title={spec.title}
        subtitle={spec.description || spec.intent}
        actions={<Badge status={state} />}
      />
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}

      {(state === 'requires_review' || state === 'draft') && (
        <ReviewPanel
          busy={action.busy}
          onApprove={() =>
            action.run('approve', () => approveWorkflow(spec.workflow_id, operator), 'Approved. You can now run it.').then(
              () => wf.reload(),
            )
          }
          onReject={(reason) =>
            action.run('reject', () => rejectWorkflow(spec.workflow_id, operator, reason), 'Rejected.').then(() =>
              wf.reload(),
            )
          }
        />
      )}
      {state === 'approved' && (
        <p className="muted small">
          Approved by {spec.approval_state.reviewed_by || 'unknown'} · {formatTime(spec.approval_state.reviewed_at)}
        </p>
      )}
      {state === 'rejected' && (
        <Alert tone="info">
          Rejected by {spec.approval_state.reviewed_by || 'unknown'}
          {spec.approval_state.rejection_reason ? `: ${spec.approval_state.rejection_reason}` : '.'} It cannot run.
        </Alert>
      )}

      <section className="card">
        <h2>What it does</h2>
        <ol className="plan-steps">
          {steps.map((s, i) => (
            <li key={s.canonical_step_id}>
              <span className="run-step-num">{i + 1}</span>
              <div>
                <div className="run-step-title">{actionLabel(s.action, s.application)}</div>
                <div className="muted small">{s.description}</div>
              </div>
              <span className={`badge badge-${riskTone(s.risk.risk_level)}`}>
                {riskLabel(s.risk.risk_category, s.application, s.risk.requires_confirmation)}
              </span>
            </li>
          ))}
        </ol>
        {context.length > 0 && (
          <details className="details">
            <summary>
              {context.length} other observed step{context.length === 1 ? '' : 's'} (not automated)
            </summary>
            <ul className="muted small">
              {context.map((s) => (
                <li key={s.canonical_step_id}>
                  {s.application}: {s.description}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {spec.variables.length > 0 && (
        <section className="card">
          <h2>Inputs</h2>
          <p className="muted small">
            Values this workflow works with, as seen in your recordings. Ones that differed between sessions (like the
            customer) are filled in at run time from earlier steps, such as the email's sender, and never copied from a
            past run.
          </p>
          <ul className="kv">
            {spec.variables.map((v) => (
              <li key={v.binding_id}>
                <span>{v.semantic_name.replace(/_/g, ' ')}</span>
                <span className="muted small">seen: {Array.from(new Set(v.observed_values)).slice(0, 3).join(', ') || '—'}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {state === 'approved' && <RunPanel spec={spec} />}
      {state === 'approved' && <ReliabilityPanel workflowId={spec.workflow_id} />}
    </>
  );
};

const ReviewPanel: React.FC<{
  busy: string | null;
  onApprove: () => void;
  onReject: (reason: string) => void;
}> = ({ busy, onApprove, onReject }) => {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <section className="card card-highlight">
      <h2>Review this workflow</h2>
      <p className="muted">
        Check the steps below. Approving lets it run when you (or an email trigger) start it; every live run still
        asks for confirmation.
      </p>
      {rejecting ? (
        <div className="inline-form">
          <input
            autoFocus
            value={reason}
            placeholder="Why are you rejecting it?"
            onChange={(e) => setReason(e.target.value)}
          />
          <button className="btn-danger" disabled={busy !== null || !reason.trim()} onClick={() => onReject(reason.trim())}>
            Reject
          </button>
          <button className="btn-secondary" onClick={() => setRejecting(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="actions">
          <button disabled={busy !== null} onClick={onApprove}>
            {busy === 'approve' ? 'Approving…' : 'Approve'}
          </button>
          <button className="btn-secondary" disabled={busy !== null} onClick={() => setRejecting(true)}>
            Reject…
          </button>
        </div>
      )}
    </section>
  );
};

const RunPanel: React.FC<{ spec: CanonicalWorkflowSpec }> = ({ spec }) => {
  const action = useAction();
  const searchStep = spec.steps.find((s) => s.catalog_action === 'gmail.search_email');
  const observedQuery = spec.variables.find((v) => v.semantic_name === 'search_query')?.observed_values[0] || '';
  const [query, setQuery] = useState(observedQuery);
  const [dryRun, setDryRun] = useState<{ plan: ExecutionPlan; result: DryRunResult } | null>(null);
  const [record, setRecord] = useState<ExecutionAuditRecord | null>(null);
  const [verification, setVerification] = useState<VerificationResult | null>(null);

  const inputs = searchStep && query.trim() ? { search_query: query.trim() } : undefined;
  const changes = spec.steps.filter((s) => s.catalog_action && s.risk.risk_category !== 'read_only');

  const testRun = () =>
    action.run('test', async () => {
      setRecord(null);
      const plan = await planWorkflow(spec.workflow_id, inputs);
      setDryRun({ plan, result: await dryRunPlan(plan.execution_plan_id) });
    });

  const runNow = () => {
    const list = changes.map((s) => `• ${actionLabel(s.action, s.application)}`).join('\n');
    if (!window.confirm(`Run "${spec.title}" for real?\n\nThis will:\n${list}`)) return;
    action.run('run', async () => {
      setDryRun(null);
      setVerification(null);
      const plan = await planWorkflow(spec.workflow_id, inputs);
      const rec = await executePlan(plan.execution_plan_id);
      setRecord(rec);
      if (rec.status === 'COMPLETED') setVerification(await verifyExecution(rec.execution_id));
    });
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>Run it</h2>
        <a href={href('automations', spec.workflow_id)}>Start it from new emails →</a>
      </div>
      {searchStep && (
        <label className="field">
          Which email? (Gmail search)
          <input value={query} placeholder='subject:"Customer Replacement Request" has:attachment' onChange={(e) => setQuery(e.target.value)} />
          <span className="muted small">Use a specific search so the right email is picked; the newest match is used.</span>
        </label>
      )}
      <div className="actions">
        <button className="btn-secondary" disabled={action.busy !== null} onClick={testRun}>
          {action.busy === 'test' ? 'Testing…' : 'Test run (changes nothing)'}
        </button>
        <button disabled={action.busy !== null} onClick={runNow}>
          {action.busy === 'run' ? 'Running…' : 'Run now'}
        </button>
      </div>
      {action.error && <Alert>{action.error}</Alert>}

      {dryRun && <TestRunResult plan={dryRun.plan} result={dryRun.result} />}

      {record && (
        <div className="result">
          <h3>
            Result: <Badge status={record.status} />{' '}
            {verification && <Badge status={verification.overall_status} />}
          </h3>
          <RunSteps record={record} verification={verification} />
          <a href={href('runs', record.execution_id)}>Open run details →</a>
        </div>
      )}
    </section>
  );
};

/** Show what each step would use, without changing anything. */
const TestRunResult: React.FC<{ plan: ExecutionPlan; result: DryRunResult }> = ({ plan, result }) => {
  const blocked = result.step_simulations.filter((s) => s.simulation_status !== 'SIMULATED');
  const describe = (value: string | null) => {
    if (value === null || value === '') return 'missing';
    return /^\{.+\}$/.test(value) ? 'from an earlier step' : value;
  };
  return (
    <div className="result">
      <h3>
        Test run:{' '}
        {blocked.length === 0 ? (
          <Badge status="completed" label="ready to run" />
        ) : (
          <Badge status="failed" label={`${blocked.length} step${blocked.length === 1 ? '' : 's'} can't run`} />
        )}
      </h3>
      <p className="muted small">Nothing was changed. This is what a real run would do:</p>
      <ol className="run-steps">
        {result.step_simulations.map((sim, i) => {
          const planned = plan.planned_steps.find((p) => p.plan_step_id === sim.plan_step_id);
          const params = Object.entries(planned?.resolved_parameters || {}).filter(
            ([k]) => !k.includes('.') && planned?.catalog_action,
          );
          return (
            <li key={sim.plan_step_id} className="run-step">
              <span className="run-step-num">{i + 1}</span>
              <div className="run-step-body">
                <div className="run-step-head">
                  <span className="run-step-title">{actionLabel(sim.action, sim.application)}</span>
                  <Badge status={sim.simulation_status} />
                </div>
                {params.length > 0 && (
                  <div className="muted small">
                    {params.map(([k, v]) => `${k.replace(/_/g, ' ')}: ${describe(v)}`).join(' · ')}
                  </div>
                )}
                {sim.simulation_status !== 'SIMULATED' && <div className="error-text small">{sim.notes}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
};

const ReliabilityPanel: React.FC<{ workflowId: string }> = ({ workflowId }) => {
  const data = useLoad(async () => {
    const runs = await listExecutions(workflowId, 1);
    return runs.length ? getReliability(workflowId) : null;
  }, [workflowId]);
  const p = data.data;
  if (!p || p.total_executions === 0) return null;
  return (
    <section className="card">
      <div className="card-head">
        <h2>How reliable is it?</h2>
        <button className="btn-secondary" onClick={data.reload}>
          Refresh
        </button>
      </div>
      <div className="stats stats-compact">
        <div className="stat">
          <span className="stat-value">{p.total_executions}</span>
          <span className="stat-label">runs</span>
        </div>
        <div className="stat">
          <span className="stat-value">{pct(p.execution_success_rate)}</span>
          <span className="stat-label">finished</span>
        </div>
        <div className="stat">
          <span className="stat-value">{pct(p.verification_rate)}</span>
          <span className="stat-label">verified afterwards</span>
        </div>
      </div>
      {p.suggestions.length > 0 && (
        <>
          <h3>Suggestions</h3>
          <ul className="suggestions">
            {p.suggestions.slice(0, 5).map((s) => (
              <li key={s.suggestion_id}>
                <strong>{s.title}</strong>
                <span className="muted small">{s.suggestion}</span>
              </li>
            ))}
          </ul>
          <p className="muted small">Suggestions are advice from past runs; nothing changes unless you change it.</p>
        </>
      )}
    </section>
  );
};
