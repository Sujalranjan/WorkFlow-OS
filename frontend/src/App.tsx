import React, { useEffect, useState, useCallback } from 'react';
import { ActivityEvent } from './types/event';
import { DiscoveryCandidate } from './types/discovery';
import { WorkflowDNA } from './types/dna';
import { InterpretationResponse, SemanticWorkflow } from './types/semantic';
import { CanonicalWorkflowSpec } from './types/canonical';
import { ExecutionPlan } from './types/execution';
import { EventList } from './components/EventList';
import { DiscoveryView } from './components/DiscoveryView';
import { DNAView } from './components/DNAView';
import { SemanticView } from './components/SemanticView';
import { CanonicalSpecView } from './components/CanonicalSpecView';
import { ExecutionPlanView } from './components/ExecutionPlanView';
import { WorkflowLearningView } from './components/WorkflowLearningView';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export const App: React.FC = () => {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [dnaItems, setDnaItems] = useState<WorkflowDNA[]>([]);
  const [interpretations, setInterpretations] = useState<Record<string, InterpretationResponse>>({});
  const [specifications, setSpecifications] = useState<CanonicalWorkflowSpec[]>([]);
  const [executionPlans, setExecutionPlans] = useState<ExecutionPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);

  const [isEventsLoading, setIsEventsLoading] = useState<boolean>(false);
  const [isDiscoveryLoading, setIsDiscoveryLoading] = useState<boolean>(false);
  const [isDnaLoading, setIsDnaLoading] = useState<boolean>(false);
  const [isSpecLoading, setIsSpecLoading] = useState<boolean>(false);
  const [isPlanLoading, setIsPlanLoading] = useState<boolean>(false);
  const [interpretingDnaId, setInterpretingDnaId] = useState<string | null>(null);

  const [eventsError, setEventsError] = useState<string | null>(null);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [dnaError, setDnaError] = useState<string | null>(null);

  const fetchEvents = useCallback(async () => {
    setIsEventsLoading(true);
    setEventsError(null);
    try {
      const response = await fetch(`${API_BASE}/api/events?limit=100`);
      if (!response.ok) {
        throw new Error(`Failed to fetch events: HTTP ${response.status}`);
      }
      const data: ActivityEvent[] = await response.json();
      setEvents(data);
    } catch (err: unknown) {
      setEventsError(err instanceof Error ? err.message : 'An unexpected error occurred while fetching events');
    } finally {
      setIsEventsLoading(false);
    }
  }, []);

  const fetchDiscoveryCandidates = useCallback(async () => {
    setIsDiscoveryLoading(true);
    setDiscoveryError(null);
    try {
      const response = await fetch(`${API_BASE}/api/discovery/candidates?limit=500&inactivity_timeout=120&min_occurrences=2`);
      if (!response.ok) {
        throw new Error(`Failed to fetch discovery candidates: HTTP ${response.status}`);
      }
      const data = await response.json();
      setCandidates(data.candidates || []);
    } catch (err: unknown) {
      setDiscoveryError(err instanceof Error ? err.message : 'An unexpected error occurred while running discovery');
    } finally {
      setIsDiscoveryLoading(false);
    }
  }, []);

  const fetchWorkflowDNA = useCallback(async () => {
    setIsDnaLoading(true);
    setDnaError(null);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/dna?limit=500&inactivity_timeout=120&min_occurrences=2&similarity_threshold=0.65`);
      if (!response.ok) {
        throw new Error(`Failed to fetch Workflow DNA: HTTP ${response.status}`);
      }
      const data = await response.json();
      setDnaItems(data.dna_items || []);
    } catch (err: unknown) {
      setDnaError(err instanceof Error ? err.message : 'An unexpected error occurred while extracting Workflow DNA');
    } finally {
      setIsDnaLoading(false);
    }
  }, []);

  const fetchSpecifications = useCallback(async () => {
    setIsSpecLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/specifications`);
      if (response.ok) {
        const data = await response.json();
        setSpecifications(data.specifications || []);
      }
    } catch {
      // Graceful fallback if specifications table is initially empty
    } finally {
      setIsSpecLoading(false);
    }
  }, []);

  const fetchExecutionPlans = useCallback(async () => {
    setIsPlanLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/execution-plans`);
      if (response.ok) {
        const data = await response.json();
        setExecutionPlans(data.plans || []);
        if (data.plans && data.plans.length > 0 && !selectedPlanId) {
          setSelectedPlanId(data.plans[0].execution_plan_id);
        }
      }
    } catch {
      // Graceful fallback
    } finally {
      setIsPlanLoading(false);
    }
  }, [selectedPlanId]);

  const handleCreateExecutionPlan = useCallback(async (workflowId: string) => {
    setIsPlanLoading(true);
    try {
      const response = await fetch(
        `${API_BASE}/api/workflows/specifications/${workflowId}/execution-plan`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fallback_to_sample: true }),
        }
      );
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Execution plan creation failed');
      }
      const newPlan: ExecutionPlan = await response.json();
      setExecutionPlans((prev) => [newPlan, ...prev.filter((p) => p.execution_plan_id !== newPlan.execution_plan_id)]);
      setSelectedPlanId(newPlan.execution_plan_id);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setIsPlanLoading(false);
    }
  }, []);

  const handleInterpret = useCallback(async (dnaId: string, providerType?: string) => {
    setInterpretingDnaId(dnaId);
    try {
      const params = new URLSearchParams({
        similarity_threshold: '0.65',
        min_occurrences: '2',
        inactivity_timeout: '120.0',
        force_refresh: 'true',
      });
      if (providerType) {
        params.append('provider_type', providerType);
      }
      const response = await fetch(`${API_BASE}/api/workflows/${dnaId}/interpret?${params.toString()}`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(`Interpretation request failed: HTTP ${response.status}`);
      }
      const data: InterpretationResponse = await response.json();
      setInterpretations((prev) => ({
        ...prev,
        [dnaId]: data,
      }));
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Unknown interpretation error';
      setInterpretations((prev) => ({
        ...prev,
        [dnaId]: {
          status: 'error',
          semantic_workflow: null,
          source_dna: dnaItems.find((d) => d.dna_id === dnaId)!,
          message: errMsg,
          validation_passed: false,
          validation_errors: [errMsg],
        },
      }));
    } finally {
      setInterpretingDnaId(null);
    }
  }, [dnaItems]);

  const handleGenerateSpec = useCallback(async (semanticWorkflowId: string) => {
    setIsSpecLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/${semanticWorkflowId}/specification`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(`Specification creation failed: HTTP ${response.status}`);
      }
      await fetchSpecifications();
    } finally {
      setIsSpecLoading(false);
    }
  }, [fetchSpecifications]);

  const handleApprove = useCallback(async (workflowId: string, reviewer?: string, comments?: string) => {
    setIsSpecLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/specifications/${workflowId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer, comments }),
      });
      if (!response.ok) {
        throw new Error(`Approval failed: HTTP ${response.status}`);
      }
      await fetchSpecifications();
    } finally {
      setIsSpecLoading(false);
    }
  }, [fetchSpecifications]);

  const handleReject = useCallback(async (workflowId: string, reason: string) => {
    setIsSpecLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/specifications/${workflowId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) {
        throw new Error(`Rejection failed: HTTP ${response.status}`);
      }
      await fetchSpecifications();
    } finally {
      setIsSpecLoading(false);
    }
  }, [fetchSpecifications]);

  const handleUpdateParameters = useCallback(async (
    workflowId: string,
    updates: { source_parameter: string; semantic_name: string }[]
  ) => {
    setIsSpecLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/specifications/${workflowId}/parameters`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates }),
      });
      if (!response.ok) {
        throw new Error(`Parameter update failed: HTTP ${response.status}`);
      }
      await fetchSpecifications();
    } finally {
      setIsSpecLoading(false);
    }
  }, [fetchSpecifications]);

  const refreshAll = useCallback(() => {
    fetchEvents();
    fetchDiscoveryCandidates();
    fetchWorkflowDNA();
    fetchSpecifications();
    fetchExecutionPlans();
  }, [fetchEvents, fetchDiscoveryCandidates, fetchWorkflowDNA, fetchSpecifications, fetchExecutionPlans]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Extract all valid semantic workflows from interpretations
  const validSemanticWorkflows: SemanticWorkflow[] = Object.values(interpretations)
    .filter((interp) => interp.status === 'success' && interp.semantic_workflow !== null)
    .map((interp) => interp.semantic_workflow!);

  const selectedExecutionPlan = executionPlans.find((p) => p.execution_plan_id === selectedPlanId) || executionPlans[0] || null;

  return (
    <div className="app-container">
      <header className="navbar">
        <div className="nav-brand">
          <div className="brand-icon">W</div>
          <span className="brand-title">WorkFlowOS</span>
        </div>
        <div className="nav-phase-badge">Phase 11: Workflow Learning & Reliability Intelligence</div>
      </header>

      <main className="main-content">
        <section className="hero-section">
          <div className="hero-subtitle">Desktop Automation Intelligence</div>
          <h1 className="hero-title">
            WorkFlowOS<br />
            AI-Powered Workflow Automation
          </h1>
          <p className="hero-description">
            Observes routine digital work, identifies repeated patterns, translates intent via AI,
            assembles formal canonical workflow contracts, and requires human approval before any automation.
          </p>
        </section>

        <section className="status-grid">
          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Discovery Engine</h2>
              <div className="indicator" title="Pattern Discovery Ready"></div>
            </div>
            <p className="card-text">
              Noise-tolerant sequence clustering and normalized signature matching across sessions.
            </p>
            <div className="card-meta">Phase 3: Repeated Sequence Discovery</div>
          </div>

          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Workflow DNA</h2>
              <div className="indicator" title="Workflow DNA Active"></div>
            </div>
            <p className="card-text">
              Deterministic extraction of invariant steps, variable parameters, optional steps, and precedence.
            </p>
            <div className="card-meta">Phase 4: Invariants, Variables & Evidence</div>
          </div>

          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Semantic Understanding</h2>
              <div className="indicator" title="Semantic Intent Active"></div>
            </div>
            <p className="card-text">
              Evidence-grounded LLM translation of structural DNA into validated semantic workflow intent.
            </p>
            <div className="card-meta">Phase 5: AI Intent Translation</div>
          </div>

          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Canonical Specification</h2>
              <div className="indicator" title="Governance & Approval Active"></div>
            </div>
            <p className="card-text">
              Traceable canonical contract, deterministic parameter binding, risk classification, and user approval.
            </p>
            <div className="card-meta">Phase 6: Formal Contract & Human Governance</div>
          </div>
        </section>

        {/* Phase 7 & 8 Execution Planning & Controlled Local Execution View */}
        <section
          style={{
            backgroundColor: '#0f172a',
            borderRadius: '12px',
            border: '1px solid #1e293b',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  style={{
                    backgroundColor: '#16a34a',
                    color: '#fff',
                    fontSize: '11px',
                    fontWeight: 'bold',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    textTransform: 'uppercase',
                  }}
                >
                  Phase 8 Active
                </span>
                <h2 style={{ margin: 0, color: '#f8fafc', fontSize: '20px' }}>
                  Execution Engine & Controlled Local Execution
                </h2>
              </div>
              <p style={{ margin: '6px 0 0 0', color: '#94a3b8', fontSize: '14px' }}>
                Converts approved canonical specifications into deterministic execution plans, simulates dry runs safely, and executes allowlisted local actions inside a sandbox.
              </p>
            </div>

            <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              {specifications.filter((s) => s.approval_state?.state === 'approved').length > 0 && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <select
                    id="approved-spec-select"
                    style={{
                      padding: '8px 12px',
                      backgroundColor: '#1e293b',
                      color: '#f8fafc',
                      borderRadius: '6px',
                      border: '1px solid #334155',
                      fontSize: '13px',
                    }}
                    defaultValue=""
                    disabled={isPlanLoading}
                    onChange={(e) => {
                      if (e.target.value) {
                        handleCreateExecutionPlan(e.target.value);
                        e.target.value = '';
                      }
                    }}
                  >
                    <option value="" disabled>Plan from approved workflow...</option>
                    {specifications
                      .filter((s) => s.approval_state?.state === 'approved')
                      .map((s) => (
                        <option key={s.workflow_id} value={s.workflow_id}>
                          {s.title} ({s.workflow_id})
                        </option>
                      ))}
                  </select>
                </div>
              )}

              {executionPlans.length > 0 && (
                <select
                  value={selectedPlanId || ''}
                  onChange={(e) => setSelectedPlanId(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    backgroundColor: '#1e293b',
                    color: '#f8fafc',
                    borderRadius: '6px',
                    border: '1px solid #334155',
                    fontSize: '13px',
                  }}
                >
                  {executionPlans.map((p) => (
                    <option key={p.execution_plan_id} value={p.execution_plan_id}>
                      Plan: {p.execution_plan_id} ({p.dry_run_status})
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {selectedExecutionPlan ? (
            <ExecutionPlanView
              plan={selectedExecutionPlan}
              onDryRunComplete={(updated) => {
                setExecutionPlans((prev) =>
                  prev.map((p) => (p.execution_plan_id === updated.execution_plan_id ? updated : p))
                );
              }}
              apiBaseUrl={API_BASE}
            />
          ) : (
            <div
              style={{
                padding: '30px',
                textAlign: 'center',
                backgroundColor: '#1e293b',
                borderRadius: '8px',
                color: '#94a3b8',
              }}
            >
              <p style={{ margin: 0 }}>No Execution Plans created yet.</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '13px' }}>
                Approve a Canonical Specification below, then select it from the dropdown to generate an execution plan.
              </p>
            </div>
          )}
        </section>

        {/* Phase 11 Workflow Learning & Reliability Intelligence View */}
        <WorkflowLearningView
          specifications={specifications}
          apiBaseUrl={API_BASE}
        />

        {/* Phase 6 Canonical Workflow Specification & User Approval View */}
        <CanonicalSpecView
          specifications={specifications}
          semanticWorkflows={validSemanticWorkflows}
          isLoading={isSpecLoading}
          onGenerateSpec={handleGenerateSpec}
          onApprove={handleApprove}
          onReject={handleReject}
          onUpdateParameters={handleUpdateParameters}
          onRefresh={fetchSpecifications}
        />

        {/* Phase 5 Semantic Understanding & Intent Translation View */}
        <SemanticView
          dnaItems={dnaItems}
          interpretations={interpretations}
          isLoading={interpretingDnaId !== null}
          interpretingDnaId={interpretingDnaId}
          onInterpret={handleInterpret}
        />

        {/* Phase 4 Workflow DNA View */}
        <DNAView
          dnaItems={dnaItems}
          isLoading={isDnaLoading}
          error={dnaError}
          onRefresh={fetchWorkflowDNA}
        />

        {/* Phase 3 Discovered Workflow Candidates View */}
        <DiscoveryView
          candidates={candidates}
          isLoading={isDiscoveryLoading}
          error={discoveryError}
          onRefresh={fetchDiscoveryCandidates}
        />

        {/* Live Event Stream View */}
        <EventList
          events={events}
          isLoading={isEventsLoading}
          error={eventsError}
          onRefresh={fetchEvents}
        />
      </main>

      <footer className="footer">
        WorkFlowOS &mdash; Phase 6 Canonical Workflow Specification, Risk Analysis & User Approval
      </footer>
    </div>
  );
};

export default App;
