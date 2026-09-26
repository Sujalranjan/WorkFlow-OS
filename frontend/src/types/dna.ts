/**
 * TypeScript types for Workflow DNA (Phase 4).
 */

export interface InvariantStep {
  step_key: string;
  application: string;
  event_type: string;
  occurrences: number;
  total_sessions: number;
  occurrence_ratio: number;
  classification: string;
}

export interface OptionalStep {
  step_key: string;
  application: string;
  event_type: string;
  occurrences: number;
  total_sessions: number;
  occurrence_ratio: number;
  supporting_session_ids: string[];
  classification: string;
}

export interface VariableParameter {
  parameter_name: string;
  source_field: string;
  associated_step_key: string;
  associated_application: string;
  observed_values: string[];
  distinct_value_count: number;
  total_observations: number;
  variation_ratio: number;
  pattern_template: string | null;
}

export interface OrderingConstraint {
  predecessor: string;
  successor: string;
  consistency_ratio: number;
  description: string;
}

export interface WorkflowBoundaries {
  first_step: string;
  last_step: string;
  min_duration_seconds: number;
  max_duration_seconds: number;
  average_duration_seconds: number;
  total_supporting_sessions: number;
}

export interface DNAEvidence {
  supporting_session_count: number;
  invariant_evidence: string;
  variable_evidence: string;
  optional_step_evidence: string;
  ordering_evidence: string;
  boundary_evidence: string;
}

export interface WorkflowDNA {
  dna_id: string;
  source_candidate_id: string;
  normalized_signature: string;
  version: string;
  invariant_steps: InvariantStep[];
  variable_parameters: VariableParameter[];
  optional_steps: OptionalStep[];
  ordering_constraints: OrderingConstraint[];
  preconditions: string[];
  boundaries: WorkflowBoundaries;
  evidence: DNAEvidence;
  statistics: Record<string, unknown>;
}

export interface WorkflowDNAListResponse {
  total_candidates_analyzed: number;
  dna_count: number;
  dna_items: WorkflowDNA[];
}
