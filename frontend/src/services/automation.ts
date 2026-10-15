import { EmailTrigger, PollResult, RunStatus, WorkflowRun } from '../types/automation';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';
const BASE = `${API_BASE}/api/automation`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
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

export interface CreateTriggerInput {
  workflow_id: string;
  gmail_query: string;
  name?: string;
  poll_interval_seconds?: number;
  include_existing_since?: number;
}

export const listTriggers = () => request<EmailTrigger[]>('/triggers');

export const createTrigger = (input: CreateTriggerInput) =>
  request<EmailTrigger>('/triggers', { method: 'POST', body: JSON.stringify(input) });

export const setTriggerEnabled = (triggerId: string, enabled: boolean) =>
  request<EmailTrigger>(`/triggers/${encodeURIComponent(triggerId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });

export const deleteTrigger = (triggerId: string) =>
  request<void>(`/triggers/${encodeURIComponent(triggerId)}`, { method: 'DELETE' });

export const pollTrigger = (triggerId: string) =>
  request<PollResult>(`/triggers/${encodeURIComponent(triggerId)}/poll`, { method: 'POST' });

export const listRuns = (statuses?: RunStatus[], limit = 100) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (statuses && statuses.length) params.set('status', statuses.join(','));
  return request<WorkflowRun[]>(`/runs?${params.toString()}`);
};

export const approveRun = (runId: string, decidedBy: string) =>
  request<WorkflowRun>(`/runs/${encodeURIComponent(runId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decided_by: decidedBy }),
  });

export const rejectRun = (runId: string, decidedBy: string) =>
  request<WorkflowRun>(`/runs/${encodeURIComponent(runId)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ decided_by: decidedBy }),
  });

export const resumeRun = (runId: string, inputs: Record<string, string>, decidedBy: string) =>
  request<WorkflowRun>(`/runs/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    body: JSON.stringify({ inputs, decided_by: decidedBy }),
  });
