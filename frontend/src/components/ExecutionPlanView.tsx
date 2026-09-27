import React, { useState, useEffect } from 'react';
import {
  ExecutionPlan,
  DryRunResult,
  ExecutionAuditRecord,
  VerificationResult,
} from '../types/execution';

interface ExecutionPlanViewProps {
  plan: ExecutionPlan;
  onDryRunComplete: (updatedPlan: ExecutionPlan) => void;
  apiBaseUrl: string;
  externalActiveTab?: 'plan' | 'parameters' | 'strategies' | 'state_changes' | 'dry_run' | 'live_execution' | 'verification';
  onExecutionComplete?: (record: ExecutionAuditRecord) => void;
  onVerificationComplete?: (result: VerificationResult) => void;
}

export const ExecutionPlanView: React.FC<ExecutionPlanViewProps> = ({
  plan,
  onDryRunComplete,
  apiBaseUrl,
  externalActiveTab,
  onExecutionComplete,
  onVerificationComplete,
}) => {
  const [isRunningDryRun, setIsRunningDryRun] = useState(false);
  const [dryRunError, setDryRunError] = useState<string | null>(null);

  // Phase 8 Controlled Live Execution State
  const [isExecutingLive, setIsExecutingLive] = useState(false);
  const [executionResult, setExecutionResult] = useState<ExecutionAuditRecord | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);

  // Phase 9 Post-Execution Verification State
  const [isVerifying, setIsVerifying] = useState(false);
  const [verificationResult, setVerificationResult] = useState<VerificationResult | null>(null);
  const [verificationError, setVerificationError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<
    'plan' | 'parameters' | 'strategies' | 'state_changes' | 'dry_run' | 'live_execution' | 'verification'
  >('plan');

  useEffect(() => {
    if (externalActiveTab) {
      setActiveTab(externalActiveTab);
    }
  }, [externalActiveTab]);

  const handleRunDryRun = async () => {
    setIsRunningDryRun(true);
    setDryRunError(null);
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/workflows/execution-plans/${plan.execution_plan_id}/dry-run`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      );
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to execute dry-run simulation');
      }
      const dryRunResult: DryRunResult = await response.json();
      const updatedPlan: ExecutionPlan = {
        ...plan,
        dry_run_status: dryRunResult.overall_simulation_status.toLowerCase(),
        dry_run_result: dryRunResult,
      };
      onDryRunComplete(updatedPlan);
      setActiveTab('dry_run');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setDryRunError(message);
    } finally {
      setIsRunningDryRun(false);
    }
  };

  const handleExecuteLive = async () => {
    setIsExecutingLive(true);
    setExecutionError(null);
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/workflows/execution-plans/${plan.execution_plan_id}/execute`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            execution_mode: 'LIVE',
            idempotency_key: `run-${plan.execution_plan_id}-${Date.now()}`,
          }),
        }
      );
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to execute controlled plan');
      }
      const auditRecord: ExecutionAuditRecord = await response.json();
      setExecutionResult(auditRecord);
      onExecutionComplete?.(auditRecord);
      setActiveTab('live_execution');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setExecutionError(message);
    } finally {
      setIsExecutingLive(false);
    }
  };

  const handleVerifyExecution = async () => {
    if (!executionResult) return;
    setIsVerifying(true);
    setVerificationError(null);
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/workflows/executions/${executionResult.execution_id}/verify`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force_recheck: true }),
        }
      );
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to verify execution');
      }
      const result: VerificationResult = await response.json();
      setVerificationResult(result);
      onVerificationComplete?.(result);
      setActiveTab('verification');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setVerificationError(message);
    } finally {
      setIsVerifying(false);
    }
  };

  const latestResult = plan.dry_run_result;
  const isApproved = plan.source_approval_state?.toLowerCase() === 'approved';

  // Check if any step requires external services (CRM, Slack, Gmail) which Phase 8 blocks
  const hasExternalSteps = plan.planned_steps.some((s) => {
    const app = s.application.toLowerCase();
    return app.includes('crm') || app.includes('slack') || app.includes('gmail');
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header Banner */}
      <div
        style={{
          padding: '16px 20px',
          backgroundColor: '#0f172a',
          borderRadius: '8px',
          border: '1px solid #334155',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h3 style={{ margin: 0, color: '#f8fafc', fontSize: '18px' }}>
              Execution Plan: {plan.execution_plan_id}
            </h3>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 'bold',
                padding: '3px 8px',
                borderRadius: '4px',
                backgroundColor:
                  plan.dry_run_status?.toUpperCase() === 'SIMULATED'
                    ? '#065f46'
                    : plan.dry_run_status?.toUpperCase() === 'SIMULATION_BLOCKED'
                    ? '#991b1b'
                    : '#374151',
                color: '#fff',
                textTransform: 'uppercase',
              }}
            >
              Status: {plan.dry_run_status || 'PLANNED'}
            </span>
            <span
              style={{
                fontSize: '11px',
                padding: '3px 8px',
                borderRadius: '4px',
                backgroundColor:
                  plan.risk_assessment?.overall_risk_level === 'high'
                    ? '#991b1b'
                    : plan.risk_assessment?.overall_risk_level === 'medium'
                    ? '#854d0e'
                    : '#1e3a8a',
                color: '#fff',
                textTransform: 'uppercase',
              }}
            >
              Risk: {plan.risk_assessment?.overall_risk_level || 'LOW'}
            </span>
          </div>
          <div style={{ color: '#94a3b8', fontSize: '13px', marginTop: '4px' }}>
            Source Workflow: <code>{plan.source_workflow_id}</code> (v{plan.workflow_version}) •
            Source Approval: <strong style={{ color: isApproved ? '#10b981' : '#f87171' }}>{plan.source_approval_state?.toUpperCase()}</strong>
          </div>
        </div>

        {/* Action Buttons: Dry Run, Controlled Execution, and Verification */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <button
              onClick={handleRunDryRun}
              disabled={isRunningDryRun}
              style={{
                padding: '9px 16px',
                backgroundColor: isRunningDryRun ? '#475569' : '#0284c7',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: isRunningDryRun ? 'not-allowed' : 'pointer',
                fontSize: '13px',
              }}
            >
              {isRunningDryRun ? 'Running Simulation...' : 'Run Dry Run'}
            </button>

            {/* Phase 8: Controlled Local Execution Button */}
            <button
              onClick={handleExecuteLive}
              disabled={isExecutingLive || !isApproved}
              title={
                !isApproved
                  ? 'Workflow must be APPROVED before execution'
                  : hasExternalSteps
                  ? 'Notice: External steps will be safely blocked by Phase 8 policy'
                  : 'Execute approved plan inside sandbox'
              }
              style={{
                padding: '9px 16px',
                backgroundColor: !isApproved ? '#334155' : isExecutingLive ? '#475569' : '#16a34a',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: !isApproved || isExecutingLive ? 'not-allowed' : 'pointer',
                fontSize: '13px',
              }}
            >
              {isExecutingLive ? 'Executing Sandbox...' : 'Execute Approved Plan'}
            </button>

            {/* Phase 9: Deterministic Post-Execution Verification Button */}
            <button
              onClick={handleVerifyExecution}
              disabled={!executionResult || isVerifying}
              title={
                !executionResult
                  ? 'Run controlled execution first before verifying'
                  : 'Run deterministic post-execution verification and evidence engine'
              }
              style={{
                padding: '9px 16px',
                backgroundColor: !executionResult ? '#334155' : isVerifying ? '#475569' : '#7c3aed',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: !executionResult || isVerifying ? 'not-allowed' : 'pointer',
                fontSize: '13px',
              }}
            >
              {isVerifying ? 'Verifying Sandbox...' : 'Verify Execution'}
            </button>
          </div>
          <span style={{ fontSize: '11px', color: '#94a3b8', fontStyle: 'italic' }}>
            Phase 8/9 deterministic sandbox execution and verification. Zero external mutations.
          </span>
        </div>
      </div>

      {dryRunError && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#450a0a',
            border: '1px solid #dc2626',
            borderRadius: '6px',
            color: '#fca5a5',
            fontSize: '13px',
          }}
        >
          <strong>Simulation Error:</strong> {dryRunError}
        </div>
      )}

      {executionError && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#450a0a',
            border: '1px solid #dc2626',
            borderRadius: '6px',
            color: '#fca5a5',
            fontSize: '13px',
          }}
        >
          <strong>Execution Guardrail Rejection:</strong> {executionError}
        </div>
      )}

      {verificationError && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#450a0a',
            border: '1px solid #dc2626',
            borderRadius: '6px',
            color: '#fca5a5',
            fontSize: '13px',
          }}
        >
          <strong>Verification Error:</strong> {verificationError}
        </div>
      )}

      {/* State / Mode Indicator Pillars (4 Pillars) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '12px',
        }}
      >
        <div
          style={{
            padding: '12px',
            backgroundColor: '#1e293b',
            borderRadius: '6px',
            borderLeft: '4px solid #38bdf8',
          }}
        >
          <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Stage 1: Contract
          </div>
          <div style={{ fontWeight: 'bold', color: '#f1f5f9', fontSize: '14px', marginTop: '2px' }}>
            PLANNED
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '4px' }}>
            {plan.planned_steps.length} steps planned.
          </div>
        </div>

        <div
          style={{
            padding: '12px',
            backgroundColor: '#1e293b',
            borderRadius: '6px',
            borderLeft: `4px solid ${plan.dry_run_status?.toUpperCase() === 'SIMULATED' ? '#34d399' : '#fbbf24'}`,
          }}
        >
          <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Stage 2: Validation
          </div>
          <div style={{ fontWeight: 'bold', color: '#f1f5f9', fontSize: '14px', marginTop: '2px' }}>
            SIMULATED
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '4px' }}>
            {latestResult
              ? `${latestResult.step_simulations.length} steps walked.`
              : 'Awaiting dry run.'}
          </div>
        </div>

        <div
          style={{
            padding: '12px',
            backgroundColor: '#1e293b',
            borderRadius: '6px',
            borderLeft: `4px solid ${executionResult ? '#22c55e' : '#eab308'}`,
          }}
        >
          <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Stage 3: Execution
          </div>
          <div style={{ fontWeight: 'bold', color: executionResult ? '#4ade80' : '#facc15', fontSize: '14px', marginTop: '2px' }}>
            {executionResult ? `LIVE: ${executionResult.status}` : 'READY FOR SANDBOX'}
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '4px' }}>
            {executionResult
              ? `${executionResult.step_results.length} step(s) evaluated.`
              : 'Execute in isolated sandbox.'}
          </div>
        </div>

        <div
          style={{
            padding: '12px',
            backgroundColor: '#1e293b',
            borderRadius: '6px',
            borderLeft: `4px solid ${
              verificationResult?.overall_status === 'VERIFIED'
                ? '#22c55e'
                : verificationResult?.overall_status === 'FAILED'
                ? '#ef4444'
                : verificationResult?.overall_status === 'UNKNOWN'
                ? '#f59e0b'
                : '#8b5cf6'
            }`,
          }}
        >
          <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Stage 4: Verification (Phase 9)
          </div>
          <div
            style={{
              fontWeight: 'bold',
              color:
                verificationResult?.overall_status === 'VERIFIED'
                  ? '#4ade80'
                  : verificationResult?.overall_status === 'FAILED'
                  ? '#f87171'
                  : verificationResult?.overall_status === 'UNKNOWN'
                  ? '#fbbf24'
                  : '#c084fc',
              fontSize: '14px',
              marginTop: '2px',
            }}
          >
            {verificationResult ? verificationResult.overall_status : 'READY TO VERIFY'}
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '4px' }}>
            {verificationResult
              ? `${verificationResult.verified_count} verified, ${verificationResult.failed_count} failed.`
              : 'Deterministic state & evidence check.'}
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div style={{ display: 'flex', borderBottom: '1px solid #334155', gap: '8px', flexWrap: 'wrap' }}>
        {[
          { key: 'plan', label: '1. Planned Steps' },
          { key: 'parameters', label: '2. Parameter Resolution' },
          { key: 'strategies', label: '3. Execution Strategies' },
          { key: 'state_changes', label: '4. Expected State Changes' },
          { key: 'dry_run', label: '5. Dry Run Result' },
          { key: 'live_execution', label: '6. Controlled Execution Result' },
          { key: 'verification', label: '7. Verification & Evidence' },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as any)}
            style={{
              padding: '8px 16px',
              backgroundColor: activeTab === tab.key ? '#334155' : 'transparent',
              color: activeTab === tab.key ? '#f8fafc' : '#94a3b8',
              border: 'none',
              borderBottom: activeTab === tab.key ? '2px solid #38bdf8' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 500,
              fontSize: '13px',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'plan' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {plan.planned_steps.map((step, idx) => (
            <div
              key={step.plan_step_id}
              style={{
                padding: '16px',
                backgroundColor: '#1e293b',
                borderRadius: '8px',
                border: '1px solid #334155',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '50%',
                      backgroundColor: '#3b82f6',
                      color: '#ffffff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontWeight: 'bold',
                      fontSize: '13px',
                    }}
                  >
                    {idx + 1}
                  </span>
                  <span style={{ fontWeight: 600, color: '#f1f5f9', fontSize: '15px' }}>
                    {step.action}
                  </span>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor: '#334155',
                      color: '#93c5fd',
                    }}
                  >
                    Target: {step.application}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '6px' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      backgroundColor: '#0f766e',
                      color: '#ccfbf1',
                    }}
                  >
                    Strategy: {step.execution_strategy?.strategy}
                  </span>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      backgroundColor:
                        step.risk?.risk_level === 'high'
                          ? '#991b1b'
                          : step.risk?.risk_level === 'medium'
                          ? '#854d0e'
                          : '#1e3a8a',
                      color: '#fff',
                    }}
                  >
                    Risk: {step.risk?.risk_level?.toUpperCase()}
                  </span>
                </div>
              </div>

              <div style={{ color: '#cbd5e1', fontSize: '13px' }}>
                <strong>Intent:</strong> {step.description}
              </div>

              {step.external_change && (
                <div
                  style={{
                    fontSize: '12px',
                    color: '#f87171',
                    backgroundColor: '#450a0a',
                    padding: '6px 10px',
                    borderRadius: '4px',
                    border: '1px solid #7f1d1d',
                  }}
                >
                  ⚠️ <strong>External Mutation Notice:</strong> External system mutation — blocked by Phase 8 policy.
                </div>
              )}

              {/* Traceability Breadcrumb */}
              <div
                style={{
                  fontSize: '11px',
                  color: '#64748b',
                  backgroundColor: '#0f172a',
                  padding: '6px 10px',
                  borderRadius: '4px',
                  display: 'flex',
                  gap: '6px',
                  flexWrap: 'wrap',
                }}
              >
                <span>Planned: <code>{step.plan_step_id}</code></span>
                <span>→</span>
                <span>Canonical: <code>{step.source_canonical_step_id}</code></span>
                <span>→</span>
                <span>Semantic: <code>{step.source_semantic_step_id}</code></span>
                <span>→</span>
                <span>DNA: <code>{step.source_dna_step_key}</code></span>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'parameters' && (
        <div style={{ backgroundColor: '#1e293b', borderRadius: '8px', padding: '16px' }}>
          <h4 style={{ margin: '0 0 12px 0', color: '#f8fafc', fontSize: '15px' }}>
            Deterministic Parameter Resolution
          </h4>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8' }}>
                <th style={{ padding: '8px' }}>Semantic Name</th>
                <th style={{ padding: '8px' }}>DNA Parameter</th>
                <th style={{ padding: '8px' }}>Status</th>
                <th style={{ padding: '8px' }}>Resolved Value</th>
              </tr>
            </thead>
            <tbody>
              {plan.resolved_parameters.map((param, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #334155' }}>
                  <td style={{ padding: '8px', color: '#f1f5f9', fontWeight: 500 }}>
                    {param.semantic_name}
                  </td>
                  <td style={{ padding: '8px', color: '#94a3b8' }}>
                    <code>{param.source_parameter}</code>
                  </td>
                  <td style={{ padding: '8px' }}>
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        backgroundColor:
                          param.resolution_status === 'resolved'
                            ? '#065f46'
                            : param.resolution_status === 'default_sample'
                            ? '#854d0e'
                            : '#991b1b',
                        color: '#fff',
                      }}
                    >
                      {param.resolution_status}
                    </span>
                  </td>
                  <td style={{ padding: '8px', color: '#38bdf8', fontWeight: 600 }}>
                    {param.runtime_value || '— (unresolved)'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'strategies' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div
            style={{
              padding: '14px 18px',
              backgroundColor: '#0f172a',
              borderRadius: '8px',
              border: '1px solid #334155',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ fontWeight: 600, color: '#38bdf8', fontSize: '14px' }}>
              Adaptive Multi-Strategy Executor Selection (Phase 10 & Phase 12)
            </div>
            <div style={{ fontSize: '12px', color: '#94a3b8', lineHeight: 1.5 }}>
              WorkFlowOS deterministically selects executor strategies per step based on capabilities, risk, and approval state.
              <strong style={{ color: '#f8fafc' }}> Known strategy does NOT mean implemented strategy. </strong>
              Phase 12 & 15A implement <code>CONTROLLED_LOCAL</code> and read-only <code>API_INTEGRATION</code> (<code>GmailApiExecutor</code> for search_email and download_attachment); all mutating actions and unsupported external services are safely blocked.
            </div>
          </div>

          {plan.planned_steps.map((step, idx) => {
            const strat = step.execution_strategy;
            const isSupported = Boolean(strat?.executor_implemented && !strat?.blocked_reason);
            const selectedStrategyName = isSupported
              ? (strat?.canonical_strategy || 'CONTROLLED_LOCAL')
              : 'NONE';

            return (
              <div
                key={step.plan_step_id}
                style={{
                  backgroundColor: '#1e293b',
                  padding: '16px',
                  borderRadius: '8px',
                  border: isSupported ? '1px solid #059669' : '1px solid #b91c1c',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '15px' }}>
                      Step {idx + 1}: {step.action}
                    </span>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                      ({step.application})
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span
                      style={{
                        backgroundColor: isSupported ? '#065f46' : '#991b1b',
                        color: '#fff',
                        fontSize: '11px',
                        fontWeight: 'bold',
                        padding: '3px 8px',
                        borderRadius: '4px',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                      }}
                    >
                      Status: {isSupported ? 'SUPPORTED' : 'UNSUPPORTED'}
                    </span>
                    <span
                      style={{
                        backgroundColor: isSupported ? '#0284c7' : '#334155',
                        color: isSupported ? '#fff' : '#94a3b8',
                        fontSize: '11px',
                        fontWeight: 600,
                        padding: '3px 8px',
                        borderRadius: '4px',
                      }}
                    >
                      Strategy: {selectedStrategyName}
                    </span>
                  </div>
                </div>

                <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '10px' }}>
                  <div style={{ backgroundColor: '#0f172a', padding: '10px 12px', borderRadius: '6px', border: '1px solid #334155' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Selection Reason</div>
                    <div style={{ fontSize: '13px', color: isSupported ? '#e2e8f0' : '#fca5a5', marginTop: '4px' }}>
                      {strat?.selection_reason || strat?.reason || 'Evaluated via deterministic strategy selector.'}
                    </div>
                  </div>

                  <div style={{ backgroundColor: '#0f172a', padding: '10px 12px', borderRadius: '6px', border: '1px solid #334155' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>Fallback & Policy</div>
                    <div style={{ fontSize: '13px', color: '#cbd5e1', marginTop: '4px' }}>
                      Fallback Used: <strong style={{ color: strat?.fallback_used ? '#facc15' : '#94a3b8' }}>{strat?.fallback_used ? 'Yes' : 'No'}</strong> •
                      Policy: <strong style={{ color: strat?.policy_decision === 'BLOCKED' ? '#f87171' : '#4ade80' }}>{strat?.policy_decision || 'ALLOWED'}</strong>
                    </div>
                  </div>
                </div>

                {strat?.available_strategies_considered && strat.available_strategies_considered.length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', marginBottom: '6px' }}>
                      Candidate Strategies Evaluated (Fallback Priority Order):
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {strat.available_strategies_considered.map((c) => {
                        const isGmailTarget = step.application.toLowerCase().includes('gmail');
                        const isSearchAction = step.action.toLowerCase().includes('search');
                        const isImplementedCand =
                          c === 'CONTROLLED_LOCAL' ||
                          (c === 'API_INTEGRATION' && isGmailTarget && isSearchAction);
                        return (
                          <span
                            key={c}
                            style={{
                              fontSize: '11px',
                              padding: '3px 8px',
                              borderRadius: '4px',
                              backgroundColor: isImplementedCand ? '#1e3a5f' : '#1f2937',
                              border: isImplementedCand ? '1px solid #0284c7' : '1px solid #374151',
                              color: isImplementedCand ? '#38bdf8' : '#9ca3af',
                            }}
                          >
                            {c} {isImplementedCand ? '✓ (Implemented)' : '✗ (Unimplemented)'}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}


      {activeTab === 'state_changes' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {plan.planned_steps.map((step, idx) => (
            <div
              key={step.plan_step_id}
              style={{
                backgroundColor: '#1e293b',
                padding: '14px',
                borderRadius: '6px',
                border: '1px solid #334155',
              }}
            >
              <div style={{ fontWeight: 600, color: '#f8fafc', marginBottom: '8px' }}>
                Step {idx + 1}: {step.action}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
                <div
                  style={{
                    backgroundColor: '#0f172a',
                    padding: '10px',
                    borderRadius: '4px',
                    border: '1px solid #334155',
                  }}
                >
                  <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase' }}>
                    Before State
                  </div>
                  <div style={{ fontSize: '13px', color: '#cbd5e1', marginTop: '4px' }}>
                    {step.state_change?.before_state || 'System at current operational state'}
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: '#0f172a',
                    padding: '10px',
                    borderRadius: '4px',
                    border: '1px solid #0284c7',
                  }}
                >
                  <div style={{ fontSize: '11px', color: '#38bdf8', textTransform: 'uppercase' }}>
                    Expected After State
                  </div>
                  <div style={{ fontSize: '13px', color: '#f0fdf4', marginTop: '4px' }}>
                    {step.state_change?.expected_after_state || 'Action completed in simulation'}
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: '#0f172a',
                    padding: '10px',
                    borderRadius: '4px',
                    border: '1px solid #dc2626',
                  }}
                >
                  <div style={{ fontSize: '11px', color: '#f87171', textTransform: 'uppercase' }}>
                    Actual State
                  </div>
                  <div style={{ fontSize: '13px', color: '#fca5a5', marginTop: '4px', fontWeight: 600 }}>
                    {step.state_change?.actual_state || 'UNTOUCHED (Phase 7 Safe Mode)'}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'dry_run' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {latestResult ? (
            <>
              <div
                style={{
                  backgroundColor: '#0f172a',
                  padding: '16px',
                  borderRadius: '6px',
                  border: '1px solid #334155',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <h4 style={{ margin: 0, color: '#f8fafc', fontSize: '16px' }}>
                      Simulation Summary ({latestResult.dry_run_id})
                    </h4>
                    <span style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 600 }}>
                      DRY RUN (PROVABLY SIDE-EFFECT FREE — ZERO EXTERNAL API CALLS, NEVER CALLS GMAIL)
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: '12px',
                      fontWeight: 'bold',
                      padding: '3px 8px',
                      borderRadius: '4px',
                      backgroundColor:
                        latestResult.overall_simulation_status?.toUpperCase() === 'SIMULATED' ? '#065f46' : '#991b1b',
                      color: '#fff',
                    }}
                  >
                    {latestResult.overall_simulation_status}
                  </span>
                </div>

                <p style={{ color: '#cbd5e1', fontSize: '13px', marginTop: '8px' }}>
                  {latestResult.summary}
                </p>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gap: '10px',
                    marginTop: '12px',
                  }}
                >
                  <div style={{ backgroundColor: '#1e293b', padding: '10px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Steps Simulated</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#f8fafc' }}>
                      {latestResult.step_simulations.length}
                    </div>
                  </div>
                  <div style={{ backgroundColor: '#1e293b', padding: '10px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Mutations Prevented</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#f59e0b' }}>
                      {latestResult.external_mutations_prevented}
                    </div>
                  </div>
                  <div style={{ backgroundColor: '#1e293b', padding: '10px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>Real Actions Performed</div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#34d399' }}>
                      {latestResult.real_actions_performed}
                    </div>
                  </div>
                </div>
              </div>

              {/* Step Simulation Results */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {latestResult.step_simulations.map((res, i) => (
                  <div
                    key={i}
                    style={{
                      backgroundColor: '#1e293b',
                      padding: '12px 16px',
                      borderRadius: '6px',
                      border: '1px solid #334155',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '14px' }}>
                          Step {res.plan_step_id}: {res.action}
                        </span>
                        <span style={{ fontSize: '11px', color: '#94a3b8' }}>({res.application})</span>
                      </div>
                      <span
                        style={{
                          fontSize: '11px',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          backgroundColor: '#065f46',
                          color: '#6ee7b7',
                        }}
                      >
                        {res.simulation_status}
                      </span>
                    </div>

                    <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                      {res.notes}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div
              style={{
                backgroundColor: '#1e293b',
                padding: '30px',
                textAlign: 'center',
                borderRadius: '8px',
                color: '#94a3b8',
              }}
            >
              <p style={{ margin: 0, fontSize: '15px' }}>
                No dry run has been simulated yet for this execution plan.
              </p>
              <p style={{ margin: '8px 0 0 0', fontSize: '13px' }}>
                Click <strong>"Run Dry Run"</strong> above to perform deterministic shadow simulation.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Phase 8: Controlled Live Execution Results Tab */}
      {activeTab === 'live_execution' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {executionResult ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div
                style={{
                  backgroundColor: '#0f172a',
                  padding: '16px',
                  borderRadius: '6px',
                  border: '1px solid #334155',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ margin: 0, color: '#f8fafc', fontSize: '16px' }}>
                    Execution Audit Record ({executionResult.execution_id})
                  </h4>
                  <span
                    style={{
                      fontSize: '12px',
                      fontWeight: 'bold',
                      padding: '3px 8px',
                      borderRadius: '4px',
                      backgroundColor:
                        executionResult.status === 'COMPLETED'
                          ? '#065f46'
                          : executionResult.status === 'BLOCKED'
                          ? '#854d0e'
                          : '#991b1b',
                      color: '#fff',
                    }}
                  >
                    STATUS: {executionResult.status}
                  </span>
                </div>

                <div style={{ marginTop: '10px', fontSize: '13px', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div><strong>Sandbox Root:</strong> <code>{executionResult.sandbox_root}</code></div>
                  <div><strong>Execution Mode:</strong> {executionResult.execution_mode}</div>
                  <div><strong>Started:</strong> {executionResult.start_time} | <strong>Ended:</strong> {executionResult.end_time || 'Running'}</div>
                  {executionResult.error_summary && (
                    <div style={{ color: '#fca5a5', marginTop: '6px' }}>
                      <strong>Guardrail Policy Note:</strong> {executionResult.error_summary}
                    </div>
                  )}
                </div>
              </div>

              {/* Step Results */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {executionResult.step_results.map((st) => (
                  <div
                    key={st.execution_step_id}
                    style={{
                      backgroundColor: '#1e293b',
                      padding: '14px',
                      borderRadius: '6px',
                      border: '1px solid #334155',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '14px' }}>
                          {st.action_name} ({st.target_application})
                        </span>
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            backgroundColor: st.selected_strategy === 'API_INTEGRATION' ? '#0f766e' : '#1e3a5f',
                            color: '#e2e8f0',
                          }}
                        >
                          Strategy: {st.selected_strategy || st.strategy || 'UNKNOWN'}
                        </span>
                        <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                          Executor: <code>{st.executor_name}</code>
                        </span>
                      </div>
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 'bold',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor:
                            st.status === 'SUCCESS'
                              ? '#065f46'
                              : st.status === 'BLOCKED'
                              ? '#854d0e'
                              : st.status === 'SKIPPED'
                              ? '#334155'
                              : '#991b1b',
                          color: '#fff',
                        }}
                      >
                        {st.status}
                      </span>
                    </div>

                    {st.executor_name === 'GmailApiExecutor' && (
                      <div
                        style={{
                          backgroundColor: '#0f172a',
                          padding: '10px 12px',
                          borderRadius: '6px',
                          border: '1px solid #0f766e',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: '11px', color: '#5eead4', fontWeight: 600, textTransform: 'uppercase' }}>
                            {st.output?.operation === 'download_attachment'
                              ? 'Gmail API Integration (Download Attachment)'
                              : 'Gmail API Integration (Read-Only Search)'}
                          </span>
                          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                            {st.output?.operation === 'download_attachment'
                              ? 'Controlled Sandbox Confinement • Scope (gmail.readonly)'
                              : 'Zero Mutation • Narrow Scope (gmail.readonly)'}
                          </span>
                        </div>
                        {st.output?.operation === 'download_attachment' ? (
                          <div style={{ fontSize: '12px', color: '#cbd5e1', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div>
                              <strong>Downloaded File:</strong> <code style={{ color: '#38bdf8' }}>{st.output.filename}</code> • <strong>Size:</strong> {st.output.size_bytes} bytes
                            </div>
                            {st.output.saved_path && (
                              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                                <strong>Destination:</strong> <code>{st.output.saved_path}</code>
                              </div>
                            )}
                            {st.output.sha256 && (
                              <div style={{ fontSize: '11px', color: '#a7f3d0' }}>
                                <strong>Cryptographic Evidence (SHA-256):</strong> <code>{st.output.sha256}</code>
                              </div>
                            )}
                          </div>
                        ) : (
                          <>
                            {st.output?.query && (
                              <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                <strong>Approved Query:</strong> <code>{st.output.query}</code> • <strong>Matches Found:</strong> {st.output.total_found ?? 0}
                              </div>
                            )}
                            {st.output?.messages && Array.isArray(st.output.messages) && st.output.messages.length > 0 && (
                              <div style={{ marginTop: '4px' }}>
                                <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>
                                  Normalized Message Summaries ({Math.min(st.output.messages.length, 5)} of {st.output.total_found}):
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                  {st.output.messages.slice(0, 5).map((m: any, mIdx: number) => (
                                    <div
                                      key={m.message_id || mIdx}
                                      style={{
                                        backgroundColor: '#1e293b',
                                        padding: '6px 8px',
                                        borderRadius: '4px',
                                        fontSize: '11px',
                                        color: '#cbd5e1',
                                      }}
                                    >
                                      <div>
                                        <strong style={{ color: '#f8fafc' }}>{m.subject || '(No Subject)'}</strong>
                                        <span style={{ color: '#94a3b8', marginLeft: '6px' }}>from: {m.sender || 'Unknown'}</span>
                                      </div>
                                      {m.snippet && (
                                        <div style={{ color: '#94a3b8', fontStyle: 'italic', marginTop: '2px' }}>
                                          "{m.snippet}"
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}

                    {st.error && (
                      <div style={{ fontSize: '12px', color: '#f87171' }}>
                        <strong>Details:</strong> {st.error}
                      </div>
                    )}

                    {st.affected_resources && st.affected_resources.length > 0 && (
                      <div style={{ fontSize: '12px', color: '#38bdf8' }}>
                        <strong>Created Sandbox Resources:</strong>
                        <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                          {st.affected_resources.map((res, idx) => (
                            <li key={idx}><code>{res}</code></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div
              style={{
                backgroundColor: '#1e293b',
                padding: '30px',
                textAlign: 'center',
                borderRadius: '8px',
                color: '#94a3b8',
              }}
            >
              <p style={{ margin: 0, fontSize: '15px' }}>
                No controlled execution has been run yet for this plan.
              </p>
              <p style={{ margin: '8px 0 0 0', fontSize: '13px' }}>
                Click <strong>"Execute Approved Plan"</strong> above to run allowlisted local actions in an isolated sandbox.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Phase 9: Verification & Evidence Results Tab */}
      {activeTab === 'verification' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {verificationResult ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Verification Run Summary Banner */}
              <div
                style={{
                  backgroundColor: '#0f172a',
                  padding: '16px',
                  borderRadius: '6px',
                  border: '1px solid #334155',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                  <div>
                    <h4 style={{ margin: 0, color: '#f8fafc', fontSize: '16px' }}>
                      Verification Run: {verificationResult.verification_run_id}
                    </h4>
                    <div style={{ color: '#94a3b8', fontSize: '12px', marginTop: '4px' }}>
                      Execution ID: <code>{verificationResult.execution_id}</code> • Workflow: <code>{verificationResult.workflow_id}</code>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: 'bold',
                        padding: '4px 10px',
                        borderRadius: '4px',
                        backgroundColor:
                          verificationResult.overall_status === 'VERIFIED'
                            ? '#065f46'
                            : verificationResult.overall_status === 'FAILED'
                            ? '#991b1b'
                            : verificationResult.overall_status === 'UNKNOWN'
                            ? '#854d0e'
                            : '#374151',
                        color: '#fff',
                        textTransform: 'uppercase',
                      }}
                    >
                      OVERALL: {verificationResult.overall_status}
                    </span>
                  </div>
                </div>

                {/* Counters and Pipeline Progression */}
                <div
                  style={{
                    marginTop: '14px',
                    padding: '10px 14px',
                    backgroundColor: '#1e293b',
                    borderRadius: '6px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '12px',
                    fontSize: '13px',
                  }}
                >
                  <div style={{ color: '#cbd5e1' }}>
                    <strong style={{ color: '#38bdf8' }}>Pipeline:</strong> Execution Result → Verification Result → Deterministic Evidence
                  </div>
                  <div style={{ display: 'flex', gap: '16px' }}>
                    <span>Total Checks: <strong>{verificationResult.checks.length}</strong></span>
                    <span style={{ color: '#4ade80' }}>Verified: <strong>{verificationResult.verified_count}</strong></span>
                    <span style={{ color: '#f87171' }}>Failed: <strong>{verificationResult.failed_count}</strong></span>
                    <span style={{ color: '#fbbf24' }}>Unknown: <strong>{verificationResult.unknown_count}</strong></span>
                  </div>
                </div>
              </div>

              {/* Individual Verification Checks */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <h5 style={{ margin: '4px 0 0 0', color: '#e2e8f0', fontSize: '14px' }}>
                  Verification Checks ({verificationResult.checks.length})
                </h5>
                {verificationResult.checks.map((check) => {
                  const execStep = executionResult?.step_results.find(
                    (s) => s.execution_step_id === check.execution_step_id
                  );
                  const isExecSuccess = execStep?.status === 'SUCCESS';
                  const stepFinalState =
                    isExecSuccess && check.status === 'VERIFIED'
                      ? 'VERIFIED'
                      : isExecSuccess && check.status === 'FAILED'
                      ? 'VERIFICATION_FAILED'
                      : isExecSuccess && check.status === 'UNKNOWN'
                      ? 'EXECUTED_UNVERIFIED'
                      : check.status === 'NOT_APPLICABLE'
                      ? 'NOT_APPLICABLE'
                      : check.status;

                  return (
                    <div
                      key={check.verification_id}
                      style={{
                        backgroundColor: '#1e293b',
                        padding: '16px',
                        borderRadius: '6px',
                        border: '1px solid #334155',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '10px',
                      }}
                    >
                      {/* Check Header */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                        <div>
                          <span style={{ fontWeight: 600, color: '#f8fafc', fontSize: '14px' }}>
                            {execStep ? execStep.action_name : check.check_type}
                          </span>
                          <span style={{ fontSize: '11px', color: '#94a3b8', marginLeft: '8px' }}>
                            Target: <code>{check.target}</code>
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '4px',
                              backgroundColor: '#334155',
                              color: '#94a3b8',
                            }}
                          >
                            Strategy: {check.strategy_type}
                          </span>
                          <span
                            style={{
                              fontSize: '11px',
                              fontWeight: 'bold',
                              padding: '2px 8px',
                              borderRadius: '4px',
                              backgroundColor:
                                check.status === 'VERIFIED'
                                  ? '#065f46'
                                  : check.status === 'FAILED'
                                  ? '#991b1b'
                                  : check.status === 'UNKNOWN'
                                  ? '#854d0e'
                                  : '#374151',
                              color: '#fff',
                            }}
                          >
                            Verification: {check.status}
                          </span>
                        </div>
                      </div>

                      {/* State Distinction Cards */}
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(3, 1fr)',
                          gap: '10px',
                          backgroundColor: '#0f172a',
                          padding: '10px',
                          borderRadius: '6px',
                          fontSize: '12px',
                        }}
                      >
                        <div>
                          <div style={{ color: '#94a3b8' }}>Executor Result:</div>
                          <div style={{ fontWeight: 600, color: execStep?.status === 'SUCCESS' ? '#4ade80' : '#f87171' }}>
                            Execution: {execStep?.status || 'EXECUTED'}
                          </div>
                        </div>
                        <div>
                          <div style={{ color: '#94a3b8' }}>Verification Check:</div>
                          <div style={{ fontWeight: 600, color: check.status === 'VERIFIED' ? '#4ade80' : check.status === 'FAILED' ? '#f87171' : '#fbbf24' }}>
                            Check: {check.check_type} ({check.status})
                          </div>
                        </div>
                        <div>
                          <div style={{ color: '#94a3b8' }}>Final Step State:</div>
                          <div
                            style={{
                              fontWeight: 700,
                              color:
                                stepFinalState === 'VERIFIED'
                                  ? '#4ade80'
                                  : stepFinalState === 'VERIFICATION_FAILED'
                                  ? '#f87171'
                                  : stepFinalState === 'EXECUTED_UNVERIFIED'
                                  ? '#fbbf24'
                                  : '#cbd5e1',
                            }}
                          >
                            {stepFinalState}
                          </div>
                        </div>
                      </div>

                      {/* Expected vs Actual State */}
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '1fr 1fr',
                          gap: '10px',
                          fontSize: '12px',
                        }}
                      >
                        <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '4px' }}>
                          <strong style={{ color: '#38bdf8' }}>Expected State:</strong>
                          <pre style={{ margin: '6px 0 0 0', color: '#cbd5e1', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px' }}>
                            {typeof check.expected_state === 'object'
                              ? JSON.stringify(check.expected_state, null, 2)
                              : String(check.expected_state)}
                          </pre>
                        </div>
                        <div style={{ backgroundColor: '#0f172a', padding: '10px', borderRadius: '4px' }}>
                          <strong style={{ color: '#a78bfa' }}>Actual State:</strong>
                          <pre style={{ margin: '6px 0 0 0', color: '#cbd5e1', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px' }}>
                            {typeof check.actual_state === 'object'
                              ? JSON.stringify(check.actual_state, null, 2)
                              : String(check.actual_state)}
                          </pre>
                        </div>
                      </div>

                      {/* Reason */}
                      <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                        <strong style={{ color: '#f1f5f9' }}>Reason:</strong> {check.reason}
                      </div>

                      {/* Evidence JSON */}
                      {check.evidence && Object.keys(check.evidence).length > 0 && (
                        <div style={{ backgroundColor: '#090d16', padding: '10px', borderRadius: '4px' }}>
                          <div style={{ fontSize: '11px', fontWeight: 600, color: '#38bdf8', marginBottom: '4px' }}>
                            Deterministic Evidence Artifact:
                          </div>
                          <pre style={{ margin: 0, color: '#34d399', fontSize: '11px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {JSON.stringify(check.evidence, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Overall Evidence Summary */}
              {verificationResult.evidence && Object.keys(verificationResult.evidence).length > 0 && (
                <div
                  style={{
                    backgroundColor: '#0f172a',
                    padding: '14px',
                    borderRadius: '6px',
                    border: '1px solid #334155',
                  }}
                >
                  <h5 style={{ margin: '0 0 8px 0', color: '#38bdf8', fontSize: '13px' }}>
                    Aggregated Evidence Summary
                  </h5>
                  <pre style={{ margin: 0, color: '#94a3b8', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(verificationResult.evidence, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div
              style={{
                backgroundColor: '#1e293b',
                padding: '30px',
                textAlign: 'center',
                borderRadius: '8px',
                color: '#94a3b8',
              }}
            >
              <p style={{ margin: 0, fontSize: '15px' }}>
                No verification has been run yet for this execution.
              </p>
              <p style={{ margin: '8px 0 0 0', fontSize: '13px' }}>
                {executionResult
                  ? 'Click "Verify Execution" above to deterministically verify sandbox state and evidence.'
                  : 'Execute an approved plan first, then click "Verify Execution".'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

