/**
 * TypeScript definitions for Canonical Workflow Specification (Phase 6).
 */

import { DNAEvidence, OrderingConstraint, WorkflowBoundaries } from './dna';

export type VariableType =
  | 'string'
  | 'filename'
  | 'application'
  | 'identifier'
  | 'timestamp'
  | 'unknown';

export interface ParameterBinding {
  binding_id: string;
  source_parameter: string;
  semantic_name: string;
  source_field: string;
  associated_step_key: string;
  associated_application: string;
  observed_values: string[];
  inferred_type: VariableType;
  binding_status: 'bound' | 'unbound' | 'user_modified';
  user_override: boolean;
  confidence: number;
}

export type RiskCategory =
  | 'read_only'
  | 'local_change'
  | 'external_change'
  | 'communication'
  | 'potentially_sensitive';

export type RiskLevel = 'low' | 'medium' | 'high';

export interface StepRisk {
  step_id: string;
  application: string;
  action: string;
  risk_level: RiskLevel;
  risk_category: RiskCategory;
  reason: string;
  requires_confirmation: boolean;
}

export interface RiskAssessment {
  overall_risk_level: RiskLevel;
  primary_risk_category: RiskCategory;
  requires_human_confirmation: boolean;
  step_risks: StepRisk[];
  summary: string;
  sensitive_factors_detected: string[];
}

export type ApprovalState = 'draft' | 'requires_review' | 'approved' | 'rejected';

export interface ApprovalMetadata {
  state: ApprovalState;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  comments: string | null;
}

export interface CanonicalStep {
  canonical_step_id: string;
  source_semantic_step_id: string;
  source_dna_step_key: string;
  application: string;
  event_type: string;
  action: string;
  description: string;
  input_variables: string[];
  output_variables: string[];
  evidence_reference: string;
  risk: StepRisk;
  occurrence_ratio: number;
  classification: string;
}

export interface CanonicalOptionalStep {
  canonical_step_id: string;
  source_semantic_step_id: string;
  source_dna_step_key: string;
  application: string;
  event_type: string;
  condition_or_trigger: string;
  description: string;
  risk: StepRisk;
  occurrence_ratio: number;
  classification: string;
}

export interface CanonicalWorkflowSpec {
  workflow_id: string;
  source_dna_id: string;
  source_semantic_workflow_id: string;
  title: string;
  intent: string;
  description: string;
  version: string;
  status: string;
  steps: CanonicalStep[];
  variables: ParameterBinding[];
  optional_steps: CanonicalOptionalStep[];
  preconditions: string[];
  boundaries: WorkflowBoundaries;
  ordering_constraints: OrderingConstraint[];
  evidence: DNAEvidence;
  parameter_bindings: ParameterBinding[];
  risk_assessment: RiskAssessment;
  approval_state: ApprovalMetadata;
  created_at: string;
  updated_at: string;
}

export interface SpecificationListResponse {
  total_count: number;
  specifications: CanonicalWorkflowSpec[];
}
