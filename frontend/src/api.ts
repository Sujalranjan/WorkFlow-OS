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
      if (body.detail) {
        detail =
          typeof body.detail === 'string' ? body.detail : body.detail.message || JSON.stringify(body.detail);
      }
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
export interface IntegrationInfo {
  key: string;
  name: string;
  role: string;
}
/** One entry per integration key (gmail, crm, slack, ...) plus `ai`. */
export type SystemStatus = {
  ai: IntegrationState;
  email_polling: boolean;
  integrations: IntegrationInfo[];
} & Record<string, IntegrationState | boolean | IntegrationInfo[] | undefined>;
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

/** `version` is the version the reviewer looked at; the server refuses if the workflow changed since. */
export const approveWorkflow = (id: string, version: string) =>
  post<CanonicalWorkflowSpec>(`/api/workflows/specifications/${encodeURIComponent(id)}/approve`, { version });

export const rejectWorkflow = (id: string, reason: string, version: string) =>
  post<CanonicalWorkflowSpec>(`/api/workflows/specifications/${encodeURIComponent(id)}/reject`, { reason, version });

// --- workflow editor ----------------------------------------------------------------

export type ParameterMode = 'upstream' | 'fixed' | 'runtime';
export interface StepParameter {
  mode: ParameterMode;
  value?: string | null;
}
export interface EditorStep {
  step_id?: string | null;
  catalog_action: string;
  parameters: Record<string, StepParameter>;
}
export interface WorkflowDefinitionView {
  workflow_id: string;
  version: string;
  approval_state: string;
  title: string;
  description: string;
  steps: EditorStep[];
  context_steps: { step_id: string; application: string; description: string }[];
}
export interface CatalogParameterInfo {
  name: string;
  description: string;
  required: boolean;
  default_upstream: string | null;
}
export interface CatalogActionInfo {
  action_id: string;
  application: string;
  action: string;
  description: string;
  risk_level: string;
  risk_reason: string;
  requires_confirmation: boolean;
  parameters: CatalogParameterInfo[];
  produces: string[];
  requires: string[];
}
export interface CatalogGroup {
  key: string;
  name: string;
  actions: CatalogActionInfo[];
}
export interface EditorIssue {
  level: 'error' | 'warning';
  message: string;
  step: number | null;
  parameter: string | null;
}
export interface WorkflowDefinitionInput {
  base_version: string;
  title: string;
  description: string;
  steps: EditorStep[];
  note?: string;
}
export interface WorkflowVersionInfo {
  version: string;
  created_at: string;
  created_by: string | null;
  note: string | null;
  changes: { kind: string; text: string }[];
}

const wfPath = (id: string) => `/api/workflows/specifications/${encodeURIComponent(id)}`;
export const getCatalog = () => request<CatalogGroup[]>('/api/catalog');
export const getWorkflowDefinition = (id: string) => request<WorkflowDefinitionView>(`${wfPath(id)}/definition`);
export const validateWorkflowDefinition = (id: string, d: WorkflowDefinitionInput) =>
  post<{ valid: boolean; issues: EditorIssue[] }>(`${wfPath(id)}/definition/validate`, d);
export const saveWorkflowDefinition = (id: string, d: WorkflowDefinitionInput) =>
  request<CanonicalWorkflowSpec>(`${wfPath(id)}/definition`, { method: 'PUT', body: JSON.stringify(d) });
export const listWorkflowVersions = (id: string) =>
  request<{ current_version: string; versions: WorkflowVersionInfo[] }>(`${wfPath(id)}/versions`);

export const planWorkflow = (id: string, runtimeParameters?: Record<string, string>) =>
  post<ExecutionPlan>(`/api/workflows/specifications/${encodeURIComponent(id)}/execution-plan`, {
    runtime_parameters: runtimeParameters && Object.keys(runtimeParameters).length ? runtimeParameters : undefined,
  });

export const dryRunPlan = (planId: string) =>
  post<DryRunResult>(`/api/workflows/execution-plans/${encodeURIComponent(planId)}/dry-run`);

// --- background jobs ----------------------------------------------------------------

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'needs_attention' | 'dismissed';

export interface Job {
  job_id: string;
  kind: string;
  status: JobStatus;
  result: Record<string, any> | null;
  attempts: number;
  max_attempts: number;
  side_effects_started: boolean;
  last_error: string | null;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

const FINISHED: JobStatus[] = ['succeeded', 'failed', 'needs_attention', 'dismissed'];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const getJob = (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`);
export const listJobs = (statuses?: JobStatus[], limit = 50) => {
  const params = new URLSearchParams({ limit: String(limit) });
  (statuses || []).forEach((s) => params.append('status', s));
  return request<Job[]>(`/api/jobs?${params}`);
};
export const dismissJob = (id: string) => post<Job>(`/api/jobs/${encodeURIComponent(id)}/dismiss`);

/** Wait for the worker to finish a job; throws with the job's error if it did not succeed. */
export async function waitForJob(job: Job, timeoutMs = 10 * 60 * 1000): Promise<Job> {
  const deadline = Date.now() + timeoutMs;
  let current = job;
  while (!FINISHED.includes(current.status)) {
    if (Date.now() > deadline) throw new Error('Still running in the background. Check Runs for the result.');
    await sleep(1000);
    current = await getJob(job.job_id);
  }
  if (current.status !== 'succeeded') {
    const why = current.status === 'needs_attention' ? 'Interrupted, needs attention' : 'Failed';
    throw new Error(`${why}: ${current.last_error || 'no details'}`);
  }
  return current;
}

export const getExecution = (executionId: string) =>
  request<ExecutionAuditRecord>(`/api/workflows/executions/${encodeURIComponent(executionId)}`);

/** Queue a live run, wait for the worker, and return the execution record. */
export async function executePlan(planId: string): Promise<ExecutionAuditRecord> {
  const job = await post<Job>(`/api/workflows/execution-plans/${encodeURIComponent(planId)}/execute`, {
    execution_mode: 'LIVE',
  });
  const done = await waitForJob(job);
  return getExecution(done.result!.execution_id);
}

/** Queue independent verification, wait for it, and return the result. */
export async function verifyExecution(executionId: string): Promise<VerificationResult> {
  const job = await post<Job>(`/api/workflows/executions/${encodeURIComponent(executionId)}/verify`, {
    force_recheck: true,
  });
  await waitForJob(job);
  return getVerification(executionId);
}

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

export const getRun = (id: string) => request<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}`);

/** Poll a run the worker is executing until it leaves RUNNING (or the wait times out). */
export async function waitForRun(run: WorkflowRun, timeoutMs = 5 * 60 * 1000): Promise<WorkflowRun> {
  const deadline = Date.now() + timeoutMs;
  let current = run;
  while (current.status === 'RUNNING' && Date.now() < deadline) {
    await sleep(1500);
    current = await getRun(run.run_id);
  }
  return current;
}

export const approveRun = (id: string) =>
  post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/approve`).then(waitForRun);

export const rejectRun = (id: string) => post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/reject`);

export const resumeRun = (id: string, inputs: Record<string, string>) =>
  post<WorkflowRun>(`/api/automation/runs/${encodeURIComponent(id)}/resume`, { inputs }).then(waitForRun);

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

// --- integrations (Settings) ----------------------------------------------------------

export interface Integrations {
  gmail: {
    connected: boolean;
    source: 'settings' | 'file' | null;
    account: string | null;
    connected_at: string | null;
    connected_by: string | null;
    client_configured: boolean;
    client_source: 'settings' | 'file' | null;
    client_id: string | null;
    redirect_uri: string;
    /** Opted in to labeling (Settings) / Google granted gmail.modify at the last Connect Gmail. */
    labels_allowed: boolean;
    can_label: boolean;
    sheets_allowed: boolean;
    can_use_sheets: boolean;
  };
  sheets: {
    configured: boolean;
    spreadsheet_id: string | null;
    title: string | null;
    sheet: string | null;
    columns: string[];
    available_columns: string[];
    updated_at: string | null;
    updated_by: string | null;
  };
  slack: {
    configured: boolean;
    source: 'settings' | 'environment' | null;
    channel_id: string | null;
    channel_name: string | null;
    /** Whether the bot was in the channel when it was saved; null when the token cannot tell. */
    bot_in_channel: boolean | null;
    alert_channel_id: string | null;
    alert_on_pending: boolean;
    team: string | null;
    updated_at: string | null;
    updated_by: string | null;
  };
  files: {
    configured: boolean;
    source: 'settings' | 'environment' | null;
    folder: string | null;
    /** The folder exists and WorkFlowOS can write to it (checked on every load). */
    ready: boolean;
    detail: string;
    updated_at: string | null;
    updated_by: string | null;
  };
  hubspot: {
    configured: boolean;
    source: 'settings' | 'environment' | null;
    portal_id: number | null;
    ui_domain: string | null;
    status_property: string | null;
    status_property_label: string | null;
    status_value: string | null;
    updated_at: string | null;
    updated_by: string | null;
  };
}

/** A writable HubSpot contact property (for choosing which one update_contact writes). */
export interface HubSpotProperty {
  name: string;
  label: string;
  type: string;
  options: string[];
}

export const getIntegrations = () => request<Integrations>('/api/integrations');
export const saveGmailClient = (client_id: string, client_secret: string) =>
  request<Integrations>('/api/integrations/gmail/client', { method: 'PUT', body: JSON.stringify({ client_id, client_secret }) });
export const removeGmailClient = () => request<Integrations>('/api/integrations/gmail/client', { method: 'DELETE' });
export const startGmailConnect = () =>
  post<{ authorization_url: string }>('/api/integrations/gmail/connect', { return_to: window.location.origin });
export const disconnectGmail = () => request<Integrations>('/api/integrations/gmail', { method: 'DELETE' });
export interface SlackChannels {
  can_list: boolean;
  channels: { id: string; name: string; is_private: boolean; is_member: boolean }[];
  notes: string[];
}
/** Channels for the picker; pass the token being set up, or null to use the saved one. */
export const listSlackChannels = (bot_token: string | null) =>
  post<SlackChannels>('/api/integrations/slack/channels', bot_token ? { bot_token } : {});
/** bot_token null keeps the saved token (changing only the channel). */
export const saveSlack = (bot_token: string | null, channel_id: string) =>
  request<Integrations>('/api/integrations/slack', {
    method: 'PUT',
    body: JSON.stringify(bot_token ? { bot_token, channel_id } : { channel_id }),
  });
export const removeSlack = () => request<Integrations>('/api/integrations/slack', { method: 'DELETE' });
export const saveHubSpot = (access_token: string) =>
  request<Integrations>('/api/integrations/hubspot', { method: 'PUT', body: JSON.stringify({ access_token }) });
export const getHubSpotProperties = () => request<HubSpotProperty[]>('/api/integrations/hubspot/properties');
export const saveHubSpotSettings = (status_property: string, status_value: string | null) =>
  request<Integrations>('/api/integrations/hubspot/settings', {
    method: 'PUT',
    body: JSON.stringify({ status_property, status_value }),
  });
export const removeHubSpot = () => request<Integrations>('/api/integrations/hubspot', { method: 'DELETE' });
export const saveSharedFolder = (folder: string) =>
  request<Integrations>('/api/integrations/files', { method: 'PUT', body: JSON.stringify({ folder }) });
export const removeSharedFolder = () => request<Integrations>('/api/integrations/files', { method: 'DELETE' });
export const saveGmailOptions = (options: { allow_labels?: boolean; allow_sheets?: boolean }) =>
  request<Integrations>('/api/integrations/gmail/options', { method: 'PUT', body: JSON.stringify(options) });
export const saveSheet = (spreadsheet: string, sheet: string, columns: string[]) =>
  request<Integrations>('/api/integrations/sheets', { method: 'PUT', body: JSON.stringify({ spreadsheet, sheet, columns }) });
export const removeSheet = () => request<Integrations>('/api/integrations/sheets', { method: 'DELETE' });

// --- monitoring -------------------------------------------------------------------

export interface JobSummary {
  job_id: string;
  kind: string;
  status: string;
  last_error: string | null;
  created_at: string;
  finished_at: string | null;
}
export interface SystemOverview {
  version: string;
  database: string;
  ready: boolean;
  checks: { database?: boolean; migrations?: boolean; worker?: boolean };
  embedded_worker: boolean;
  workers: { name: string; kind: string; last_seen: string; alive: boolean }[];
  jobs: Record<string, number>;
  executions: Record<string, number>;
  triggered_runs: Record<string, number>;
  needs_attention: JobSummary[];
  failed_jobs: JobSummary[];
  triggers: { trigger_id: string; name: string; enabled: boolean; last_polled_at: string | null; last_error: string | null; last_note: string | null }[];
  metrics_enabled: boolean;
  alerts: { channel_id: string | null; notify_pending: boolean };
}
export const getSystem = () => request<SystemOverview>('/api/system');
export const saveSlackAlerts = (channel_id: string | null, notify_pending: boolean) =>
  request<Integrations>('/api/integrations/slack/alerts', { method: 'PUT', body: JSON.stringify({ channel_id, notify_pending }) });
