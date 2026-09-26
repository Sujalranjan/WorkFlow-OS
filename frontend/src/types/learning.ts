export interface StepReliability {
  planned_step_id: string;
  action: string;
  target: string;
  selected_strategy?: string | null;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  blocked_executions: number;
  verified_success_count: number;
  verification_failure_count: number;
  last_outcome: string;
  failure_pattern?: string | null;
}

export interface DetectedPattern {
  pattern_id: string;
  pattern_type: string;
  description: string;
  affected_step_id?: string | null;
  affected_action?: string | null;
  occurrence_count: number;
  evidence_execution_ids: string[];
  evidence_verification_ids?: string[];
}

export interface ImprovementSuggestion {
  suggestion_id: string;
  workflow_id: string;
  affected_step_id?: string | null;
  affected_step_action?: string | null;
  category: string;
  title: string;
  suggestion: string;
  evidence: Record<string, any>;
  is_advisory: boolean;
  created_at: string;
}

export interface WorkflowLearningEvent {
  event_id: string;
  workflow_id: string;
  timestamp: string;
  event_type: string;
  execution_id?: string | null;
  verification_id?: string | null;
  planned_step_id?: string | null;
  step_action?: string | null;
  observed_evidence: Record<string, any>;
  insight: string;
  confidence: number;
}

export interface WorkflowReliabilityProfile {
  profile_id: string;
  workflow_id: string;
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  blocked_executions: number;
  verified_executions: number;
  verification_failures: number;
  unknown_verifications: number;
  execution_success_rate: number;
  verification_rate: number;
  blocked_rate: number;
  reliability_rate: number;
  last_execution_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  step_reliabilities: StepReliability[];
  detected_patterns: DetectedPattern[];
  suggestions: ImprovementSuggestion[];
  latest_events: WorkflowLearningEvent[];
  computed_at: string;
}
