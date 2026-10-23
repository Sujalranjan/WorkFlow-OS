import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Session, UNAUTHORIZED_EVENT, getSession, listRuns, logout } from './api';
import { CAN, SessionContext, SessionInfo, href, useLoad, useRoute } from './ui';
import { OverviewPage } from './pages/OverviewPage';
import { ActivityPage } from './pages/ActivityPage';
import { WorkflowsPage } from './pages/WorkflowsPage';
import { WorkflowDetailPage } from './pages/WorkflowDetailPage';
import { InboxPage } from './pages/InboxPage';
import { AutomationsPage } from './pages/AutomationsPage';
import { RunsPage } from './pages/RunsPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoginPage } from './pages/LoginPage';

const NAV = [
  { id: '', label: 'Overview' },
  { id: 'activity', label: 'Activity' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'inbox', label: 'Inbox' },
  { id: 'automations', label: 'Automations' },
  { id: 'runs', label: 'Runs' },
];

export const App: React.FC = () => {
  // undefined: still checking; null: signed out
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    getSession()
      .then(setSession)
      .catch(() => setSession(null));
    const onUnauthorized = () =>
      setSession((current) => {
        if (current) setNotice('Your session ended. Please sign in again.');
        return null;
      });
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (session === undefined) return <p className="muted center">Loading…</p>;
  if (session === null) {
    return (
      <LoginPage
        notice={notice}
        onSignedIn={(s) => {
          setNotice(null);
          setSession(s);
        }}
      />
    );
  }
  return <SignedInApp session={session} onSignedOut={() => setSession(null)} />;
};

const SignedInApp: React.FC<{ session: Session; onSignedOut: () => void }> = ({ session, onSignedOut }) => {
  const [page, param] = useRoute();
  const info: SessionInfo = useMemo(() => {
    const allowed = new Set(session.permissions);
    return { user: session.user, can: (route: string) => allowed.has(route) };
  }, [session]);
  const inbox = useLoad(() => listRuns(['PENDING_APPROVAL', 'NEEDS_INPUT'], 200), [], 15000);
  const inboxCount = inbox.data?.length || 0;
  const isAdmin = info.can(CAN.manageUsers);

  const signOut = useCallback(async () => {
    await logout().catch(() => undefined);
    onSignedOut();
  }, [onSignedOut]);

  let content: React.ReactNode;
  switch (page || '') {
    case 'activity':
      content = <ActivityPage />;
      break;
    case 'workflows':
      content = param ? <WorkflowDetailPage workflowId={param} /> : <WorkflowsPage />;
      break;
    case 'inbox':
      content = <InboxPage onChange={inbox.reload} />;
      break;
    case 'automations':
      content = <AutomationsPage />;
      break;
    case 'runs':
      content = <RunsPage executionId={param} />;
      break;
    case 'settings':
      content = isAdmin ? <SettingsPage /> : <p className="muted">Only admins can open Settings.</p>;
      break;
    default:
      content = <OverviewPage inboxCount={inboxCount} />;
  }

  const nav = isAdmin ? [...NAV, { id: 'settings', label: 'Settings' }] : NAV;

  return (
    <SessionContext.Provider value={info}>
      <div className="shell">
        <aside className="sidebar">
          <a className="brand" href={href()}>
            <span className="brand-mark" aria-hidden="true">W</span>
            <span>WorkFlowOS</span>
          </a>
          <nav className="nav" aria-label="Main">
            {nav.map((item) => {
              const active = (page || '') === item.id;
              return (
                <a
                  key={item.id}
                  href={href(...(item.id ? [item.id] : []))}
                  className={`nav-link${active ? ' nav-link-active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                >
                  {item.label}
                  {item.id === 'inbox' && inboxCount > 0 && <span className="nav-count">{inboxCount}</span>}
                </a>
              );
            })}
          </nav>
          <div className="user-box">
            <div className="user-name">{session.user.name}</div>
            <div className="muted small">
              {session.user.email} · {session.user.role}
            </div>
            <button className="btn-secondary" onClick={signOut}>
              Sign out
            </button>
          </div>
        </aside>
        <main className="content">{content}</main>
      </div>
    </SessionContext.Provider>
  );
};

export default App;
