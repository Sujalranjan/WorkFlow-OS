import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityEvent } from './types/event';
import { RiskCategory } from './types/canonical';
import type { User } from './api';

// --- routing (hash based, so links and refresh work without a server router) --------

export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState<string[]>(read);
  useEffect(() => {
    const onChange = () => setParts(read());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return parts;
}

export const href = (...parts: string[]) => `#/${parts.map(encodeURIComponent).join('/')}`;
export const go = (...parts: string[]) => {
  window.location.hash = href(...parts);
};

// --- data loading ------------------------------------------------------------------

export function useLoad<T>(load: () => Promise<T>, deps: React.DependencyList, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    try {
      const value = await loadRef.current();
      setData(value);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    setLoading(true);
    reload();
    if (!refreshMs) return;
    const id = window.setInterval(reload, refreshMs);
    return () => window.clearInterval(id);
  }, [reload, refreshMs]);

  return { data, error, loading, reload };
}

/** Run a user action with a busy flag and a single error/notice message. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, success?: string | ((r: T) => string)) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      if (success) setNotice(typeof success === 'function' ? success(result) : success);
      return result;
    } catch (e) {
      setError(errorText(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, error, notice, run, setError, setNotice };
}

export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

// --- signed-in user -----------------------------------------------------------------

export interface SessionInfo {
  user: User;
  /** True if the signed-in user's role may call this route ("POST /api/automation/triggers"). */
  can: (route: string) => boolean;
}

export const SessionContext = React.createContext<SessionInfo | null>(null);

export function useSession(): SessionInfo {
  const session = React.useContext(SessionContext);
  if (!session) throw new Error('useSession used outside the signed-in app');
  return session;
}

/** Routes behind the main actions, so pages can hide what the user's role does not allow. */
export const CAN = {
  createWorkflow: 'POST /api/workflows/{semantic_workflow_id}/specification',
  reviewWorkflow: 'POST /api/workflows/specifications/{workflow_id}/approve',
  runWorkflow: 'POST /api/workflows/execution-plans/{execution_plan_id}/execute',
  decideRun: 'POST /api/automation/runs/{run_id}/approve',
  verify: 'POST /api/workflows/executions/{execution_id}/verify',
  manageTriggers: 'POST /api/automation/triggers',
  loadSample: 'POST /api/demo/seed-activity',
  manageUsers: 'POST /api/auth/users',
};

// --- formatting --------------------------------------------------------------------

export function formatTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function timeAgo(value?: string | null): string {
  if (!value) return 'never';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return formatTime(value);
}

export const pct = (ratio: number) => `${Math.round((ratio || 0) * 100)}%`;

const humanize = (s: string) => {
  const t = s.replace(/[._:-]+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

// --- plain-language labels ----------------------------------------------------------

const ACTION_LABELS: Record<string, string> = {
  search_email: 'Find the request email',
  download_attachment: 'Save the email attachment',
  download_email_attachment: 'Save the email attachment',
  find_customer: 'Look up the customer',
  get_customer: 'Look up the customer',
  update_customer_record: 'Update the customer record',
  update_customer: 'Update the customer record',
  send_notification: 'Notify the team',
  notify: 'Notify the team',
  window_focused: 'Switch to the app',
};

export function actionLabel(action: string, application?: string): string {
  const key = action.toLowerCase().trim().replace(/\s+/g, '_');
  const base = ACTION_LABELS[key] || humanize(action);
  return application ? `${base} · ${application}` : base;
}

export function riskLabel(category: RiskCategory | string, application: string, needsConfirmation: boolean): string {
  const text: Record<string, string> = {
    read_only: 'Reads only',
    local_change: 'Saves a local file',
    external_change: `Changes data in ${application}`,
    communication: 'Sends a message',
    potentially_sensitive: 'Touches sensitive data',
  };
  const base = text[category] || humanize(String(category));
  return needsConfirmation ? `${base} · needs confirmation` : base;
}

export function riskTone(level: string): Tone {
  return level === 'high' ? 'bad' : level === 'medium' ? 'warn' : 'neutral';
}

export type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'info';

const STATUS: Record<string, [string, Tone]> = {
  // workflow review
  requires_review: ['Needs review', 'warn'],
  draft: ['Draft', 'neutral'],
  approved: ['Approved', 'good'],
  rejected: ['Rejected', 'neutral'],
  // runs and executions
  pending_approval: ['Awaiting approval', 'warn'],
  needs_input: ['Needs your input', 'warn'],
  running: ['Running', 'info'],
  completed: ['Completed', 'good'],
  success: ['Done', 'good'],
  failed: ['Failed', 'bad'],
  blocked: ['Stopped', 'bad'],
  skipped: ['Skipped', 'neutral'],
  cancelled: ['Cancelled', 'neutral'],
  pending: ['Pending', 'neutral'],
  simulated: ['Would run', 'info'],
  blocked_unresolved: ['Missing input', 'bad'],
  // verification
  verified: ['Verified', 'good'],
  unknown: ["Couldn't verify", 'warn'],
  not_applicable: ['Nothing to verify', 'neutral'],
  // triggers
  enabled: ['On', 'good'],
  paused: ['Paused', 'neutral'],
};

export const Badge: React.FC<{ status: string; label?: string; tone?: Tone }> = ({ status, label, tone }) => {
  const [text, t] = STATUS[status.toLowerCase()] || [humanize(status.toLowerCase()), 'neutral' as Tone];
  return <span className={`badge badge-${tone || t}`}>{label || text}</span>;
};

/** A readable line for one observed event, and the app it really happened in. */
export function describeEvent(e: ActivityEvent): { app: string; text: string } {
  const m = e.metadata || {};
  const str = (k: string) => (typeof m[k] === 'string' ? (m[k] as string) : '');
  let app = e.application || '—';

  const action = str('workflow_action');
  if (action) {
    const params = (m.action_parameters as Record<string, unknown>) || {};
    const detail = Object.values(params).filter((v) => typeof v === 'string' && v).join(', ');
    return { app, text: `${actionLabel(action.split('.').pop() || action)}${detail ? ` (${detail})` : ''}` };
  }

  let url: URL | null = null;
  try {
    url = str('url') ? new URL(str('url')) : null;
  } catch {
    url = null;
  }
  if (url) {
    const host = url.hostname;
    const crmMatch = url.pathname.match(/\/ui\/customers(?:\/([^/]+))?/);
    if (host.endsWith('mail.google.com')) {
      app = 'Gmail';
      const search = url.hash.match(/^#search\/([^/]+)(\/.+)?/);
      if (e.event_type === 'file_downloaded') return { app, text: `Downloaded attachment ${str('file_name') || ''}`.trim() };
      if (search) {
        const q = decodeURIComponent(search[1].replace(/\+/g, ' '));
        return { app, text: search[2] ? `Opened an email from the search “${q}”` : `Searched email for “${q}”` };
      }
    } else if (host === 'app.slack.com') {
      app = 'Slack';
      const channel = url.pathname.split('/').filter(Boolean)[2];
      if (e.event_type === 'form_submitted') return { app, text: `Posted a message${channel ? ` in ${channel}` : ''}` };
      return { app, text: `Opened ${channel || 'Slack'}` };
    } else if (crmMatch) {
      app = 'CRM';
      const id = crmMatch[1];
      const fields = (m.form_fields as Record<string, unknown>) || {};
      if (e.event_type === 'form_submitted' && id) {
        const changes = Object.entries(fields).map(([k, v]) => `${k} = ${v}`).join(', ');
        return { app, text: `Updated customer ${id}${changes ? ` (${changes})` : ''}` };
      }
      if (id) return { app, text: `Opened customer ${id}` };
      const q = url.searchParams.get('q');
      return { app, text: q ? `Searched customers for “${q}”` : 'Opened the customer list' };
    }
  }

  switch (e.event_type) {
    case 'browser_navigation':
      return { app, text: `Visited ${str('tab_title') || (url ? url.hostname + url.pathname : 'a page')}` };
    case 'window_focused':
      return { app, text: `Switched to ${str('window_title') || e.application || 'a window'}` };
    case 'file_downloaded':
      return { app, text: `Downloaded ${str('file_name') || 'a file'}` };
    case 'file_created':
      return { app, text: `Created ${str('file_name') || str('path') || 'a file'}` };
    case 'file_opened':
      return { app, text: `Opened ${str('file_name') || str('path') || 'a file'}` };
    case 'file_moved':
      return { app, text: `Moved ${str('file_name') || 'a file'}` };
    case 'form_submitted':
      return { app, text: 'Submitted a form' };
    case 'application_opened':
      return { app, text: `Opened ${e.application || 'an app'}` };
    case 'application_closed':
      return { app, text: `Closed ${e.application || 'an app'}` };
    default:
      return { app, text: humanize(e.event_type) };
  }
}

// --- small building blocks ----------------------------------------------------------

export const Alert: React.FC<{ tone?: 'error' | 'ok' | 'info'; children: React.ReactNode }> = ({
  tone = 'error',
  children,
}) => (
  <div className={`alert alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    {children}
  </div>
);

export const Empty: React.FC<{ title: string; children?: React.ReactNode }> = ({ title, children }) => (
  <div className="empty">
    <p className="empty-title">{title}</p>
    {children && <div className="empty-body">{children}</div>}
  </div>
);

export const PageHeader: React.FC<{ title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }> = ({
  title,
  subtitle,
  actions,
}) => (
  <header className="page-header">
    <div>
      <h1>{title}</h1>
      {subtitle && <p className="page-subtitle">{subtitle}</p>}
    </div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
);

export const Loading: React.FC = () => <p className="muted">Loading…</p>;
