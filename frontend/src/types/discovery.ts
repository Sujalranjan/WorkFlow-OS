export interface NormalizedStep {
  step_index: number;
  application: string;
  event_type: string;
  action_key: string;
  is_optional: boolean;
}

export interface DiscoveryCandidate {
  candidate_id: string;
  normalized_signature: string;
  occurrences: number;
  first_seen: string;
  last_seen: string;
  applications: string[];
  event_types: string[];
  representative_sequence: NormalizedStep[];
  average_similarity_score: number;
  supporting_session_ids: string[];
  evidence: string;
  metadata: Record<string, unknown>;
}

export interface TaskSession {
  session_id: string;
  start_time: string;
  end_time: string;
  applications_involved: string[];
  event_count: number;
  duration_seconds: number;
  segmentation_reason: string;
}

export interface DiscoveryAnalysisResponse {
  total_events_analyzed: number;
  total_sessions_found: number;
  candidate_count: number;
  sessions: TaskSession[];
  candidates: DiscoveryCandidate[];
}
