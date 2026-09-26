/**
 * TypeScript types for Semantic Understanding (Phase 5).
 */

import { WorkflowBoundaries, WorkflowDNA } from './dna';

export interface SemanticStep {
  step_id: string;
  source_dna_step_key: string;
  application: string;
  action: string;
  description: string;
  input_variables: string[];
  output_variables: string[];
  evidence_reference: string;
}

export interface SemanticVariable {
  source_parameter: string;
  semantic_name: string;
  source_field: string;
  observed_values: string[];
  reason: string;
  model_interpretation_confidence: number;
}

export interface SemanticOptionalStep {
  step_id: string;
  source_dna_step_key: string;
  application: string;
  condition_or_trigger: string;
  description: string;
}

export interface SemanticWorkflow {
  semantic_workflow_id: string;
  source_dna_id: string;
  title: string;
  intent: string;
  summary: string;
  semantic_steps: SemanticStep[];
  semantic_variables: SemanticVariable[];
  optional_steps: SemanticOptionalStep[];
  preconditions: string[];
  boundaries: WorkflowBoundaries;
  evidence_mapping: Record<string, string>;
  interpretation_notes: string;
  model_provider: string;
  status: string;
}

export interface InterpretationResponse {
  status: 'success' | 'fallback' | 'error';
  semantic_workflow: SemanticWorkflow | null;
  source_dna: WorkflowDNA;
  message: string;
  validation_passed: boolean;
  validation_errors: string[];
}
