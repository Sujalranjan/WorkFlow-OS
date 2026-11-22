import React from 'react';
import { getSystem, SystemOverview } from '../api';
import { Alert, Badge, Empty, Loading, PageHeader, href, timeAgo, useLoad } from '../ui';

const countList = (counts: Record<string, number>) =>
  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${n} ${k.toLowerCase().replace(/_/g, ' ')}`)
    .join(' · ') || 'none';

/** Admin overview: is WorkFlowOS able to work, and what needs a person. */
export const SystemPage: React.FC = () => {
  const data = useLoad(getSystem, []);
  return (
    <>
      <PageHeader
        title="System"
        subtitle="Health of WorkFlowOS itself: database, workers, background jobs and email triggers."
        actions={
          <button className="btn-secondary" onClick={data.reload}>
            Refresh
          </button>
        }
      />
      {data.error && <Alert>{data.error}</Alert>}
      {!data.data ? <Loading /> : <SystemBody s={data.data} />}
    </>
  );
};

const SystemBody: React.FC<{ s: SystemOverview }> = ({ s }) => {
  const alive = s.workers.filter((w) => w.alive);
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Status</h2>
          {s.ready ? <Badge status="completed" label="Ready" /> : <Badge status="failed" label="Not ready" />}
        </div>
        <ul className="kv">
          <li>
            <span>Database</span>
            <span>
              {s.database} {s.checks.database ? '· reachable' : '· unreachable'}
              {s.checks.migrations === false && ' · schema out of date (run migrations)'}
            </span>
          </li>
          <li>
            <span>Workers</span>
            <span>
              {s.embedded_worker
                ? 'running inside the API (local development)'
                : alive.length
                  ? `${alive.length} running`
                  : 'none running: queued runs and email checks are not being done'}
            </span>
          </li>
          <li>
            <span>Version</span>
            <span>{s.version}</span>
          </li>
          <li>
            <span>Metrics</span>
            <span>{s.metrics_enabled ? 'Prometheus metrics at /metrics (token required)' : 'off (set METRICS_TOKEN to enable)'}</span>
          </li>
          <li>
            <span>Alerts</span>
            <span>
              {s.alerts.channel_id ? (
                <>
                  to Slack <code>{s.alerts.channel_id}</code>
                </>
              ) : (
                <>
                  off: choose an alert channel in <a href={href('settings')}>Settings › Slack</a>
                </>
              )}
            </span>
          </li>
        </ul>
        {!s.embedded_worker && s.workers.length > 0 && (
          <details className="details">
            <summary>Workers seen</summary>
            <ul className="muted small">
              {s.workers.map((w) => (
                <li key={w.name}>
                  {w.name}: {w.alive ? 'alive' : 'not seen'} · last seen {timeAgo(w.last_seen)}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section className="card">
        <h2>Needs a person</h2>
        {s.needs_attention.length === 0 ? (
          <Empty title="Nothing needs a person.">Jobs that stop after they may have changed an external system appear here.</Empty>
        ) : (
          <>
            <p className="muted small">
              These stopped part-way while they may already have changed Gmail, the CRM, Slack or files. They are never
              retried automatically: check the outcome in that system, then dismiss them from the Runs page.
            </p>
            <ul className="history">
              {s.needs_attention.map((j) => (
                <li key={j.job_id}>
                  <strong>{j.kind.replace(/_/g, ' ')}</strong> <span className="muted small">{timeAgo(j.finished_at || j.created_at)}</span>
                  <div className="error-text small">{j.last_error}</div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Activity</h2>
        <ul className="kv">
          <li>
            <span>Background jobs</span>
            <span>{countList(s.jobs)}</span>
          </li>
          <li>
            <span>Workflow runs</span>
            <span>{countList(s.executions)}</span>
          </li>
          <li>
            <span>Email-triggered runs</span>
            <span>{countList(s.triggered_runs)}</span>
          </li>
        </ul>
        {s.failed_jobs.length > 0 && (
          <details className="details">
            <summary>{s.failed_jobs.length} recently failed job(s)</summary>
            <ul className="muted small">
              {s.failed_jobs.map((j) => (
                <li key={j.job_id}>
                  {j.kind.replace(/_/g, ' ')}: {j.last_error}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section className="card">
        <h2>Email triggers</h2>
        {s.triggers.length === 0 ? (
          <Empty title="No email triggers yet." />
        ) : (
          <ul className="history">
            {s.triggers.map((t) => (
              <li key={t.trigger_id}>
                <strong>{t.name}</strong> {t.enabled ? <Badge status="completed" label="On" /> : <Badge status="paused" label="Off" />}{' '}
                <span className="muted small">checked {t.last_polled_at ? timeAgo(t.last_polled_at) : 'never'}</span>
                {t.last_error && <div className="error-text small">{t.last_error}</div>}
                {!t.last_error && t.last_note && <div className="muted small">{t.last_note}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
};
