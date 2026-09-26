export type ActivityEventType =
  | 'application_opened'
  | 'application_closed'
  | 'window_focused'
  | 'browser_navigation'
  | 'file_created'
  | 'file_opened'
  | 'file_downloaded'
  | 'file_moved'
  | 'form_submitted'
  | 'generic_ui_action';

export interface ActivityEvent {
  event_id: string;
  event_type: ActivityEventType;
  timestamp: string;
  application: string | null;
  source: string;
  metadata: Record<string, unknown>;
}
