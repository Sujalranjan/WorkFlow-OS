export type ExecutionStrategy =
  | 'api'
  | 'application_integration'
  | 'accessibility_semantic_ui'
  | 'browser_automation'
  | 'ui_fallback';

export type ParameterResolutionStatus =
  | 'resolved'
  | 'sample_fallback'
  | 'default_sample'
  | 'unresolved';

export interface ResolvedParameter {
  semantic_name: string;
  source_parameter: string;
  source_field?: string;
  inferred_type?: string;
  data_type?: string;
  is_required: boolean;
  definition?: string;
  sample_value?: string | null;
  sample_observed_values?: string[];
  runtime_value?: string | null;
  resolution_status: ParameterResolutionStatus;
  resolution_source?: string;
}

export type PreconditionStatus = 'satisfied' | 'unsatisfied' | 'unknown';

export interface PreconditionCheck {
  condition: string;
  condition_description?: string;
  status: PreconditionStatus;
  reason?: string;
  evaluation_reason?: string;
}

export interface ExpectedStateChange {
  target_system: string;
  target_entity?: string;
  before_state: string;
  expected_after_state: string;
  actual_state: string;
}

export interface StepExecutionStrategy {
  strategy: ExecutionStrategy;
  reason: string;
  target_technology?: string;
  is_currently_executable?: boolean;
  supported_alternatives?: ExecutionStrategy[];
  canonical_strategy?: string | null;
  selection_reason?: string | null;
  available_strategies_considered?: string[];
  rejected_strategies?: string[];
  rejection_reasons?: Record<string, string>;
  fallback_used?: boolean;
  executor_implemented?: boolean;
  blocked_reason?: string | null;
  policy_decision?: string;
}


export interface PlannedStep {
  plan_step_id: string;
  step_number?: number;
  source_canonical_step_id: string;
  source_semantic_step_id: string;
  source_dna_step_key: string;
  application: string;
  action: string;
  description: string;
  resolved_parameters: Record<string, string | null>;
  execution_strategy: StepExecutionStrategy;
  risk: {
    risk_level: string;
    risk_category: string;
    reason: string;
    requires_confirmation: boolean;
  };
  expected_result: string;
  external_change: boolean;
  requires_confirmation: boolean;
  state_change: ExpectedStateChange;
}

export interface DryRunStepResult {
  plan_step_id: string;
  application: string;
  action: string;
  strategy: ExecutionStrategy;
  simulation_status: string;
  risk_level: string;
  risk_category: string;
  external_mutation_prevented: boolean;
  expected_state_transition: string;
  simulated_output: Record<string, any>;
  notes: string;
}

export interface DryRunResult {
  dry_run_id: string;
  simulated_at: string;
  overall_simulation_status: string;
  step_simulations: DryRunStepResult[];
  precondition_checks: PreconditionCheck[];
  real_actions_performed: number;
  external_mutations_prevented: number;
  summary: string;
}

export interface ExecutionPlan {
  execution_plan_id: string;
  source_workflow_id: string;
  workflow_version: string;
  created_at: string;
  source_approval_state: string;
  resolved_parameters: ResolvedParameter[];
  planned_steps: PlannedStep[];
  preconditions: PreconditionCheck[];
  boundaries: {
    first_step: string;
    last_step: string;
    typical_duration_seconds?: number;
    step_count?: number;
  };
  risk_assessment: {
    overall_risk_level: string;
    primary_risk_category: string;
    requires_human_confirmation: boolean;
    summary: string;
  };
  expected_effects: ExpectedStateChange[];
  dry_run_status: string;
  dry_run_result?: DryRunResult | null;
}

export interface ExecutionPlanListResponse {
  plans: ExecutionPlan[];
  total_count: number;
}

// ----------------------------------------------------------------------
// Phase 8: Execution Engine Types
// ----------------------------------------------------------------------

export type ExecutionMode = 'DRY_RUN' | 'LIVE';

export type ExecutionStepStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCESS'
  | 'FAILED'
  | 'BLOCKED'
  | 'SKIPPED'
  | 'CANCELLED';

export type ExecutionOverallStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'BLOCKED';

export interface ExecutionStepResult {
  execution_step_id: string;
  planned_step_id: string;
  action_name: string;
  target_application: string;
  strategy: ExecutionStrategy;
  executor_name: string;
  status: ExecutionStepStatus;
  parameters_used: Record<string, any>;
  output: Record<string, any>;
  error?: string | null;
  affected_resources: string[];
  start_time: string;
  end_time?: string | null;
  selected_strategy?: string | null;
  selection_reason?: string | null;
  candidate_strategies?: string[];
  fallback_used?: boolean;
  policy_decision?: string;
  blocked_reason?: string | null;
}


export interface ExecutionAuditRecord {
  execution_id: string;
  workflow_id: string;
  workflow_version: string;
  execution_plan_id: string;
  approval_state: string;
  approved_by?: string | null;
  execution_mode: ExecutionMode;
  status: ExecutionOverallStatus;
  sandbox_root: string;
  start_time: string;
  end_time?: string | null;
  step_results: ExecutionStepResult[];
  affected_resources: string[];
  error_summary?: string | null;
  executed_by: string;
  idempotency_key?: string | null;
  verification_status?: string | null;
  verification_id?: string | null;
}

export interface ExecutionListResponse {
  total_count: number;
  executions: ExecutionAuditRecord[];
}

// ----------------------------------------------------------------------
// Phase 9: Verification Engine Types
// ----------------------------------------------------------------------

export type VerificationStatus =
  | 'PENDING'
  | 'VERIFIED'
  | 'FAILED'
  | 'UNKNOWN'
  | 'NOT_APPLICABLE';

export type VerificationStrategyType =
  | 'FILE_SYSTEM'
  | 'STRUCTURED_OUTPUT'
  | 'RESOURCE_EXISTENCE'
  | 'STATE_MATCH'
  | 'NOT_APPLICABLE';

export interface VerificationCheck {
  verification_id: string;
  execution_id: string;
  execution_step_id: string;
  planned_step_id: string;
  check_type: string;
  strategy_type: VerificationStrategyType;
  target: string;
  expected_state: any;
  actual_state: any;
  status: VerificationStatus;
  evidence: Record<string, any>;
  reason: string;
  checked_at: string;
}

export interface VerificationResult {
  verification_run_id: string;
  execution_id: string;
  workflow_id: string;
  execution_plan_id: string;
  overall_status: VerificationStatus;
  checks: VerificationCheck[];
  verified_count: number;
  failed_count: number;
  unknown_count: number;
  not_applicable_count: number;
  evidence: Record<string, any>;
  started_at: string;
  completed_at?: string | null;
}

