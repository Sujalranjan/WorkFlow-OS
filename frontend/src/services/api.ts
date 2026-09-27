import { CanonicalWorkflowSpec } from '../types/canonical';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export interface SeedActivityResponse {
  events_created: number;
  sessions_created: number;
  scenario: string;
  message: string;
}

/**
 * Creates a formal CanonicalWorkflowSpec from a validated SemanticWorkflow.
 * Calls existing backend endpoint: POST /api/workflows/{semantic_workflow_id}/specification
 */
export async function createCanonicalSpecification(
  semanticWorkflowId: string
): Promise<CanonicalWorkflowSpec> {
  const response = await fetch(`${API_BASE}/api/workflows/${encodeURIComponent(semanticWorkflowId)}/specification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(`Failed to generate canonical specification: ${errorDetail}`);
  }

  return response.json();
}

/**
 * Seeds deterministic synthetic demo activity events for demonstration.
 * Calls existing backend endpoint: POST /api/demo/seed-activity
 */
export async function seedDemoActivity(
  scenario: string = 'local_file_automation'
): Promise<SeedActivityResponse> {
  const response = await fetch(`${API_BASE}/api/demo/seed-activity`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ scenario }),
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(`Failed to seed demo activity: ${errorDetail}`);
  }

  return response.json();
}

export interface ResetDemoResponse {
  status: string;
  events_deleted: number;
  specifications_deleted: number;
  plans_deleted: number;
  executions_deleted: number;
  verifications_deleted: number;
  learning_profiles_deleted: number;
  message: string;
}

export interface SeedE2EWorkflowResponse {
  workflow_id: string;
  title: string;
  status: string;
  approval_state: string;
  steps_count: number;
  steps: string[];
  message: string;
}

/**
 * Seeds the complete Phase 16 Full End-to-End Workflow into WorkFlowOS
 * (Gmail → Attachment → CRM → Slack).
 * Calls backend endpoint: POST /api/demo/seed-e2e-workflow
 */
export async function seedE2EWorkflow(
  autoApprove: boolean = false,
  reviewer?: string
): Promise<SeedE2EWorkflowResponse> {
  const url = new URL(`${API_BASE}/api/demo/seed-e2e-workflow`);
  if (autoApprove) url.searchParams.append('auto_approve', 'true');
  if (reviewer) url.searchParams.append('reviewer', reviewer);

  const response = await fetch(url.toString(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(`Failed to seed E2E workflow: ${errorDetail}`);
  }

  return response.json();
}

/**
 * Safely clears demonstration state without modifying credentials or application settings.
 * Calls existing backend endpoint: POST /api/demo/reset
 */
export async function resetDemoState(): Promise<ResetDemoResponse> {
  const response = await fetch(`${API_BASE}/api/demo/reset`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(`Failed to reset demo state: ${errorDetail}`);
  }

  return response.json();
}


