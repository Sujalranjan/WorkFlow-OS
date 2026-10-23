import React, { useState } from 'react';
import { createWorkflowFromRoutine, listEvents, listRoutineStructures, listWorkflows, loadSampleActivity } from '../api';
import { WorkflowDNA } from '../types/dna';
import { CanonicalWorkflowSpec } from '../types/canonical';
import { Alert, Badge, Empty, Loading, PageHeader, actionLabel, describeEvent, formatTime, go, href, useAction, useLoad } from '../ui';

const PAGE = 50;

export const ActivityPage: React.FC = () => {
  const events = useLoad(() => listEvents(500), [], 20000);
  const routines = useLoad(async () => {
    const [dna, workflows] = await Promise.all([listRoutineStructures(), listWorkflows()]);
    return { dna: dna.dna_items, workflows };
  }, []);
  const action = useAction();
  const [shown, setShown] = useState(PAGE);

  const reloadAll = () => {
    events.reload();
    routines.reload();
  };

  const hasEvents = (events.data?.length || 0) > 0;

  return (
    <>
      <PageHeader
        title="Activity"
        subtitle="What WorkFlowOS has observed, and the routines you repeat. Routines need at least two similar sessions separated by a short break."
        actions={
          <button className="btn-secondary" onClick={reloadAll}>
            Refresh
          </button>
        }
      />
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}

      <section className="card">
        <h2>Repeated routines</h2>
        {routines.error && <Alert>{routines.error}</Alert>}
        {routines.loading && !routines.data ? (
          <Loading />
        ) : routines.data && routines.data.dna.length > 0 ? (
          <ul className="routines">
            {routines.data.dna.map((dna) => (
              <RoutineCard
                key={dna.dna_id}
                dna={dna}
                workflow={routines.data!.workflows.find(
                  (w) => w.source_dna_id === dna.dna_id && w.approval_state.state !== 'rejected',
                )}
                busy={action.busy}
                onCreate={() =>
                  action.run(`create-${dna.dna_id}`, async () => {
                    const wf = await createWorkflowFromRoutine(dna.dna_id);
                    go('workflows', wf.workflow_id);
                  })
                }
              />
            ))}
          </ul>
        ) : (
          <Empty title="No repeated routine found yet.">
            {hasEvents
              ? 'Do the same task a couple more times, with a few minutes between attempts, then refresh.'
              : 'Record some activity first (see below).'}
          </Empty>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Recent activity</h2>
          {hasEvents && <span className="muted small">{events.data!.length} events</span>}
        </div>
        {events.error && <Alert>{events.error}</Alert>}
        {events.loading && !events.data ? (
          <Loading />
        ) : !hasEvents ? (
          <Empty title="Nothing recorded yet.">
            <p>
              Start the desktop agent (<code>python -m desktop_agent.agent</code>) and load the browser extension from{' '}
              <code>desktop-agent/browser_extension</code>, then do your routine as usual. See the README for setup.
            </p>
            <p>Just exploring? Load three recorded sessions of a Gmail → CRM → Slack routine:</p>
            <button
              disabled={action.busy !== null}
              onClick={() =>
                action.run('sample', async () => {
                  const r = await loadSampleActivity();
                  reloadAll();
                  return r;
                }, (r) => `Loaded ${r.events_created} sample events across ${r.sessions_created} sessions.`)
              }
            >
              {action.busy === 'sample' ? 'Loading…' : 'Load sample activity'}
            </button>
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>App</th>
                    <th>What happened</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data!.slice(0, shown).map((e) => {
                    const view = describeEvent(e);
                    return (
                      <tr key={e.event_id}>
                        <td className="nowrap muted">{formatTime(e.timestamp)}</td>
                        <td className="nowrap">{view.app}</td>
                        <td>{view.text}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {events.data!.length > shown && (
              <button className="btn-secondary btn-block" onClick={() => setShown((n) => n + PAGE)}>
                Show more
              </button>
            )}
          </>
        )}
      </section>
    </>
  );
};

const RoutineCard: React.FC<{
  dna: WorkflowDNA;
  workflow?: CanonicalWorkflowSpec;
  busy: string | null;
  onCreate: () => void;
}> = ({ dna, workflow, busy, onCreate }) => {
  const steps = dna.invariant_steps;
  const apps = Array.from(new Set(steps.map((s) => s.application)));
  const minutes = Math.max(1, Math.round((dna.boundaries.average_duration_seconds || 0) / 60));
  const changing = dna.variable_parameters.filter((v) => v.distinct_value_count > 1);

  return (
    <li className="routine">
      <div className="routine-head">
        <div>
          <div className="routine-title">{apps.join(' → ')}</div>
          <div className="muted small">
            Seen {dna.boundaries.total_supporting_sessions} times · about {minutes} min each
          </div>
        </div>
        {workflow ? (
          <div className="routine-actions">
            <Badge status={workflow.approval_state.state} />
            <a className="btn btn-secondary" href={href('workflows', workflow.workflow_id)}>
              Open workflow
            </a>
          </div>
        ) : (
          <button disabled={busy !== null} onClick={onCreate}>
            {busy === `create-${dna.dna_id}` ? 'Creating…' : 'Create workflow'}
          </button>
        )}
      </div>
      <ol className="step-chips">
        {steps.map((s) => (
          <li key={s.step_key}>
            {s.event_type === 'window_focused' ? `Open ${s.application}` : actionLabel(s.step_key.split(':').pop() || s.event_type)}
            <span className="muted"> · {s.application}</span>
          </li>
        ))}
      </ol>
      {changing.length > 0 && (
        <p className="muted small">
          Changes each time:{' '}
          {changing
            .map((v) => `${v.parameter_name.replace(/_/g, ' ')} (e.g. ${v.observed_values.slice(0, 2).join(', ')})`)
            .join('; ')}
        </p>
      )}
    </li>
  );
};
