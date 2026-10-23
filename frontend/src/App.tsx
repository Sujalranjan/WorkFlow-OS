import React, { useState } from 'react';
import { listRuns } from './api';
import { OperatorContext, href, readOperator, saveOperator, useLoad, useRoute } from './ui';
import { OverviewPage } from './pages/OverviewPage';
import { ActivityPage } from './pages/ActivityPage';
import { WorkflowsPage } from './pages/WorkflowsPage';
import { WorkflowDetailPage } from './pages/WorkflowDetailPage';
import { InboxPage } from './pages/InboxPage';
import { AutomationsPage } from './pages/AutomationsPage';
import { RunsPage } from './pages/RunsPage';

const NAV = [
  { id: '', label: 'Overview' },
  { id: 'activity', label: 'Activity' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'inbox', label: 'Inbox' },
  { id: 'automations', label: 'Automations' },
  { id: 'runs', label: 'Runs' },
];

export const App: React.FC = () => {
  const route = useRoute();
  const [page, param] = route;
  const [operator, setOperator] = useState(readOperator);
  const inbox = useLoad(() => listRuns(['PENDING_APPROVAL', 'NEEDS_INPUT'], 200), [], 15000);
  const inboxCount = inbox.data?.length || 0;

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
    default:
      content = <OverviewPage inboxCount={inboxCount} />;
  }

  return (
    <OperatorContext.Provider value={operator.trim() || 'operator'}>
      <div className="shell">
        <aside className="sidebar">
          <a className="brand" href={href()}>
            <span className="brand-mark" aria-hidden="true">W</span>
            <span>WorkFlowOS</span>
          </a>
          <nav className="nav" aria-label="Main">
            {NAV.map((item) => {
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
          <label className="operator">
            Your name
            <input
              value={operator}
              placeholder="used when you approve"
              onChange={(e) => {
                setOperator(e.target.value);
                saveOperator(e.target.value);
              }}
            />
          </label>
        </aside>
        <main className="content">{content}</main>
      </div>
    </OperatorContext.Provider>
  );
};

export default App;
