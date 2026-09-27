import React, { useState } from 'react';
import { PipelineStageId } from './PipelineNav';
import { CanonicalWorkflowSpec } from '../types/canonical';

export type DemoTrackId = 'local' | 'safety' | 'gmail';

export interface GuidedDemoPanelProps {
  track: DemoTrackId;
  onSelectTrack: (track: DemoTrackId) => void;
  onClose: () => void;
  // State inputs
  eventsCount: number;
  candidatesCount: number;
  dnaCount: number;
  semanticWorkflowCount: number;
  specifications: CanonicalWorkflowSpec[];
  approvedSpecsCount: number;
  executionPlansCount: number;
  simulatedPlansCount: number;
  lastExecutionStatus: string | null;
  lastVerificationStatus: string | null;
  // Specific selection targets
  selectedCandidateId: string | null;
  selectedDnaId: string | null;
  selectedSpecId: string | null;
  // Action callbacks
  onSeedActivity: (scenario?: string) => void;
  onRunDiscovery: () => void;
  onExtractDNA: (candidateId: string) => void;
  onNavigateToStage: (stageId: PipelineStageId) => void;
  // Loading flags
  isSeeding: boolean;
  isDiscoveryLoading: boolean;
  isDnaLoading: boolean;
  isExtractingDNA: boolean;
  isSpecLoading: boolean;
  isPlanLoading: boolean;
}

export const GuidedDemoPanel: React.FC<GuidedDemoPanelProps> = ({
  track,
  onSelectTrack,
  onClose,
  eventsCount,
  candidatesCount,
  dnaCount,
  semanticWorkflowCount,
  specifications,
  approvedSpecsCount,
  executionPlansCount,
  simulatedPlansCount,
  lastExecutionStatus,
  lastVerificationStatus,
  selectedCandidateId,
  selectedDnaId,
  selectedSpecId,
  onSeedActivity,
  onRunDiscovery,
  onExtractDNA,
  onNavigateToStage,
  isSeeding,
  isDiscoveryLoading,
  isDnaLoading,
  isExtractingDNA,
  isSpecLoading,
  isPlanLoading,
}) => {
  const [isMinimized, setIsMinimized] = useState<boolean>(false);

  // Check if a Gmail specification is loaded
  const gmailSpec = specifications.find(
    (s) =>
      s.workflow_id.toLowerCase().includes('gmail') ||
      s.title.toLowerCase().includes('gmail') ||
      s.steps.some((st) => st.application.toLowerCase() === 'gmail')
  );

  // Helper to determine the current guidance step in Track A
  const getTrackAGuidance = () => {
    if (eventsCount === 0) {
      const isSafety = track === 'safety';
      return {
        stageId: 'observe' as PipelineStageId,
        stepNumber: 1,
        stepTitle: isSafety
          ? 'OBSERVE — Multi-App Safety Policy Seeding'
          : 'OBSERVE — Local File Routine Seeding',
        badge: isSafety ? 'Cross-App Seeding' : 'Local Routine Seeding',
        status: 'Action Required',
        statusType: 'action-needed',
        description: isSafety
          ? 'WorkFlowOS begins with zero-privilege desktop activity capture. Seed multi-app events (Gmail, Excel, CRM, Slack) to demonstrate that the Execution Policy Engine safely BLOCKS unsupported external actions at Stage 6.'
          : 'WorkFlowOS begins with zero-privilege desktop activity capture. For a complete end-to-end local automation, seed synthetic events representing a repetitive transaction reconciliation and archiving routine across local filesystem storage.',
        actionLabel: isSeeding
          ? 'Seeding Events...'
          : isSafety
          ? 'Seed Multi-App Safety Activity'
          : 'Seed Local Workflow Activity',
        actionDisabled: isSeeding,
        onAction: () => {
          onSeedActivity(isSafety ? 'invoice_processing' : 'local_file_automation');
          onNavigateToStage('observe');
        },
        jumpStageId: 'observe' as PipelineStageId,
        isHardStop: false,
        capabilityNote: isSafety
          ? 'Policy Safety Demo: Validates that WorkFlowOS refuses to execute unsupported external tools (CRM, Slack)'
          : 'Primary Track A: Safe, allowlisted local filesystem routines executing 100% inside sandbox',
      };
    }

    if (candidatesCount === 0) {
      return {
        stageId: 'discover' as PipelineStageId,
        stepNumber: 2,
        stepTitle: 'DISCOVER — Pattern Clustering & Repetition Detection',
        badge: 'Sequence Clustering',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Activity events are logged. Now run deterministic sequence clustering to detect repeated task patterns across sessions with similarity scoring.',
        actionLabel: isDiscoveryLoading ? 'Analyzing Patterns...' : 'Run Discovery Analysis',
        actionDisabled: isDiscoveryLoading,
        onAction: () => {
          onRunDiscovery();
          onNavigateToStage('discover');
        },
        jumpStageId: 'discover' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Noise-tolerant sequence alignment and temporal session boundary segmentation',
      };
    }

    if (dnaCount === 0) {
      return {
        stageId: 'discover' as PipelineStageId,
        stepNumber: 2,
        stepTitle: 'DISCOVER — Workflow DNA Extraction',
        badge: 'Structural Invariants',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Repeated candidate pattern discovered. Extract deterministic Workflow DNA: invariant steps (100% frequency), variable parameters (filenames), ordering constraints, and empirical evidence.',
        actionLabel: isExtractingDNA || isDnaLoading ? 'Extracting DNA...' : 'Extract Workflow DNA →',
        actionDisabled: isExtractingDNA || isDnaLoading,
        onAction: () => {
          if (selectedCandidateId) {
            onExtractDNA(selectedCandidateId);
          }
          onNavigateToStage('discover');
        },
        jumpStageId: 'discover' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Deterministic Workflow DNA extraction from repeated activity evidence',
      };
    }

    if (semanticWorkflowCount === 0) {
      return {
        stageId: 'understand' as PipelineStageId,
        stepNumber: 3,
        stepTitle: 'UNDERSTAND — Gemini Semantic Intent Translation',
        badge: 'AI Grounding',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Workflow DNA is ready. Translate empirical structure into operational intent using LLM inference (Gemini API or offline Mock). Structural variables are mapped into semantic entities with grounded evidence citations.',
        actionLabel: 'Go to Semantic Understanding →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('understand'),
        jumpStageId: 'understand' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'LLM inference strictly constrained by deterministic Workflow DNA ground truth',
      };
    }

    if (specifications.length === 0) {
      return {
        stageId: 'understand' as PipelineStageId,
        stepNumber: 3,
        stepTitle: 'UNDERSTAND — Canonical Contract Assembly',
        badge: 'Contract Synthesis',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Semantic intent validated. Synthesize a formal Canonical Workflow Specification with step-level risk classification and parameter bindings for governance review.',
        actionLabel: 'Generate Canonical Specification (Stage 3)',
        actionDisabled: isSpecLoading,
        onAction: () => onNavigateToStage('understand'),
        jumpStageId: 'understand' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Synthesizes immutable workflow contract with explicit step risk annotations',
      };
    }

    if (approvedSpecsCount === 0) {
      return {
        stageId: 'approve' as PipelineStageId,
        stepNumber: 4,
        stepTitle: 'APPROVE — Human Governance Gate',
        badge: 'Human-in-the-Loop',
        status: '🛑 HARD STOP — Human Approval Required',
        statusType: 'hard-stop',
        description:
          'WorkFlowOS will not execute this workflow until a human reviews and approves the canonical specification. Inspect the formal steps, parameter bindings, and risk analysis in Stage 4.',
        actionLabel: 'Review Workflow Specification →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('approve'),
        jumpStageId: 'approve' as PipelineStageId,
        isHardStop: true,
        capabilityNote: 'Zero-execution guarantee: Execution engine rejects unapproved specifications',
      };
    }

    if (executionPlansCount === 0) {
      return {
        stageId: 'approve' as PipelineStageId,
        stepNumber: 4,
        stepTitle: 'APPROVE — Execution Plan Generation',
        badge: 'Plan Assembly',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Specification is approved! Convert the approved governance contract into an executable multi-strategy plan with parameter resolution and policy binding.',
        actionLabel: 'Generate Execution Plan in Stage 4/5 →',
        actionDisabled: isPlanLoading,
        onAction: () => onNavigateToStage('dry_run'),
        jumpStageId: 'dry_run' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Binds parameters and assigns execution strategies per step',
      };
    }

    if (simulatedPlansCount === 0) {
      return {
        stageId: 'dry_run' as PipelineStageId,
        stepNumber: 5,
        stepTitle: 'DRY RUN — Zero Side-Effect Simulation',
        badge: 'Simulation',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Execution plan ready. Run provably side-effect free dry run simulation to validate parameter substitutions and safety policies without touching real resources.',
        actionLabel: 'Go to Dry Run Simulation →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('dry_run'),
        jumpStageId: 'dry_run' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Provably guarantees 0 real side-effects during simulation',
      };
    }

    if (track === 'safety' && lastExecutionStatus === 'BLOCKED') {
      return {
        stageId: 'execute' as PipelineStageId,
        stepNumber: 6,
        stepTitle: 'EXECUTE — Policy Boundary Enforced (BLOCKED)',
        badge: 'Safety Enforced',
        status: '🛡️ Safety Guardrail Active — Execution BLOCKED',
        statusType: 'success',
        description:
          'Safety demonstration complete! WorkFlowOS correctly identified unsupported external application executors (CRM, Slack) and safely BLOCKED execution at the policy boundary. No unauthorized external actions were attempted.',
        actionLabel: 'Switch to Track A (Complete Local Workflow) →',
        actionDisabled: false,
        onAction: () => onSelectTrack('local'),
        jumpStageId: 'execute' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Policy Boundary: Execution strictly refused for unimplemented external integrations',
      };
    }

    if (lastExecutionStatus !== 'COMPLETED') {
      const isSafety = track === 'safety';
      return {
        stageId: 'execute' as PipelineStageId,
        stepNumber: 6,
        stepTitle: isSafety
          ? 'EXECUTE — Multi-App Execution Policy Test'
          : 'EXECUTE — Controlled Local Sandbox Execution',
        badge: 'Operator Action Required',
        status: '⚠️ Explicit Operator Trigger Required',
        statusType: 'warning',
        description: isSafety
          ? 'Review the multi-app execution plan. When you trigger Execute, the Execution Policy Engine will evaluate CRM and Slack steps against allowlisted executors and safely return BLOCKED.'
          : 'Execution is ready. Review the execution plan and choose Execute when you are ready. Live execution is strictly limited to the controlled local sandbox directory.',
        actionLabel: 'Open Execution Console (Stage 6) →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('execute'),
        jumpStageId: 'execute' as PipelineStageId,
        isHardStop: false,
        capabilityNote: isSafety
          ? 'Safety Test: Demonstrates execution refusal when workflows require unimplemented external executors'
          : 'Strictly restricted to allowlisted filesystem sandbox. No mouse/keyboard emulation.',
      };
    }

    if (lastVerificationStatus !== 'VERIFIED') {
      return {
        stageId: 'verify' as PipelineStageId,
        stepNumber: 7,
        stepTitle: 'VERIFY — Post-Execution Evidence Audit',
        badge: 'Evidence Verification',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Execution completed! Verification checks whether the expected state actually occurred by analyzing independent filesystem evidence and hashing created artifacts.',
        actionLabel: 'Open Verification Console (Stage 7) →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('verify'),
        jumpStageId: 'verify' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Post-execution state audit independent of execution return values',
      };
    }

    return {
      stageId: 'learn' as PipelineStageId,
      stepNumber: 8,
      stepTitle: 'LEARN — Reliability Intelligence & Learning',
      badge: 'Full Chain Verified',
      status: '✓ Pipeline Complete & Verified',
      statusType: 'success',
      description:
        'Guided demo complete! Learning aggregates execution audits and verification evidence into deterministic reliability profiles and advisory suggestions without self-modifying code.',
      actionLabel: 'View Reliability Profile (Stage 8) →',
      actionDisabled: false,
      onAction: () => onNavigateToStage('learn'),
      jumpStageId: 'learn' as PipelineStageId,
      isHardStop: false,
      capabilityNote: 'Deterministic reliability profiling and parameter advisory suggestions',
    };
  };

  // Helper for Track B (Gmail Read-Only)
  const getTrackBGuidance = () => {
    if (!gmailSpec) {
      return {
        stageId: 'approve' as PipelineStageId,
        stepNumber: 4,
        stepTitle: 'GMAIL TRACK — Specification Configuration',
        badge: 'Official Gmail API',
        status: 'External Spec Setup',
        statusType: 'warning',
        description:
          'Track B demonstrates official Gmail API read-only search under the locked gmail.readonly OAuth scope. To demonstrate this track, run "python desktop-agent/desktop_agent/demo_phase12_live.py" to load the approved Gmail specification and live OAuth credentials.',
        actionLabel: 'Switch to Track A (Local Sandbox)',
        actionDisabled: false,
        onAction: () => onSelectTrack('local'),
        jumpStageId: 'observe' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Official Google OAuth 2.0 with minimal read-only scope (https://www.googleapis.com/auth/gmail.readonly)',
      };
    }

    const isGmailApproved = gmailSpec.approval_state?.state === 'approved';

    if (!isGmailApproved) {
      return {
        stageId: 'approve' as PipelineStageId,
        stepNumber: 4,
        stepTitle: 'GMAIL TRACK — Human Governance Approval Gate',
        badge: 'OAuth Read-Only',
        status: '🛑 HARD STOP — Human Approval Required',
        statusType: 'hard-stop',
        description:
          'WorkFlowOS will not execute Gmail API queries until an operator reviews and approves the canonical Gmail specification. Operation is strictly search_email.',
        actionLabel: 'Review Gmail Specification →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('approve'),
        jumpStageId: 'approve' as PipelineStageId,
        isHardStop: true,
        capabilityNote: 'Locked Scope: gmail.readonly. Zero email sending, modification, or deletion allowed.',
      };
    }

    if (simulatedPlansCount === 0) {
      return {
        stageId: 'dry_run' as PipelineStageId,
        stepNumber: 5,
        stepTitle: 'GMAIL TRACK — Zero API Call Dry Run',
        badge: 'Zero API Calls',
        status: 'Action Required',
        statusType: 'action-needed',
        description:
          'Dry run verifies Gmail parameters and query syntax ("from:billing@supplier.com invoice") with 0 external API calls.',
        actionLabel: 'Go to Dry Run Simulation →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('dry_run'),
        jumpStageId: 'dry_run' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Guarantees zero network calls or credential requests during dry-run simulation',
      };
    }

    if (lastExecutionStatus !== 'COMPLETED') {
      return {
        stageId: 'execute' as PipelineStageId,
        stepNumber: 6,
        stepTitle: 'GMAIL TRACK — Live API Search Execution',
        badge: 'Official API Search',
        status: '⚠️ Operator Action Required',
        statusType: 'warning',
        description:
          'Execution is ready. Review the execution plan and choose Execute when you are ready. Queries the real Gmail messages.list API endpoint.',
        actionLabel: 'Open Gmail Execution Console →',
        actionDisabled: false,
        onAction: () => onNavigateToStage('execute'),
        jumpStageId: 'execute' as PipelineStageId,
        isHardStop: false,
        capabilityNote: 'Executes official search_email query via GmailApiExecutor under locked scope',
      };
    }

    return {
      stageId: 'verify' as PipelineStageId,
      stepNumber: 7,
      stepTitle: 'GMAIL TRACK — Verification & Audit Evidence',
      badge: 'API Evidence',
      status: '✓ Gmail API Search Verified',
      statusType: 'success',
      description:
        'Live Gmail search verified! Verification audited query results and message identifiers without storing raw email contents or secrets.',
      actionLabel: 'View Gmail Verification & Reliability →',
      actionDisabled: false,
      onAction: () => onNavigateToStage('verify'),
      jumpStageId: 'verify' as PipelineStageId,
      isHardStop: false,
      capabilityNote: 'Zero secrets or credential persistence in audit logs',
    };
  };

  const guidance = track === 'gmail' ? getTrackBGuidance() : getTrackAGuidance();

  const pipelineStages: { id: PipelineStageId; label: string; number: number }[] = [
    { id: 'observe', label: 'OBSERVE', number: 1 },
    { id: 'discover', label: 'DISCOVER', number: 2 },
    { id: 'understand', label: 'UNDERSTAND', number: 3 },
    { id: 'approve', label: 'APPROVE', number: 4 },
    { id: 'dry_run', label: 'DRY RUN', number: 5 },
    { id: 'execute', label: 'EXECUTE', number: 6 },
    { id: 'verify', label: 'VERIFY', number: 7 },
    { id: 'learn', label: 'LEARN', number: 8 },
  ];

  if (isMinimized) {
    return (
      <div className="guided-demo-minimized-bar">
        <div className="minimized-left">
          <span className="guide-compass-icon">🧭</span>
          <strong>Guided Hackathon Demo:</strong>
          <span className="minimized-track-badge">
            {track === 'local'
              ? 'Track A: Local Sandbox'
              : track === 'safety'
              ? 'Track A: Safety Policy'
              : 'Track B: Gmail Read-Only'}
          </span>
          <span className={`minimized-status-badge ${guidance.statusType}`}>
            {guidance.status}
          </span>
          <span className="minimized-step-text">
            Step {guidance.stepNumber}/8: {guidance.stepTitle.split('—')[0]}
          </span>
        </div>
        <div className="minimized-actions">
          <button
            type="button"
            className="btn-minimized-action"
            onClick={guidance.onAction}
            disabled={guidance.actionDisabled}
          >
            {guidance.actionLabel}
          </button>
          <button
            type="button"
            className="btn-minimized-expand"
            onClick={() => setIsMinimized(false)}
            title="Expand Guided Demo Panel"
          >
            Expand ↗
          </button>
          <button
            type="button"
            className="btn-minimized-close"
            onClick={onClose}
            title="Exit Guided Demo"
          >
            ✕
          </button>
        </div>
      </div>
    );
  }

  return (
    <aside className="guided-demo-panel" aria-label="Guided Hackathon Demo Controller">
      {/* Top Controller Bar */}
      <div className="guided-panel-top">
        <div className="guided-title-group">
          <div className="guided-brand-tag">
            <span className="guide-compass-icon">🧭</span>
            <span>Guided Hackathon Demonstration Mode</span>
          </div>
          <span className="guided-human-loop-tag">Human-in-the-Loop Governance</span>
        </div>

        {/* Demo Track Switcher */}
        <div className="guided-track-switcher">
          <span className="track-switcher-label">Scenario:</span>
          <button
            type="button"
            className={`track-switch-btn ${track === 'local' ? 'active' : ''}`}
            onClick={() => onSelectTrack('local')}
            title="Primary Track A: Safe local file routine executing 100% inside sandbox"
          >
            Track A: Complete Local Workflow
          </button>
          <button
            type="button"
            className={`track-switch-btn ${track === 'safety' ? 'active' : ''}`}
            onClick={() => onSelectTrack('safety')}
            title="Track A Safety: Demonstrates policy boundary blocking external CRM/Slack execution"
          >
            Track A Safety: Multi-App Policy
          </button>
          <button
            type="button"
            className={`track-switch-btn ${track === 'gmail' ? 'active' : ''}`}
            onClick={() => onSelectTrack('gmail')}
            title="Track B: Real Google OAuth read-only Gmail search proof"
          >
            Track B: Gmail Read-Only API
          </button>
        </div>

        <div className="guided-panel-window-controls">
          <button
            type="button"
            className="btn-window-ctrl"
            onClick={() => setIsMinimized(true)}
            title="Minimize to top bar"
          >
            Minimize
          </button>
          <button
            type="button"
            className="btn-window-ctrl close-btn"
            onClick={onClose}
            title="Exit Guided Demo Mode"
          >
            ✕
          </button>
        </div>
      </div>

      {/* 8-Stage Progress Stepper */}
      <div className="guided-stepper-row">
        {pipelineStages.map((st) => {
          const isCurrent = guidance.stageId === st.id;
          const isPast = st.number < guidance.stepNumber;
          const isHardStopStage = st.id === 'approve' && guidance.isHardStop;

          return (
            <div
              key={st.id}
              className={`stepper-node ${isCurrent ? 'current' : ''} ${isPast ? 'completed' : ''} ${
                isHardStopStage ? 'hard-stop' : ''
              }`}
              onClick={() => onNavigateToStage(st.id)}
              title={`Click to jump to Stage ${st.number}: ${st.label}`}
              style={{ cursor: 'pointer' }}
            >
              <div className="stepper-node-top">
                <span className="stepper-node-badge">
                  {isPast ? '✓' : isHardStopStage ? '🛑' : isCurrent ? '●' : st.number}
                </span>
                <span className="stepper-node-name">{st.label}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Active Guidance Card */}
      <div className={`guided-active-card ${guidance.statusType}`}>
        <div className="active-card-header">
          <div className="card-header-left">
            <span className={`status-pill ${guidance.statusType}`}>
              {guidance.status}
            </span>
            <span className="step-counter">
              Step {guidance.stepNumber} of 8 &bull; {guidance.badge}
            </span>
            {selectedDnaId && (guidance.stageId === 'understand' || guidance.stageId === 'discover') && (
              <span className="step-counter" style={{ fontFamily: 'monospace' }}>
                DNA: {selectedDnaId}
              </span>
            )}
            {selectedSpecId && (guidance.stageId === 'approve' || guidance.stageId === 'dry_run' || guidance.stageId === 'execute') && (
              <span className="step-counter" style={{ fontFamily: 'monospace' }}>
                Spec: {selectedSpecId}
              </span>
            )}
          </div>
          <span className="stage-anchor-link" onClick={() => onNavigateToStage(guidance.jumpStageId)}>
            Stage Anchor: <code>#stage-{guidance.jumpStageId}</code>
          </span>
        </div>

        <h3 className="active-step-title">{guidance.stepTitle}</h3>
        <p className="active-step-description">{guidance.description}</p>

        {/* Hard Stop Highlight if at APPROVE */}
        {guidance.isHardStop && (
          <div className="governance-hard-stop-callout">
            <span className="stop-icon">🛑</span>
            <div className="stop-text">
              <strong>Human Approval Gate Hard Stop:</strong> WorkFlowOS strictly stops here. The system will not automatically generate an execution plan or invoke any executor without your explicit signature.
            </div>
          </div>
        )}

        <div className="active-card-footer">
          <div className="capability-note">
            <span className="note-shield">🛡️</span>
            <span>{guidance.capabilityNote}</span>
          </div>

          <div className="active-card-actions">
            <button
              type="button"
              className={`btn-guided-primary ${guidance.isHardStop ? 'btn-hard-stop' : ''}`}
              onClick={guidance.onAction}
              disabled={guidance.actionDisabled}
            >
              {guidance.actionLabel}
            </button>
            <button
              type="button"
              className="btn-guided-jump"
              onClick={() => onNavigateToStage(guidance.jumpStageId)}
            >
              Jump to Stage Section &darr;
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
};
