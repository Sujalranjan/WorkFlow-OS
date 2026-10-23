import { ActivityEvent } from './types/event';
import { DiscoveryAnalysisResponse } from './types/discovery';
import { WorkflowDNAListResponse } from './types/dna';
import { InterpretationResponse } from './types/semantic';
import { CanonicalWorkflowSpec, SpecificationListResponse } from './types/canonical';
import {
  DryRunResult,
  ExecutionAuditRecord,
  ExecutionListResponse,
  ExecutionPlan,
  VerificationResult,
} from './types/execution';
import { WorkflowReliabilityProfile } from './types/learning';
import { EmailTrigger, PollResult, RunStatus, WorkflowRun } from './types/automation';

// Same host name as the dashboard by default: the session cookie is only sent between pages and an
// API on the same site (localhost vs 127.0.0.1 count as different sites).
export const API_BASE =
  import.meta.env.VITE_BACKEND_URL || `${window.location.protocol}//${window.location.hostname}:8000`;

/** Fired when the API says the session is missing or expired; the app shows the sign-in page. */
export const UNAUTHORIZED_EVENT = 'workflowos:unauthorized';

// Discovery settings shared by every call so patterns and their workflows line up.
const DISCOVERY = { limit: '500', inactivity_timeout: '120', min_occurrences: '2', similarity_threshold: '0.65' };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-WorkflowOS-CSRF': '1', ...(init?.headers || {}) },
    });
  } catch {
    throw new Error(`Cannot reach the WorkFlowOS backend at ${API_BASE}. Is it running?`);
  }
  if (res.status === 401 && path !== '/api/auth/login') {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      detail = res.statusText || detail;
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

// --- status -------------------------------------------------------------------------

export interface IntegrationState {
  connected: boolean;
  detail: string;
}
export interface SystemStatus {
  gmail: IntegrationState;
  slack: IntegrationState;
  crm: IntegrationState;
  ai: IntegrationState;
  email_polling: boolean;
}
export const getStatus = () => request<SystemStatus>('/api/status');

// --- activity & discovery -----------------------------------------------------------

export const listEvents = (limit = 200) => request<ActivityEvent[]>(`/api/events?limit=${limit}`);

export const discoverRoutines = () =>
  request<DiscoveryAnalysisResponse>(`/api/discovery/candidates?${new URLSearchParams(DISCOVERY)}`);

export const listRoutineStructures = () =>
  request<WorkflowDNAListResponse>(`/api/workflows/dna?${new URLSearchParams(DISCOVERY)}`);

export const loadSampleActivity = () =>
  post<{ events_created: number; sessions_created: number; message: string }>('/api/demo/seed-activity', {
    scenario: 'observed_browser_routine',
  });

/** Describe a discovered routine with the AI interpreter, then turn it into a reviewable workflow. */
export async function createWorkflowFromRoutine(dnaId: string): Promise<CanonicalWorkflowSpec> {
  const params = new URLSearchParams({
    similarity_threshold: DISCOVERY.similarity_threshold,
    min_occurrences: DISCOVERY.min_occurrences,
    inactivity_timeout: DISCOVERY.inactivity_timeout,
  });
  const interp = await post<InterpretationResponse>(`/api/workflows/${encodeURIComponent(dnaId)}/interpret?${params}`);
  if (!interp.semantic_workflow) {
    const why = interp.validation_errors?.length ? interp.validation_errors.join('; ') : interp.message;
    throw new Error(`Could not describe this routine: ${why}`);
  }
  return post<CanonicalWorkflowSpec>(
    `/api/workflows/${encodeURIComponent(interp.semantic_workflow.semantic_workflow_id)}/specification`,
  );
}

// --- workflows ----------------------------------------------------------------------

export const listWorkflows = () =>
  request<SpecificationListResponse>('/api/workflows/specifications?limit=200').then((r) => r.specifications);

export const getWorkflow = (id: string) =>
  request<CanonicalWorkflowSpec>(`/api/workflows/specifications/${encodeURIComponent(id)}`);

export const approveWorkflow = (id: string) =>
  post<CanonicalWorkflowSpec>(`/api/workflows/specifications/${encodeURIComponent(id)}/approve`, {});

export const rejectWorkflow = (id: string, reason: string) =>
  post<CanonicalWorkflowSpec>(`/api/workflows/specifications/${encodeURIComponent(id)}/reject`, { reason });

export const planWorkflow = (id: string, runtimeParameters?: Record<string, string>) =>
  post<ExecutionPlan>(`/api/workflows/specifications/${encodeURIComponent(id)}/execution-plan`, {
    runtime_parameters: runtimeParameters && Object.keys(runtimeParameters).length ? runtimeParameters : undefined,
  });

export const dryRunPlan = (planId: string) =>
  post<DryRunResult>(`/api/workflows/execution-plans/${encodeURIComponent(planId)}/dry-run`);

export const executePlan = (planId: string) =>
  post<ExecutionAuditRecord>(`/api/workflows/execution-plans/${encodeURIComponent(planId)}/execute`, {
    execution_mode: 'LIVE',
  });

export const verifyExecution = (executionId: string) =>
  post<VerificationResult>(`/api/workflows/executions/${encodeURIComponent(executionId)}/verify`, {
    force_recheck: true,
  });

export const getVerification = (executionId: string) =>
  request<VerificationResult>(`/api/workflows/executions/${encodeURIComponent(executionId)}/verification`);

export const listExecutions = (workflowId?: string, limit = 100) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (workflowId) params.set('workflow_id', workflowId);
  return request<ExecutionListResponse>(`/api/workflows/executions?${params}`).then((r) => r.executions);
};

export const getReliability = (workflowId: string) =>
  post<WorkflowReliabilityProfile>(`/api/workflows/${encodeURIComponent(workflowId)}/learning/refresh`);

// --- automation ---------------------------------------------------------------------

export const listTriggers = () => request<EmailTrigger[]>('/api/automation/triggers');

export const createTrigger = (input: {
  workflow_id: string;
  gmail_query: string;
  name?: string;
  poll_interval_seconds?: number;
  include_existing_since?: number;
}) => post<EmailTrigger>('/api/automation/triggers', input);

export const setTriggerEnabled = (id: string, enabled: boolean) =>
  request<EmailTrigger>(`/api/automation/triggers/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });

export const deleteTrigger = (id: string) =>
  request<void>(`/api/automation/triggers/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const pollTrigger = (id: string) => post<PollResult>(`/api/automation/triggers/${encodeURIComponent(id)}/poll`);

export const listRuns = (statuses?: RunStatus[], limit = 100) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (statuses?.length) params.set('status', statuses.join(','));
  return request<WorkflowRun[]>(`/api/automation/runs?${params}`);
};

export const approveRun = (id: string) => post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/approve`);

export const rejectRun = (id: string) => post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/reject`);

export const resumeRun = (id: string, inputs: Record<string, string>) =>
  post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/resume`, { inputs });

// --- auth ---------------------------------------------------------------------------

export type Role = 'viewer' | 'approver' | 'admin';

export interface User {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Session {
  user: User;
  /** "METHOD /path/template" entries this user may call. */
  permissions: string[];
}

export interface ApiKey {
  key_id: string;
  name: string;
  prefix: string;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export const login = (email: string, password: string) => post<Session>('/api/auth/login', { email, password });
export const logout = () => post<void>('/api/auth/logout');
export const getSession = () => request<Session>('/api/auth/me');

export const listUsers = () => request<User[]>('/api/auth/users');
export const createUser = (input: { email: string; name: string; role: Role; password: string }) =>
  post<User>('/api/auth/users', input);
export const updateUser = (id: string, changes: Partial<{ name: string; role: Role; active: boolean; password: string }>) =>
  request<User>(`/api/auth/users/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(changes) });

export const listApiKeys = () => request<ApiKey[]>('/api/auth/api-keys');
export const createApiKey = (name: string) => post<{ key: string; api_key: ApiKey }>('/api/auth/api-keys', { name });
export const revokeApiKey = (id: string) =>
  request<ApiKey>(`/api/auth/api-keys/${encodeURIComponent(id)}`, { method: 'DELETE' });
