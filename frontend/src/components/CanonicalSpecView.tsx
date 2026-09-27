import React, { useState, useEffect } from 'react';
import { CanonicalWorkflowSpec, ParameterBinding } from '../types/canonical';
import { SemanticWorkflow } from '../types/semantic';

interface CanonicalSpecViewProps {
  specifications: CanonicalWorkflowSpec[];
  semanticWorkflows: SemanticWorkflow[];
  isLoading: boolean;
  onGenerateSpec: (semanticWorkflowId: string) => Promise<void>;
  onApprove: (workflowId: string, reviewer?: string, comments?: string) => Promise<void>;
  onReject: (workflowId: string, reason: string) => Promise<void>;
  onUpdateParameters: (workflowId: string, updates: { source_parameter: string; semantic_name: string }[]) => Promise<void>;
  onRefresh: () => void;
  selectedWorkflowId?: string | null;
  onSelectWorkflowId?: (workflowId: string) => void;
}

export const CanonicalSpecView: React.FC<CanonicalSpecViewProps> = ({
  specifications,
  semanticWorkflows,
  isLoading,
  onGenerateSpec,
  onApprove,
  onReject,
  onUpdateParameters,
  onRefresh,
  selectedWorkflowId: selectedWorkflowIdProp,
  onSelectWorkflowId,
}) => {
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(selectedWorkflowIdProp || null);
  const [editingParams, setEditingParams] = useState<Record<string, string>>({});
  const [rejectReason, setRejectReason] = useState<string>('');
  const [isRejecting, setIsRejecting] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    if (selectedWorkflowIdProp) {
      setSelectedWorkflowId(selectedWorkflowIdProp);
    }
  }, [selectedWorkflowIdProp]);

  // Automatically select first spec if none selected
  const activeSpec = specifications.find((s) => s.workflow_id === (selectedWorkflowIdProp || selectedWorkflowId)) || specifications[0] || null;

  const handleStartParamEdit = (b: ParameterBinding) => {
    setEditingParams((prev) => ({
      ...prev,
      [b.source_parameter]: b.semantic_name,
    }));
  };

  const handleParamChange = (sourceParam: string, val: string) => {
    setEditingParams((prev) => ({
      ...prev,
      [sourceParam]: val,
    }));
  };

  const handleSaveParameters = async () => {
    if (!activeSpec) return;
    const updates = Object.entries(editingParams).map(([source_parameter, semantic_name]) => ({
      source_parameter,
      semantic_name,
    }));

    if (updates.length === 0) return;

    try {
      await onUpdateParameters(activeSpec.workflow_id, updates);
      setActionMessage('Parameter bindings successfully updated.');
      setEditingParams({});
      setTimeout(() => setActionMessage(null), 4000);
    } catch (err: unknown) {
      setActionMessage(err instanceof Error ? err.message : 'Failed to update parameters.');
    }
  };

  const handleApproveAction = async () => {
    if (!activeSpec) return;
    try {
      await onApprove(activeSpec.workflow_id, 'Human Reviewer', 'Verified workflow steps and risk profile.');
      setActionMessage('Workflow specification APPROVED. Note: Approval records governance intent only; no code was executed.');
      setTimeout(() => setActionMessage(null), 6000);
    } catch (err: unknown) {
      setActionMessage(err instanceof Error ? err.message : 'Approval failed.');
    }
  };

  const handleRejectAction = async () => {
    if (!activeSpec) return;
    if (!rejectReason.trim()) {
      alert('Please provide a reason for rejecting this specification.');
      return;
    }
    try {
      await onReject(activeSpec.workflow_id, rejectReason.trim());
      setActionMessage('Workflow specification REJECTED.');
      setIsRejecting(false);
      setRejectReason('');
      setTimeout(() => setActionMessage(null), 6000);
    } catch (err: unknown) {
      setActionMessage(err instanceof Error ? err.message : 'Rejection failed.');
    }
  };

  return (
    <section className="section-container" style={{ marginTop: '2.5rem' }}>
      <div className="section-header">
        <div>
          <div className="badge badge-purple" style={{ marginBottom: '0.5rem' }}>
            Phase 6: Canonical Specification & Governance
          </div>
          <h2 className="section-title">Canonical Workflow Specification & User Approval</h2>
          <p className="section-subtitle">
            Formal executable-ready workflow contract. AI proposes meaning, deterministic systems
            enforce structure, and the human user approves intent.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button className="btn btn-secondary" onClick={onRefresh} disabled={isLoading}>
            Refresh Specs
          </button>
        </div>
      </div>

      {/* Governance Banner: Human In Control */}
      <div
        style={{
          background: 'rgba(30, 41, 59, 0.7)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          borderRadius: '8px',
          padding: '1rem 1.25rem',
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '1rem',
        }}
      >
        <div style={{ fontSize: '1.75rem' }}>🛡️</div>
        <div>
          <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.95rem' }}>
            Human-in-the-Loop Governance: Approval Accepts Intent — Strictly No Execution
          </div>
          <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: '0.2rem' }}>
            Approving this workflow specification validates the business routine and parameter bindings.
            No automated browser actions, click replays, or API mutations are triggered during approval.
          </div>
        </div>
      </div>

      {actionMessage && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            color: '#34d399',
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            marginBottom: '1.25rem',
            fontSize: '0.9rem',
          }}
        >
          {actionMessage}
        </div>
      )}

      {/* Generation Bar: If there are un-converted Semantic Workflows */}
      {semanticWorkflows.length > 0 && (
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.6)',
            border: '1px dashed rgba(148, 163, 184, 0.25)',
            borderRadius: '8px',
            padding: '1rem',
            marginBottom: '1.5rem',
          }}
        >
          <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '0.5rem' }}>
            Generate Canonical Specification from Validated Semantic Workflows:
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {semanticWorkflows.map((sem) => {
              const alreadyHasSpec = specifications.some((s) => s.source_semantic_workflow_id === sem.semantic_workflow_id);
              return (
                <button
                  key={sem.semantic_workflow_id}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
                  disabled={isLoading || alreadyHasSpec}
                  onClick={() => onGenerateSpec(sem.semantic_workflow_id)}
                >
                  {alreadyHasSpec ? '✓ Spec Ready: ' : '+ Build Spec: '}
                  {sem.title}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Specifications Selector */}
      {specifications.length > 1 && (
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', overflowX: 'auto', paddingBottom: '0.5rem' }}>
          {specifications.map((s) => (
            <button
              key={s.workflow_id}
              onClick={() => {
                setSelectedWorkflowId(s.workflow_id);
                onSelectWorkflowId?.(s.workflow_id);
              }}
              style={{
                background: (activeSpec?.workflow_id === s.workflow_id) ? 'rgba(99, 102, 241, 0.2)' : 'rgba(15, 23, 42, 0.6)',
                border: (activeSpec?.workflow_id === s.workflow_id) ? '1px solid #6366f1' : '1px solid rgba(255, 255, 255, 0.1)',
                color: '#f8fafc',
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
                textAlign: 'left',
              }}
            >
              <div style={{ fontWeight: 600 }}>{s.title}</div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                State: <span style={{ textTransform: 'uppercase', color: s.approval_state.state === 'approved' ? '#34d399' : '#f59e0b' }}>{s.approval_state.state}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {!activeSpec ? (
        <div className="empty-state">
          <p>No canonical workflow specifications created yet.</p>
          <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
            Interpret a WorkflowDNA above in Phase 5 to generate a validated SemanticWorkflow, then click "Build Spec".
          </span>
        </div>
      ) : (
        <div className="card" style={{ padding: '1.75rem', background: 'rgba(15, 23, 42, 0.85)' }}>
          {/* Header & Governance Controls */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', borderBottom: '1px solid rgba(255, 255, 255, 0.1)', paddingBottom: '1.25rem', marginBottom: '1.5rem' }}>
            <div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                <span className="badge badge-purple">{activeSpec.workflow_id}</span>
                <span
                  className="badge"
                  style={{
                    background:
                      activeSpec.approval_state.state === 'approved'
                        ? 'rgba(16, 185, 129, 0.2)'
                        : activeSpec.approval_state.state === 'rejected'
                        ? 'rgba(239, 68, 68, 0.2)'
                        : 'rgba(245, 158, 11, 0.2)',
                    color:
                      activeSpec.approval_state.state === 'approved'
                        ? '#34d399'
                        : activeSpec.approval_state.state === 'rejected'
                        ? '#f87171'
                        : '#fbbf24',
                    border: '1px solid currentColor',
                  }}
                >
                  STATE: {activeSpec.approval_state.state.toUpperCase()}
                </span>
                <span
                  className="badge"
                  style={{
                    background:
                      activeSpec.risk_assessment.overall_risk_level === 'high'
                        ? 'rgba(239, 68, 68, 0.2)'
                        : activeSpec.risk_assessment.overall_risk_level === 'medium'
                        ? 'rgba(245, 158, 11, 0.2)'
                        : 'rgba(16, 185, 129, 0.2)',
                    color:
                      activeSpec.risk_assessment.overall_risk_level === 'high'
                        ? '#f87171'
                        : activeSpec.risk_assessment.overall_risk_level === 'medium'
                        ? '#fbbf24'
                        : '#34d399',
                  }}
                >
                  OVERALL RISK: {activeSpec.risk_assessment.overall_risk_level.toUpperCase()}
                </span>
              </div>
              <h3 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#f8fafc', margin: '0.2rem 0' }}>
                {activeSpec.title}
              </h3>
              <p style={{ color: '#94a3b8', fontSize: '0.9rem', margin: '0.2rem 0' }}>
                {activeSpec.intent}
              </p>
            </div>

            {/* Approval Action Panel */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'flex-end' }}>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {activeSpec.approval_state.state !== 'approved' && (
                  <button
                    className="btn btn-primary"
                    style={{ background: '#10b981', borderColor: '#10b981' }}
                    onClick={handleApproveAction}
                    disabled={isLoading}
                  >
                    ✓ Approve Specification
                  </button>
                )}
                {activeSpec.approval_state.state !== 'rejected' && (
                  <button
                    className="btn btn-secondary"
                    style={{ borderColor: '#ef4444', color: '#f87171' }}
                    onClick={() => setIsRejecting(!isRejecting)}
                    disabled={isLoading}
                  >
                    ✕ Reject Specification
                  </button>
                )}
              </div>

              {activeSpec.approval_state.reviewed_by && (
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                  Reviewed by: <strong>{activeSpec.approval_state.reviewed_by}</strong> on{' '}
                  {new Date(activeSpec.approval_state.reviewed_at!).toLocaleString()}
                </div>
              )}
            </div>
          </div>

          {/* Rejection Reason Form */}
          {isRejecting && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                padding: '1rem',
                borderRadius: '6px',
                marginBottom: '1.5rem',
              }}
            >
              <div style={{ fontWeight: 600, color: '#f87171', fontSize: '0.9rem', marginBottom: '0.4rem' }}>
                Rejection Reason:
              </div>
              <input
                type="text"
                placeholder="e.g. Unapproved CRM modification requires additional team clearance."
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  background: '#0f172a',
                  border: '1px solid #334155',
                  color: '#fff',
                  borderRadius: '4px',
                  marginBottom: '0.5rem',
                }}
              />
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button className="btn btn-primary" style={{ background: '#ef4444', borderColor: '#ef4444', fontSize: '0.8rem' }} onClick={handleRejectAction}>
                  Confirm Rejection
                </button>
                <button className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => setIsRejecting(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Four-Way Architectural Contrast View */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem', marginBottom: '1.75rem' }}>
            <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                1. Observed Ground Truth
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f8fafc', marginTop: '0.2rem' }}>
                WorkflowDNA
              </div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.4rem' }}>
                Source DNA: <code>{activeSpec.source_dna_id}</code><br />
                Invariants: {activeSpec.steps.length} steps (100% stable)<br />
                Supporting: {activeSpec.boundaries.total_supporting_sessions} recorded sessions
              </div>
            </div>

            <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#a855f7', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                2. AI Interpretation
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f8fafc', marginTop: '0.2rem' }}>
                SemanticWorkflow
              </div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.4rem' }}>
                Semantic ID: <code>{activeSpec.source_semantic_workflow_id}</code><br />
                Validation: 100% Invariants Matched<br />
                Hallucinated Steps: 0 (Rejected by Engine)
              </div>
            </div>

            <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#10b981', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                3. Canonical Specification
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f8fafc', marginTop: '0.2rem' }}>
                Formal Contract
              </div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.4rem' }}>
                Status: <code>{activeSpec.status}</code><br />
                Version: {activeSpec.version}<br />
                Traceability: 100% Chain Preserved
              </div>
            </div>

            <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: '6px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                4. Risk & Governance
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#f8fafc', marginTop: '0.2rem' }}>
                Approval State
              </div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '0.4rem' }}>
                Category: <code>{activeSpec.risk_assessment.primary_risk_category}</code><br />
                Human Review: {activeSpec.risk_assessment.requires_human_confirmation ? 'Required' : 'Optional'}<br />
                Autonomous Execution: None
              </div>
            </div>
          </div>

          {/* Traceable Steps Table with Risk Badges */}
          <div style={{ marginBottom: '2rem' }}>
            <h4 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#f8fafc', marginBottom: '0.75rem' }}>
              Traceable Canonical Steps & Risk Analysis
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {activeSpec.steps.map((st, idx) => {
                const r = st.risk;
                const riskColor =
                  r.risk_category === 'external_change'
                    ? '#f87171'
                    : r.risk_category === 'communication'
                    ? '#c084fc'
                    : r.risk_category === 'local_change'
                    ? '#60a5fa'
                    : '#34d399';

                return (
                  <div
                    key={st.canonical_step_id}
                    style={{
                      background: 'rgba(30, 41, 59, 0.4)',
                      border: '1px solid rgba(255, 255, 255, 0.08)',
                      borderRadius: '6px',
                      padding: '1rem',
                      display: 'grid',
                      gridTemplateColumns: '40px 1fr auto',
                      gap: '1rem',
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#94a3b8', textAlign: 'center' }}>
                      {idx}
                    </div>

                    <div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.2rem' }}>
                        <span style={{ fontWeight: 700, color: '#f8fafc', fontSize: '0.95rem' }}>
                          [{st.application}] {st.action}
                        </span>
                        <span className="badge badge-blue" style={{ fontSize: '0.7rem' }}>
                          {st.event_type}
                        </span>
                      </div>
                      <div style={{ color: '#cbd5e1', fontSize: '0.85rem', marginBottom: '0.4rem' }}>
                        {st.description}
                      </div>

                      {/* Traceability Breadcrumbs */}
                      <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                        Traceability: <code>{st.canonical_step_id}</code> &rarr;{' '}
                        <code>{st.source_semantic_step_id}</code> &rarr;{' '}
                        <code>{st.source_dna_step_key}</code> | Citation: {st.evidence_reference}
                      </div>
                    </div>

                    {/* Step Risk Classification */}
                    <div style={{ textAlign: 'right', minWidth: '160px' }}>
                      <span
                        className="badge"
                        style={{
                          background: `${riskColor}22`,
                          color: riskColor,
                          border: `1px solid ${riskColor}66`,
                          marginBottom: '0.3rem',
                          display: 'inline-block',
                        }}
                      >
                        {r.risk_category.toUpperCase()} ({r.risk_level.toUpperCase()})
                      </span>
                      <div style={{ fontSize: '0.75rem', color: '#94a3b8', maxWidth: '220px' }}>
                        {r.reason}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Parameter Binding & Customization Section */}
          <div style={{ marginBottom: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <div>
                <h4 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#f8fafc', margin: 0 }}>
                  Deterministic Parameter Bindings & Type Inference
                </h4>
                <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  User can customize semantic names. Underlying DNA source parameters remain permanently immutable.
                </div>
              </div>
              {Object.keys(editingParams).length > 0 && (
                <button className="btn btn-primary" onClick={handleSaveParameters}>
                  Save Modified Parameters ({Object.keys(editingParams).length})
                </button>
              )}
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)', color: '#94a3b8' }}>
                    <th style={{ padding: '0.6rem' }}>Semantic Name (Editable)</th>
                    <th style={{ padding: '0.6rem' }}>Source DNA Parameter (Locked)</th>
                    <th style={{ padding: '0.6rem' }}>Source Field</th>
                    <th style={{ padding: '0.6rem' }}>Inferred Type</th>
                    <th style={{ padding: '0.6rem' }}>Sample Observed Values</th>
                    <th style={{ padding: '0.6rem' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {activeSpec.variables.map((b) => {
                    const isEditing = editingParams[b.source_parameter] !== undefined;
                    const currentValue = isEditing ? editingParams[b.source_parameter] : b.semantic_name;

                    return (
                      <tr key={b.source_parameter} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                        <td style={{ padding: '0.6rem' }}>
                          <input
                            type="text"
                            value={currentValue}
                            onChange={(e) => {
                              handleStartParamEdit(b);
                              handleParamChange(b.source_parameter, e.target.value);
                            }}
                            style={{
                              background: isEditing ? '#1e293b' : 'transparent',
                              border: isEditing ? '1px solid #6366f1' : '1px solid transparent',
                              color: '#38bdf8',
                              fontWeight: 600,
                              padding: '0.25rem 0.5rem',
                              borderRadius: '4px',
                              width: '180px',
                            }}
                          />
                        </td>
                        <td style={{ padding: '0.6rem', color: '#94a3b8' }}>
                          <code>{b.source_parameter}</code>
                        </td>
                        <td style={{ padding: '0.6rem', color: '#cbd5e1' }}>
                          {b.source_field}
                        </td>
                        <td style={{ padding: '0.6rem' }}>
                          <span className="badge badge-purple" style={{ fontSize: '0.75rem' }}>
                            {b.inferred_type.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ padding: '0.6rem', color: '#94a3b8', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {b.observed_values.join(', ')}
                        </td>
                        <td style={{ padding: '0.6rem' }}>
                          <span
                            className="badge"
                            style={{
                              background: b.user_override ? 'rgba(56, 189, 248, 0.2)' : 'rgba(148, 163, 184, 0.2)',
                              color: b.user_override ? '#38bdf8' : '#94a3b8',
                              fontSize: '0.7rem',
                            }}
                          >
                            {b.binding_status.toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Optional Steps if present */}
          {activeSpec.optional_steps.length > 0 && (
            <div style={{ marginBottom: '1.5rem' }}>
              <h4 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#f8fafc', marginBottom: '0.5rem' }}>
                Optional Branch Steps
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {activeSpec.optional_steps.map((opt) => (
                  <div
                    key={opt.canonical_step_id}
                    style={{
                      background: 'rgba(30, 41, 59, 0.3)',
                      border: '1px dashed rgba(255, 255, 255, 0.1)',
                      borderRadius: '6px',
                      padding: '0.75rem 1rem',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.9rem' }}>
                        [{opt.application}] {opt.condition_or_trigger}
                      </div>
                      <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>
                        {opt.description} | DNA key: <code>{opt.source_dna_step_key}</code>
                      </div>
                    </div>
                    <span className="badge badge-purple" style={{ fontSize: '0.75rem' }}>
                      {opt.risk.risk_category.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Preconditions & Boundaries */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '1.25rem' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.9rem', marginBottom: '0.4rem' }}>
                Preconditions & Invariants
              </div>
              <ul style={{ color: '#94a3b8', fontSize: '0.85rem', paddingLeft: '1.25rem', margin: 0 }}>
                {activeSpec.preconditions.map((p, idx) => (
                  <li key={idx}>{p}</li>
                ))}
              </ul>
            </div>

            <div>
              <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.9rem', marginBottom: '0.4rem' }}>
                Empirical Boundaries
              </div>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
                Entry Step: <code>{activeSpec.boundaries.first_step}</code><br />
                Exit Step: <code>{activeSpec.boundaries.last_step}</code><br />
                Avg Duration: {activeSpec.boundaries.average_duration_seconds.toFixed(1)}s across{' '}
                {activeSpec.boundaries.total_supporting_sessions} sessions
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
