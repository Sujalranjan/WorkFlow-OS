import React, { useState } from 'react';
import { listWorkflows } from '../api';
import { ApprovalState } from '../types/canonical';
import { Alert, Badge, Empty, Loading, PageHeader, href, timeAgo, useLoad } from '../ui';

const FILTERS: { id: 'all' | ApprovalState; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'requires_review', label: 'Needs review' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
];

export const WorkflowsPage: React.FC = () => {
  const workflows = useLoad(listWorkflows, []);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all');

  const items = (workflows.data || []).filter((w) => filter === 'all' || w.approval_state.state === filter);

  return (
    <>
      <PageHeader
        title="Workflows"
        subtitle="Workflows created from your repeated routines. Review each one before it can run."
      />
      {workflows.error && <Alert>{workflows.error}</Alert>}

      <div className="segmented" role="tablist" aria-label="Filter workflows">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={filter === f.id}
            className={filter === f.id ? 'segmented-active' : ''}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
            {f.id !== 'all' && workflows.data && (
              <span className="muted"> {workflows.data.filter((w) => w.approval_state.state === f.id).length}</span>
            )}
          </button>
        ))}
      </div>

      <section className="card">
        {workflows.loading && !workflows.data ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty title={filter === 'all' ? 'No workflows yet.' : 'Nothing here.'}>
            {filter === 'all' && (
              <>
                Create one from a repeated routine on the <a href={href('activity')}>Activity</a> page.
              </>
            )}
          </Empty>
        ) : (
          <ul className="rows">
            {items.map((w) => (
              <li key={w.workflow_id}>
                <a className="row-link" href={href('workflows', w.workflow_id)}>
                  <span className="row-main">
                    <span className="row-title">{w.title}</span>
                    <span className="muted small">
                      {Array.from(new Set(w.steps.filter((s) => s.catalog_action).map((s) => s.application))).join(
                        ' → ',
                      ) || `${w.steps.length} steps`}{' '}
                      · created {timeAgo(w.created_at)}
                    </span>
                  </span>
                  <span className="row-meta">
                    <Badge status={w.approval_state.state} />
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
