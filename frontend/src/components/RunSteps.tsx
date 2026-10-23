import React from 'react';
import { ExecutionAuditRecord, ExecutionStepResult, VerificationResult } from '../types/execution';
import { Badge, actionLabel } from '../ui';

/** One line of human-readable outcome for a step, from its structured output. */
function stepSummary(step: ExecutionStepResult): string | null {
  const o = step.output || {};
  const action = step.action_name.toLowerCase();
  if (action === 'search_email') {
    const m = o.selected_message;
    if (m) return `Email “${m.subject || '(no subject)'}” from ${m.sender || 'unknown sender'}`;
    if (o.total_found === 0) return `No email matched “${o.query}”`;
  }
  if (action.includes('download_attachment') && o.filename) {
    const kb = o.size_bytes ? ` (${Math.max(1, Math.round(o.size_bytes / 1024))} KB)` : '';
    return `Saved ${o.filename}${kb}`;
  }
  if (action === 'find_customer') {
    const c = o.customer || o.matched_customer;
    if (c) return `${c.name || c.customer_id} · ${c.email || ''} (${c.customer_id})`;
  }
  if (action.startsWith('update_customer') && o.updated_fields) {
    return `Set ${Object.entries(o.updated_fields)
      .map(([k, v]) => `${k} = ${v}`)
      .join(', ')} on ${o.customer_id}`;
  }
  if (action === 'send_notification' && (o.channel || o.ts)) {
    return `Posted to ${o.channel || 'Slack'}`;
  }
  return null;
}

export const RunSteps: React.FC<{ record: ExecutionAuditRecord; verification?: VerificationResult | null }> = ({
  record,
  verification,
}) => {
  // A resumed run keeps the paused attempt in its history; show the latest attempt per step.
  const latest = new Map<string, ExecutionStepResult>();
  const pausedEarlier = new Set<string>();
  for (const s of record.step_results) {
    if (latest.has(s.planned_step_id) && latest.get(s.planned_step_id)!.status === 'NEEDS_INPUT') {
      pausedEarlier.add(s.planned_step_id);
    }
    latest.set(s.planned_step_id, s);
  }

  return (
    <ol className="run-steps">
      {Array.from(latest.values()).map((s, i) => {
        const checks = verification?.checks.filter((c) => c.planned_step_id === s.planned_step_id) || [];
        const failedCheck = checks.find((c) => c.status === 'FAILED');
        const summary = stepSummary(s);
        return (
          <li key={s.planned_step_id} className={`run-step run-step-${s.status.toLowerCase()}`}>
            <span className="run-step-num">{i + 1}</span>
            <div className="run-step-body">
              <div className="run-step-head">
                <span className="run-step-title">{actionLabel(s.action_name, s.target_application)}</span>
                <span className="row-meta">
                  <Badge status={s.status} />
                  {checks.length > 0 && <Badge status={failedCheck ? 'FAILED' : checks[0].status} />}
                </span>
              </div>
              {summary && <div className="small">{summary}</div>}
              {s.output?.selected_by === 'user_intervention' && (
                <div className="muted small">Customer chosen by a person.</div>
              )}
              {pausedEarlier.has(s.planned_step_id) && (
                <div className="muted small">Paused here for input, then continued.</div>
              )}
              {s.error && s.status !== 'SUCCESS' && s.status !== 'SKIPPED' && <div className="error-text small">{s.error}</div>}
              {failedCheck && <div className="error-text small">Verification: {failedCheck.reason}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
};
