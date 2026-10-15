export interface EmailTrigger {
  trigger_id: string;
  workflow_id: string;
  name: string;
  gmail_query: string;
  enabled: boolean;
  poll_interval_seconds: number;
  active_since: number;
  created_at: string;
  last_polled_at: string | null;
  last_error: string | null;
}

export type RunStatus =
  | 'PENDING_APPROVAL'
  | 'RUNNING'
  | 'NEEDS_INPUT'
  | 'COMPLETED'
  | 'FAILED'
  | 'BLOCKED'
  | 'REJECTED';

export interface SourceEmail {
  message_id: string;
  thread_id: string | null;
  subject: string | null;
  sender: string | null;
  snippet: string | null;
  received_at: string | null;
  attachment_names: string[];
}

export interface CustomerCandidate {
  customer_id: string;
  name: string | null;
  email: string | null;
  company: string | null;
  status: string | null;
}

export interface Intervention {
  parameter?: string;
  reason?: string;
  code?: 'NO_MATCH' | 'MULTIPLE_MATCHES' | string;
  accepted_inputs?: string[];
  candidates?: CustomerCandidate[];
  step?: string | null;
}

export interface WorkflowRun {
  run_id: string;
  trigger_id: string;
  workflow_id: string;
  source_email: SourceEmail;
  gmail_query: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  decided_by: string | null;
  execution_plan_id: string | null;
  execution_id: string | null;
  verification_status: string | null;
  intervention: Intervention | null;
  error: string | null;
}

export interface PollResult {
  trigger_id: string;
  polled_at: string;
  matched: number;
  new_runs: WorkflowRun[];
  error: string | null;
}
