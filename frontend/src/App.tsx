import React, { useEffect, useState, useCallback } from 'react';
import { ActivityEvent } from './types/event';
import { DiscoveryCandidate } from './types/discovery';
import { WorkflowDNA } from './types/dna';
import { InterpretationResponse, SemanticWorkflow } from './types/semantic';
import { CanonicalWorkflowSpec } from './types/canonical';
import { ExecutionPlan, ExecutionAuditRecord, VerificationResult } from './types/execution';
import { EventList } from './components/EventList';
import { DiscoveryView } from './components/DiscoveryView';
import { DNAView } from './components/DNAView';
import { SemanticView } from './components/SemanticView';
import { CanonicalSpecView } from './components/CanonicalSpecView';
import { ExecutionPlanView } from './components/ExecutionPlanView';
import { WorkflowLearningView } from './components/WorkflowLearningView';
import { PipelineNav, PipelineStageId, StageInfo, StageState } from './components/PipelineNav';
import { DemoHeader } from './components/DemoHeader';
import { GuidedDemoPanel, DemoTrackId } from './components/GuidedDemoPanel';
import { seedDemoActivity, resetDemoState, seedE2EWorkflow, SeedActivityResponse } from './services/api';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export const App: React.FC = () => {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [dnaItems, setDnaItems] = useState<WorkflowDNA[]>([]);
  const [selectedDnaId, setSelectedDnaId] = useState<string | null>(null);
  const [isExtractingDNA, setIsExtractingDNA] = useState<boolean>(false);
  const [interpretations, setInterpretations] = useState<Record<string, InterpretationResponse>>({});
  const [specifications, setSpecifications] = useState<CanonicalWorkflowSpec[]>([]);
  const [selectedSpecId, setSelectedSpecId] = useState<string | null>(null);
  const [executionPlans, setExecutionPlans] = useState<ExecutionPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);

  // Guided Demo Mode (Phase 13.5 & 16)
  const [isGuidedDemoOpen, setIsGuidedDemoOpen] = useState<boolean>(true);
  const [demoTrack, setDemoTrack] = useState<DemoTrackId>('phase16');

  // Demo Seeding & Reset Tracker (Phase 15 & 16)
  const [isSeedingActivity, setIsSeedingActivity] = useState<boolean>(false);
  const [isSeedingE2E, setIsSeedingE2E] = useState<boolean>(false);
  const [isResettingDemo, setIsResettingDemo] = useState<boolean>(false);
  const [seedResult, setSeedResult] = useState<SeedActivityResponse | null>(null);

  // Pipeline Execution / Verification Tracker
  const [lastExecutionRecord, setLastExecutionRecord] = useState<ExecutionAuditRecord | null>(null);
  const [lastVerificationResult, setLastVerificationResult] = useState<VerificationResult | null>(null);
  const [activeStage, setActiveStage] = useState<PipelineStageId>('observe');
  const [executionPlanTab, setExecutionPlanTab] = useState<
    'plan' | 'parameters' | 'strategies' | 'state_changes' | 'dry_run' | 'live_execution' | 'verification'
  >('plan');

  const [isEventsLoading, setIsEventsLoading] = useState<boolean>(false);
  const [isDiscoveryLoading, setIsDiscoveryLoading] = useState<boolean>(false);
  const [isDnaLoading, setIsDnaLoading] = useState<boolean>(false);
  const [isSpecLoading, setIsSpecLoading] = useState<boolean>(false);
  const [isPlanLoading, setIsPlanLoading] = useState<boolean>(false);
  const [interpretingDnaId, setInterpretingDnaId] = useState<string | null>(null);

  const [eventsError, setEventsError] = useState<string | null>(null);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [dnaError, setDnaError] = useState<string | null>(null);

  // Keep first candidate selected by default if available
  useEffect(() => {
    if (candidates.length > 0 && !selectedCandidateId) {
      setSelectedCandidateId(candidates[0].candidate_id);
    }
  }, [candidates, selectedCandidateId]);

  // Keep first DNA selected by default if available
  useEffect(() => {
    if (dnaItems.length > 0 && !selectedDnaId) {
      setSelectedDnaId(dnaItems[0].dna_id);
    }
  }, [dnaItems, selectedDnaId]);

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

  const handleSeedDemoActivity = useCallback(async (scenario?: string) => {
    if (isSeedingActivity) return;
    setIsSeedingActivity(true);
    try {
      const targetScenario = scenario || (demoTrack === 'safety' ? 'invoice_processing' : 'local_file_automation');
      const res = await seedDemoActivity(targetScenario);
      setSeedResult(res);
      await fetchEvents();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSeedingActivity(false);
    }
  }, [isSeedingActivity, demoTrack, fetchEvents]);

  const handleResetDemoState = useCallback(async () => {
    if (isResettingDemo) return;
    setIsResettingDemo(true);
    try {
      const res = await resetDemoState();
      // Safely reset all local UI workflow states to return to clean OBSERVE state
      setEvents([]);
      setCandidates([]);
      setSelectedCandidateId(null);
      setDnaItems([]);
      setSelectedDnaId(null);
      setInterpretations({});
      setSpecifications([]);
      setSelectedSpecId(null);
      setExecutionPlans([]);
      setSelectedPlanId(null);
      setLastExecutionRecord(null);
      setLastVerificationResult(null);
      setSeedResult(null);
      setActiveStage('observe');
      setExecutionPlanTab('plan');
      alert(`Demo state reset successfully. Cleared ${res.events_deleted} activity events and demonstration records.`);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setIsResettingDemo(false);
    }
  }, [isResettingDemo]);

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
      if (data.dna_items && data.dna_items.length > 0 && !selectedDnaId) {
        setSelectedDnaId(data.dna_items[0].dna_id);
      }
    } catch (err: unknown) {
      setDnaError(err instanceof Error ? err.message : 'An unexpected error occurred while extracting Workflow DNA');
    } finally {
      setIsDnaLoading(false);
    }
  }, [selectedDnaId]);

  const handleExtractDNA = useCallback(async (candidateId: string) => {
    if (isExtractingDNA) return;
    setIsExtractingDNA(true);
    setDnaError(null);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/dna?limit=500&inactivity_timeout=120&min_occurrences=2&similarity_threshold=0.65`);
      if (!response.ok) {
        throw new Error(`Failed to extract Workflow DNA: HTTP ${response.status}`);
      }
      const data = await response.json();
      const items: WorkflowDNA[] = data.dna_items || [];
      setDnaItems(items);

      // Find the DNA corresponding to this candidate
      const matched = items.find(
        (d) => d.source_candidate_id === candidateId || d.dna_id === `dna-${candidateId}`
      );
      const targetId = matched ? matched.dna_id : (items[0]?.dna_id || null);
      if (targetId) {
        setSelectedDnaId(targetId);
      }
      setSelectedCandidateId(candidateId);
    } catch (err: unknown) {
      setDnaError(err instanceof Error ? err.message : 'An unexpected error occurred while extracting Workflow DNA');
    } finally {
      setIsExtractingDNA(false);
    }
  }, [isExtractingDNA]);

  const handleNavigateToSemantic = useCallback((dnaId: string) => {
    setSelectedDnaId(dnaId);
    setActiveStage('understand');
    setTimeout(() => {
      const target = document.getElementById(`semantic-dna-${dnaId}`) || document.getElementById('stage-understand');
      if (target) {
        target.scrollIntoView({ behavior: 'smooth' });
      }
    }, 50);
  }, []);

  const handleNavigateToDNA = useCallback((dnaId: string) => {
    setSelectedDnaId(dnaId);
    setTimeout(() => {
      const target = document.getElementById(`dna-card-${dnaId}`) || document.getElementById('stage-discover');
      if (target) {
        target.scrollIntoView({ behavior: 'smooth' });
      }
    }, 50);
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

  const handleSeedE2EWorkflow = useCallback(async () => {
    if (isSeedingE2E) return;
    setIsSeedingE2E(true);
    try {
      const res = await seedE2EWorkflow(false);
      await fetchSpecifications();
      setSelectedSpecId(res.workflow_id);
      setActiveStage('approve');
      const targetElement = document.getElementById('stage-approve');
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth' });
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSeedingE2E(false);
    }
  }, [isSeedingE2E, fetchSpecifications]);

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
      setActiveStage('dry_run');
      setExecutionPlanTab('plan');
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
      setActiveStage('understand');
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
      const newSpec: CanonicalWorkflowSpec = await response.json();
      await fetchSpecifications();
      setSelectedSpecId(newSpec.workflow_id);
      setActiveStage('approve');
      const targetElement = document.getElementById('stage-approve');
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth' });
      }
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

  // Pipeline stage navigation handler
  const handleSelectStage = useCallback((stageId: PipelineStageId) => {
    setActiveStage(stageId);
    if (stageId === 'dry_run') {
      setExecutionPlanTab('dry_run');
    } else if (stageId === 'execute') {
      setExecutionPlanTab('live_execution');
    } else if (stageId === 'verify') {
      setExecutionPlanTab('verification');
    }

    const targetElementId =
      stageId === 'dry_run' || stageId === 'execute' || stageId === 'verify'
        ? 'stage-execution'
        : `stage-${stageId}`;

    const targetElement = document.getElementById(targetElementId);
    if (targetElement) {
      targetElement.scrollIntoView({ behavior: 'smooth' });
    }
  }, []);

  // Compute honest, derived stage states
  const approvedSpecs = specifications.filter((s) => s.approval_state?.state === 'approved');
  const simulatedPlans = executionPlans.filter((p) => p.dry_run_status?.toLowerCase() === 'simulated');

  const getStageState = (stageId: PipelineStageId): StageState => {
    if (activeStage === stageId) return 'current';

    switch (stageId) {
      case 'observe':
        return events.length > 0 ? 'completed' : 'current';
      case 'discover':
        return (selectedDnaId || dnaItems.length > 0)
          ? 'completed'
          : candidates.length > 0
          ? 'pending'
          : 'pending';
      case 'understand':
        return validSemanticWorkflows.length > 0
          ? 'completed'
          : 'pending';
      case 'approve':
        if (approvedSpecs.length > 0) return 'completed';
        if (specifications.some((s) => s.approval_state?.state === 'rejected')) return 'blocked';
        return specifications.length > 0 ? 'pending' : 'pending';
      case 'dry_run':
        if (simulatedPlans.length > 0) return 'completed';
        if (executionPlans.some((p) => p.dry_run_status?.toLowerCase() === 'simulation_blocked')) return 'blocked';
        return approvedSpecs.length > 0 ? 'pending' : 'blocked';
      case 'execute':
        if (lastExecutionRecord?.status === 'COMPLETED') return 'completed';
        if (lastExecutionRecord?.status === 'BLOCKED' || lastExecutionRecord?.status === 'FAILED') return 'blocked';
        return simulatedPlans.length > 0 ? 'pending' : 'blocked';
      case 'verify':
        if (lastVerificationResult?.overall_status === 'VERIFIED') return 'completed';
        if (lastVerificationResult?.overall_status === 'FAILED') return 'blocked';
        return lastExecutionRecord?.status === 'COMPLETED' ? 'pending' : 'blocked';
      case 'learn':
        return lastVerificationResult || lastExecutionRecord ? 'completed' : 'pending';
      default:
        return 'pending';
    }
  };

  const stages: StageInfo[] = [
    {
      id: 'observe',
      number: 1,
      label: 'OBSERVE',
      subtitle: 'Desktop Events',
      state: getStageState('observe'),
      stateDetail: events.length > 0 ? `${events.length} events logged` : 'Awaiting activity',
      badge: events.length > 0 ? `${events.length}` : undefined,
    },
    {
      id: 'discover',
      number: 2,
      label: 'DISCOVER',
      subtitle: 'Patterns & DNA',
      state: getStageState('discover'),
      stateDetail:
        selectedDnaId && dnaItems.length > 0
          ? `${dnaItems.length} DNA extracted &bull; Selected: ${selectedDnaId}`
          : candidates.length > 0
          ? `${candidates.length} candidate(s) discovered`
          : 'Clustering patterns',
      badge: selectedDnaId ? 'DNA ✓' : candidates.length > 0 ? `${candidates.length}` : undefined,
    },
    {
      id: 'understand',
      number: 3,
      label: 'UNDERSTAND',
      subtitle: 'Gemini Semantic Intent',
      state: getStageState('understand'),
      stateDetail:
        validSemanticWorkflows.length > 0
          ? `${validSemanticWorkflows.length} intent model(s)`
          : selectedDnaId
          ? `Ready to interpret ${selectedDnaId}`
          : 'AI translation',
      badge: validSemanticWorkflows.length > 0 ? `${validSemanticWorkflows.length}` : undefined,
    },
    {
      id: 'approve',
      number: 4,
      label: 'APPROVE',
      subtitle: 'Governance & Contract',
      state: getStageState('approve'),
      stateDetail:
        approvedSpecs.length > 0
          ? `${approvedSpecs.length} approved`
          : specifications.length > 0
          ? `${specifications.length} pending review`
          : 'Awaiting spec',
      badge: approvedSpecs.length > 0 ? '✓' : undefined,
    },
    {
      id: 'dry_run',
      number: 5,
      label: 'DRY RUN',
      subtitle: 'Zero Side-Effect Sim',
      state: getStageState('dry_run'),
      stateDetail:
        simulatedPlans.length > 0
          ? `${simulatedPlans.length} simulated`
          : approvedSpecs.length > 0
          ? 'Ready to simulate'
          : 'Needs approval',
      badge: simulatedPlans.length > 0 ? '0 side-effects' : undefined,
    },
    {
      id: 'execute',
      number: 6,
      label: 'EXECUTE',
      subtitle: 'Sandbox / Gmail API',
      state: getStageState('execute'),
      stateDetail:
        lastExecutionRecord?.status === 'COMPLETED'
          ? 'Completed'
          : lastExecutionRecord?.status === 'BLOCKED'
          ? 'Blocked by policy'
          : simulatedPlans.length > 0
          ? 'Ready for sandbox'
          : 'Needs dry-run',
      badge: lastExecutionRecord ? lastExecutionRecord.status : undefined,
    },
    {
      id: 'verify',
      number: 7,
      label: 'VERIFY',
      subtitle: 'Deterministic Evidence',
      state: getStageState('verify'),
      stateDetail:
        lastVerificationResult?.overall_status === 'VERIFIED'
          ? 'Verified success'
          : lastVerificationResult?.overall_status === 'FAILED'
          ? 'Verification failed'
          : lastExecutionRecord?.status === 'COMPLETED'
          ? 'Ready to verify'
          : 'Needs execution',
      badge: lastVerificationResult ? lastVerificationResult.overall_status : undefined,
    },
    {
      id: 'learn',
      number: 8,
      label: 'LEARN',
      subtitle: 'Reliability Intelligence',
      state: getStageState('learn'),
      stateDetail: 'Profiles & advisory',
    },
  ];

  return (
    <div className="app-container">
      <nav className="navbar">
        <div className="nav-brand">
          <div className="brand-icon">W</div>
          <span className="brand-title">WorkFlowOS</span>
        </div>
        <div className="nav-phase-badge">Phase 15: Hackathon Demo Packaging</div>
      </nav>

      <main className="main-content">
        {/* Top-Level Demo Header with Capability Transparency */}
        <DemoHeader
          eventCount={events.length}
          approvedSpecCount={approvedSpecs.length}
          simulatedPlanCount={simulatedPlans.length}
          verifiedExecutionCount={lastVerificationResult?.overall_status === 'VERIFIED' ? 1 : 0}
          onRefreshAll={refreshAll}
          isLoading={isEventsLoading || isDiscoveryLoading || isDnaLoading || isSpecLoading || isPlanLoading}
          isGuidedDemoOpen={isGuidedDemoOpen}
          onToggleGuidedDemo={() => setIsGuidedDemoOpen((prev) => !prev)}
          onResetDemo={handleResetDemoState}
          isResetting={isResettingDemo}
        />

        {/* Phase 13.5: Guided Hackathon Demo Mode Controller Panel */}
        {isGuidedDemoOpen && (
          <GuidedDemoPanel
            track={demoTrack}
            onSelectTrack={setDemoTrack}
            onClose={() => setIsGuidedDemoOpen(false)}
            eventsCount={events.length}
            candidatesCount={candidates.length}
            dnaCount={dnaItems.length}
            semanticWorkflowCount={validSemanticWorkflows.length}
            specifications={specifications}
            approvedSpecsCount={approvedSpecs.length}
            executionPlansCount={executionPlans.length}
            simulatedPlansCount={simulatedPlans.length}
            lastExecutionStatus={lastExecutionRecord?.status || null}
            lastVerificationStatus={lastVerificationResult?.overall_status || null}
            selectedCandidateId={selectedCandidateId}
            selectedDnaId={selectedDnaId}
            selectedSpecId={selectedSpecId}
            onSeedActivity={handleSeedDemoActivity}
            onSeedE2E={handleSeedE2EWorkflow}
            onRunDiscovery={fetchDiscoveryCandidates}
            onExtractDNA={handleExtractDNA}
            onNavigateToStage={handleSelectStage}
            isSeeding={isSeedingActivity}
            isSeedingE2E={isSeedingE2E}
            isDiscoveryLoading={isDiscoveryLoading}
            isDnaLoading={isDnaLoading}
            isExtractingDNA={isExtractingDNA}
            isSpecLoading={isSpecLoading}
            isPlanLoading={isPlanLoading}
          />
        )}

        {/* Sticky Unified Pipeline Navigation */}
        <PipelineNav
          stages={stages}
          activeStage={activeStage}
          onSelectStage={handleSelectStage}
        />

        {/* ================================================================= */}
        {/* STAGE 1: OBSERVE — Live Desktop Activity Event Stream             */}
        {/* ================================================================= */}
        <section id="stage-observe" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stage 1</span>
              <span className="stage-section-name">OBSERVE — Desktop Activity Capture</span>
            </div>
            <span className="stage-section-hint">Raw event stream from Windows hooks & collectors</span>
          </div>

          <EventList
            events={events}
            isLoading={isEventsLoading}
            error={eventsError}
            onRefresh={fetchEvents}
            onSeedDemoActivity={handleSeedDemoActivity}
            isSeeding={isSeedingActivity}
            seedResult={seedResult}
            onNavigateToDiscover={() => handleSelectStage('discover')}
          />
        </section>

        {/* ================================================================= */}
        {/* STAGE 2: DISCOVER — Segmentation & Workflow DNA Extraction         */}
        {/* ================================================================= */}
        <section id="stage-discover" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stage 2</span>
              <span className="stage-section-name">DISCOVER — Repeated Patterns & Workflow DNA</span>
            </div>
            <span className="stage-section-hint">Noise-tolerant clustering, invariants & parameter variance</span>
          </div>

          <DiscoveryView
            candidates={candidates}
            isLoading={isDiscoveryLoading}
            error={discoveryError}
            onRefresh={fetchDiscoveryCandidates}
            selectedCandidateId={selectedCandidateId}
            onSelectCandidate={setSelectedCandidateId}
            onExtractDNA={handleExtractDNA}
            isExtractingDNA={isExtractingDNA}
            dnaItems={dnaItems}
            onNavigateToSemantic={handleNavigateToSemantic}
            onNavigateToDNA={handleNavigateToDNA}
          />

          <DNAView
            dnaItems={dnaItems}
            isLoading={isDnaLoading || isExtractingDNA}
            error={dnaError}
            onRefresh={fetchWorkflowDNA}
            selectedDnaId={selectedDnaId}
            onSelectDnaId={setSelectedDnaId}
            onNavigateToSemantic={handleNavigateToSemantic}
          />
        </section>

        {/* ================================================================= */}
        {/* STAGE 3: UNDERSTAND — Gemini Semantic Interpretation              */}
        {/* ================================================================= */}
        <section id="stage-understand" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stage 3</span>
              <span className="stage-section-name">UNDERSTAND — Semantic Intent Translation</span>
            </div>
            <span className="stage-section-hint">Evidence-grounded translation: Ground Truth vs Gemini Intent</span>
          </div>

          <SemanticView
            dnaItems={dnaItems}
            interpretations={interpretations}
            isLoading={interpretingDnaId !== null}
            interpretingDnaId={interpretingDnaId}
            onInterpret={handleInterpret}
            selectedDnaId={selectedDnaId}
            onSelectDnaId={setSelectedDnaId}
            onSpecificationCreated={async (newSpec) => {
              await fetchSpecifications();
              setSelectedSpecId(newSpec.workflow_id);
              handleSelectStage('approve');
            }}
            onNavigateToApprove={(workflowId) => {
              setSelectedSpecId(workflowId);
              handleSelectStage('approve');
            }}
            existingSpecifications={specifications}
          />
        </section>

        {/* ================================================================= */}
        {/* STAGE 4: APPROVE — Canonical Specification & Governance           */}
        {/* ================================================================= */}
        <section id="stage-approve" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stage 4</span>
              <span className="stage-section-name">APPROVE — Canonical Specification & Governance</span>
            </div>
            <span className="stage-section-hint">Deterministic contract, risk classification & human approval gate</span>
          </div>

          <CanonicalSpecView
            specifications={specifications}
            semanticWorkflows={validSemanticWorkflows}
            isLoading={isSpecLoading}
            onGenerateSpec={handleGenerateSpec}
            onApprove={handleApprove}
            onReject={handleReject}
            onUpdateParameters={handleUpdateParameters}
            onRefresh={fetchSpecifications}
            selectedWorkflowId={selectedSpecId}
            onSelectWorkflowId={setSelectedSpecId}
          />
        </section>

        {/* ================================================================= */}
        {/* STAGES 5, 6, 7: DRY RUN, EXECUTE, VERIFY                          */}
        {/* ================================================================= */}
        <section id="stage-execution" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stages 5–7</span>
              <span className="stage-section-name">DRY RUN, EXECUTE & VERIFY — Safe Execution Engine</span>
            </div>
            <span className="stage-section-hint">Provably side-effect free dry runs, controlled sandbox / Gmail API, post-execution verification</span>
          </div>

          <div
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
                    Guarded Execution Engine
                  </span>
                  <h2 style={{ margin: 0, color: '#f8fafc', fontSize: '20px' }}>
                    Multi-Strategy Execution & Verification
                  </h2>
                </div>
                <p style={{ margin: '6px 0 0 0', color: '#94a3b8', fontSize: '14px' }}>
                  Converts approved canonical specifications into deterministic plans. Dry run guarantees 0 side-effects. Live execution strictly limited to Controlled Local sandbox and Read-Only Gmail API search.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                {approvedSpecs.length > 0 && (
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
                      {approvedSpecs.map((s) => (
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
                externalActiveTab={executionPlanTab}
                onExecutionComplete={(record) => {
                  setLastExecutionRecord(record);
                  setActiveStage('verify');
                }}
                onVerificationComplete={(result) => {
                  setLastVerificationResult(result);
                  setActiveStage('learn');
                }}
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
                  Approve a Canonical Specification in Stage 4, then select it from the dropdown above to generate an execution plan.
                </p>
              </div>
            )}
          </div>
        </section>

        {/* ================================================================= */}
        {/* STAGE 8: LEARN — Workflow Learning & Reliability Intelligence    */}
        {/* ================================================================= */}
        <section id="stage-learn" className="stage-section-wrapper">
          <div className="stage-section-banner">
            <div className="stage-section-banner-title">
              <span className="stage-section-number">Stage 8</span>
              <span className="stage-section-name">LEARN — Workflow Learning & Reliability Intelligence</span>
            </div>
            <span className="stage-section-hint">Deterministic aggregation of execution audits and verification evidence into reliability profiles</span>
          </div>

          <WorkflowLearningView
            specifications={specifications}
            apiBaseUrl={API_BASE}
          />
        </section>
      </main>

      <footer className="footer">
        WorkFlowOS &mdash; Phase 13.1 Unified Workflow Pipeline UI Shell &bull; Controlled Local Sandbox &amp; Read-Only Gmail API
      </footer>
    </div>
  );
};

export default App;
