import React, { useState, useEffect, useCallback } from 'react';
import { WorkflowReliabilityProfile } from '../types/learning';
import { CanonicalWorkflowSpec } from '../types/canonical';

interface WorkflowLearningViewProps {
  specifications: CanonicalWorkflowSpec[];
  apiBaseUrl: string;
}

export const WorkflowLearningView: React.FC<WorkflowLearningViewProps> = ({
  specifications,
  apiBaseUrl,
}) => {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('');
  const [profile, setProfile] = useState<WorkflowReliabilityProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Default to first approved spec or first spec
  useEffect(() => {
    if (!selectedWorkflowId && specifications.length > 0) {
      const approved = specifications.find((s) => s.approval_state?.state === 'approved');
      setSelectedWorkflowId(approved ? approved.workflow_id : specifications[0].workflow_id);
    }
  }, [specifications, selectedWorkflowId]);

  const fetchProfile = useCallback(async (workflowId: string) => {
    if (!workflowId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/workflows/${workflowId}/learning`);
      if (!res.ok) {
        throw new Error(`Failed to load reliability profile: HTTP ${res.status}`);
      }
      const data: WorkflowReliabilityProfile = await res.json();
      setProfile(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error loading profile');
    } finally {
      setIsLoading(false);
    }
  }, [apiBaseUrl]);

  const handleRefresh = async () => {
    if (!selectedWorkflowId) return;
    setIsRefreshing(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/workflows/${selectedWorkflowId}/learning/refresh`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error(`Failed to refresh reliability profile: HTTP ${res.status}`);
      }
      const data: WorkflowReliabilityProfile = await res.json();
      setProfile(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to refresh learning intelligence');
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    if (selectedWorkflowId) {
      fetchProfile(selectedWorkflowId);
    }
  }, [selectedWorkflowId, fetchProfile]);

  return (
    <section
      style={{
        backgroundColor: '#0f172a',
        border: '1px solid #1e293b',
        borderRadius: '10px',
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
        marginTop: '24px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                backgroundColor: '#3b82f6',
                color: '#fff',
                fontSize: '11px',
                fontWeight: 'bold',
                padding: '2px 8px',
                borderRadius: '4px',
                textTransform: 'uppercase',
              }}
            >
              Phase 11 Active
            </span>
            <h2 style={{ margin: 0, color: '#f8fafc', fontSize: '20px' }}>
              Workflow Learning & Reliability Intelligence
            </h2>
          </div>
          <p style={{ margin: '6px 0 0 0', color: '#94a3b8', fontSize: '14px' }}>
            Empirical historical aggregation of execution outcomes, verification evidence, and failure patterns. Generates advisory improvement suggestions without modifying workflows automatically.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {specifications.length > 0 && (
            <select
              value={selectedWorkflowId}
              onChange={(e) => setSelectedWorkflowId(e.target.value)}
              style={{
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                color: '#f8fafc',
                borderRadius: '6px',
                border: '1px solid #334155',
                fontSize: '13px',
              }}
            >
              {specifications.map((s) => (
                <option key={s.workflow_id} value={s.workflow_id}>
                  {s.title} ({s.workflow_id})
                </option>
              ))}
            </select>
          )}

          <button
            onClick={handleRefresh}
            disabled={isRefreshing || !selectedWorkflowId}
            style={{
              padding: '8px 14px',
              backgroundColor: '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              fontWeight: '600',
              fontSize: '13px',
              cursor: isRefreshing || !selectedWorkflowId ? 'not-allowed' : 'pointer',
              opacity: isRefreshing ? 0.7 : 1,
            }}
          >
            {isRefreshing ? 'Recomputing...' : 'Refresh Intelligence'}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#451a1a',
            border: '1px solid #7f1d1d',
            borderRadius: '6px',
            color: '#fca5a5',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      )}

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: '30px', color: '#94a3b8' }}>
          Loading reliability profile...
        </div>
      ) : profile ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Workflow-Level Metrics KPI Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: '12px',
            }}
          >
            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #334155' }}>
              <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>Total Executions</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#f8fafc', marginTop: '4px' }}>{profile.total_executions}</div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #065f46' }}>
              <div style={{ fontSize: '11px', color: '#34d399', textTransform: 'uppercase', fontWeight: 600 }}>Verified Successes</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>{profile.verified_executions}</div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #991b1b' }}>
              <div style={{ fontSize: '11px', color: '#f87171', textTransform: 'uppercase', fontWeight: 600 }}>Execution Failures</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#ef4444', marginTop: '4px' }}>{profile.failed_executions}</div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #b45309' }}>
              <div style={{ fontSize: '11px', color: '#fbbf24', textTransform: 'uppercase', fontWeight: 600 }}>Verification Failures</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>{profile.verification_failures}</div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #581c87' }}>
              <div style={{ fontSize: '11px', color: '#c084fc', textTransform: 'uppercase', fontWeight: 600 }}>Blocked Steps</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#a855f7', marginTop: '4px' }}>{profile.blocked_executions}</div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #1e3a8a' }}>
              <div style={{ fontSize: '11px', color: '#60a5fa', textTransform: 'uppercase', fontWeight: 600 }}>Verified Reliability</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#3b82f6', marginTop: '4px' }}>
                {(profile.reliability_rate * 100).toFixed(1)}%
              </div>
            </div>

            <div style={{ backgroundColor: '#1e293b', padding: '14px', borderRadius: '8px', border: '1px solid #334155' }}>
              <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>Verification Rate</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#cbd5e1', marginTop: '4px' }}>
                {(profile.verification_rate * 100).toFixed(1)}%
              </div>
            </div>
          </div>

          {/* Step-Level Reliability Table */}
          <div>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#f8fafc' }}>
              Step-Level Empirical Reliability
            </h3>
            {profile.step_reliabilities.length === 0 ? (
              <p style={{ color: '#94a3b8', fontSize: '13px' }}>No step executions recorded yet for this workflow.</p>
            ) : (
              <div style={{ overflowX: 'auto', border: '1px solid #334155', borderRadius: '6px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#1e293b', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                      <th style={{ padding: '10px 14px' }}>Step / Action</th>
                      <th style={{ padding: '10px 14px' }}>Target System</th>
                      <th style={{ padding: '10px 14px' }}>Selected Strategy</th>
                      <th style={{ padding: '10px 14px' }}>Runs</th>
                      <th style={{ padding: '10px 14px' }}>Verified</th>
                      <th style={{ padding: '10px 14px' }}>Failed</th>
                      <th style={{ padding: '10px 14px' }}>Blocked</th>
                      <th style={{ padding: '10px 14px' }}>Last Outcome</th>
                      <th style={{ padding: '10px 14px' }}>Pattern</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.step_reliabilities.map((st) => (
                      <tr key={st.planned_step_id} style={{ borderBottom: '1px solid #1e293b' }}>
                        <td style={{ padding: '10px 14px', color: '#f8fafc', fontWeight: 500 }}>
                          {st.action}
                          <div style={{ fontSize: '11px', color: '#64748b' }}>{st.planned_step_id}</div>
                        </td>
                        <td style={{ padding: '10px 14px', color: '#cbd5e1' }}>{st.target}</td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            style={{
                              backgroundColor: st.selected_strategy === 'CONTROLLED_LOCAL' ? '#064e3b' : '#334155',
                              color: st.selected_strategy === 'CONTROLLED_LOCAL' ? '#34d399' : '#94a3b8',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              fontSize: '11px',
                              fontFamily: 'monospace',
                            }}
                          >
                            {st.selected_strategy || 'NONE'}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px', color: '#cbd5e1' }}>{st.total_executions}</td>
                        <td style={{ padding: '10px 14px', color: '#10b981', fontWeight: 600 }}>{st.verified_success_count}</td>
                        <td style={{ padding: '10px 14px', color: st.failed_executions + st.verification_failure_count > 0 ? '#ef4444' : '#64748b' }}>
                          {st.failed_executions + st.verification_failure_count}
                        </td>
                        <td style={{ padding: '10px 14px', color: st.blocked_executions > 0 ? '#a855f7' : '#64748b' }}>
                          {st.blocked_executions}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: '4px',
                              fontSize: '11px',
                              fontWeight: 600,
                              backgroundColor:
                                st.last_outcome === 'VERIFIED' ? '#064e3b' :
                                st.last_outcome === 'BLOCKED' ? '#581c87' :
                                st.last_outcome === 'VERIFICATION_FAILED' ? '#78350f' : '#7f1d1d',
                              color:
                                st.last_outcome === 'VERIFIED' ? '#34d399' :
                                st.last_outcome === 'BLOCKED' ? '#c084fc' :
                                st.last_outcome === 'VERIFICATION_FAILED' ? '#fcd34d' : '#fca5a5',
                            }}
                          >
                            {st.last_outcome}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          {st.failure_pattern ? (
                            <span style={{ color: '#f59e0b', fontSize: '11px', fontWeight: 600 }}>
                              ⚠️ {st.failure_pattern}
                            </span>
                          ) : (
                            <span style={{ color: '#64748b', fontSize: '11px' }}>None</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Detected Patterns */}
          {profile.detected_patterns.length > 0 && (
            <div>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#f8fafc' }}>
                Detected Empirical Failure & Operational Patterns
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
                {profile.detected_patterns.map((pat) => (
                  <div
                    key={pat.pattern_id}
                    style={{
                      backgroundColor: '#1e293b',
                      border: '1px solid #334155',
                      borderRadius: '8px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span
                        style={{
                          backgroundColor: pat.pattern_type.includes('SUCCESS') ? '#065f46' : '#7f1d1d',
                          color: pat.pattern_type.includes('SUCCESS') ? '#a7f3d0' : '#fecaca',
                          fontSize: '11px',
                          fontWeight: 'bold',
                          padding: '2px 6px',
                          borderRadius: '4px',
                        }}
                      >
                        {pat.pattern_type}
                      </span>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                        Occurred: {pat.occurrence_count} time(s)
                      </span>
                    </div>
                    <div style={{ color: '#f8fafc', fontSize: '13px', lineHeight: '1.4' }}>
                      {pat.description}
                    </div>
                    <div style={{ fontSize: '11px', color: '#64748b' }}>
                      Evidence Executions: {pat.evidence_execution_ids.join(', ') || 'N/A'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Advisory Improvement Suggestions */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '16px', color: '#f8fafc' }}>
                Evidence-Backed Improvement Suggestions
              </h3>
              <span
                style={{
                  backgroundColor: '#374151',
                  color: '#9ca3af',
                  fontSize: '10px',
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  textTransform: 'uppercase',
                }}
              >
                Advisory Only — Human Approval Required
              </span>
            </div>

            {profile.suggestions.length === 0 ? (
              <p style={{ color: '#94a3b8', fontSize: '13px' }}>
                No improvement suggestions generated yet. Accumulate execution history to discover operational opportunities.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {profile.suggestions.map((sug) => (
                  <div
                    key={sug.suggestion_id}
                    style={{
                      backgroundColor: '#1e293b',
                      borderLeft: '4px solid #3b82f6',
                      borderRadius: '4px 8px 8px 4px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                      <span style={{ color: '#60a5fa', fontWeight: 600, fontSize: '14px' }}>
                        💡 {sug.title}
                      </span>
                      <span
                        style={{
                          backgroundColor: '#1e3a8a',
                          color: '#93c5fd',
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          fontWeight: 500,
                        }}
                      >
                        {sug.category}
                      </span>
                    </div>
                    <div style={{ color: '#e2e8f0', fontSize: '13px', lineHeight: '1.4' }}>
                      {sug.suggestion}
                    </div>
                    <div style={{ fontSize: '12px', color: '#94a3b8', backgroundColor: '#0f172a', padding: '8px 10px', borderRadius: '4px' }}>
                      <strong style={{ color: '#cbd5e1' }}>Ground Truth Evidence: </strong>
                      {JSON.stringify(sug.evidence)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Learning Events Audit History */}
          {profile.latest_events.length > 0 && (
            <div>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#f8fafc' }}>
                Recent Learning & Verification Observations
              </h3>
              <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid #334155', borderRadius: '6px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ backgroundColor: '#1e293b', color: '#94a3b8', borderBottom: '1px solid #334155' }}>
                      <th style={{ padding: '8px 12px' }}>Timestamp</th>
                      <th style={{ padding: '8px 12px' }}>Event Type</th>
                      <th style={{ padding: '8px 12px' }}>Insight</th>
                      <th style={{ padding: '8px 12px' }}>Execution ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.latest_events.slice().reverse().map((ev) => (
                      <tr key={ev.event_id} style={{ borderBottom: '1px solid #1e293b' }}>
                        <td style={{ padding: '8px 12px', color: '#64748b' }}>{ev.timestamp.slice(11, 19)}</td>
                        <td style={{ padding: '8px 12px', color: '#cbd5e1', fontWeight: 500 }}>{ev.event_type}</td>
                        <td style={{ padding: '8px 12px', color: '#e2e8f0' }}>{ev.insight}</td>
                        <td style={{ padding: '8px 12px', color: '#64748b', fontFamily: 'monospace' }}>{ev.execution_id || 'N/A'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: '30px', color: '#94a3b8' }}>
          Select a workflow specification to view reliability intelligence.
        </div>
      )}
    </section>
  );
};
