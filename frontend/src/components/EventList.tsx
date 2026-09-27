import React from 'react';
import { ActivityEvent } from '../types/event';
import { SeedActivityResponse } from '../services/api';

interface EventListProps {
  events: ActivityEvent[];
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  onSeedDemoActivity?: (scenario?: 'local_file_automation' | 'invoice_processing') => Promise<void>;
  isSeeding?: boolean;
  seedResult?: SeedActivityResponse | null;
  onNavigateToDiscover?: () => void;
}

export const EventList: React.FC<EventListProps> = ({
  events,
  isLoading,
  error,
  onRefresh,
  onSeedDemoActivity,
  isSeeding = false,
  seedResult = null,
  onNavigateToDiscover,
}) => {
  return (
    <section className="events-section">
      <div className="events-header">
        <div className="events-title-group">
          <h2 className="section-title">Ingested Activity Events</h2>
          <span className="events-count-badge">{events.length} Events</span>
        </div>
        <button
          className="refresh-button"
          onClick={onRefresh}
          disabled={isLoading || isSeeding}
        >
          {isLoading ? 'Refreshing...' : 'Refresh Events'}
        </button>
      </div>

      {/* Synthetic Demo Activity Seeding Card (Phase 15) */}
      <div className="demo-seeding-card">
        <div className="demo-seeding-content">
          <div className="demo-seeding-info">
            <div className="demo-seeding-badge">Synthetic Activity Seeding</div>
            <strong className="demo-seeding-title">Deterministic Demonstration Traces</strong>
            <p className="demo-seeding-description">
              Populate deterministic repeated desktop activity so WorkFlowOS can discover recurring patterns.
              <strong> Track A</strong> seeds a local filesystem routine (reconciliation &amp; archiving) that executes 100% inside sandbox.
              <strong> Multi-App</strong> seeds cross-application activity (Gmail, CRM, Slack) to demonstrate that the execution engine safely blocks unimplemented external tools.
            </p>
            {events.length > 0 && (
              <span className="demo-seeding-existing-note">
                Note: Seeding adds another deterministic set of events to SQLite without deleting existing events. Use <strong>Reset Demo State</strong> in the header if you wish to start from an empty database.
              </span>
            )}
          </div>

          {onSeedDemoActivity && (
            <div className="demo-seeding-actions" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn-seed-activity"
                onClick={() => onSeedDemoActivity('local_file_automation')}
                disabled={isSeeding || isLoading}
                title="Populate SQLite event store with deterministic local filesystem routine"
              >
                {isSeeding ? (
                  <>
                    <span className="btn-spinner" /> Seeding...
                  </>
                ) : (
                  '⚡ Seed Local Routine (Track A)'
                )}
              </button>
              <button
                type="button"
                className="btn-seed-secondary"
                onClick={() => onSeedDemoActivity('invoice_processing')}
                disabled={isSeeding || isLoading}
                title="Populate SQLite event store with cross-app events for policy safety demo"
              >
                ⚡ Multi-App Policy Trace
              </button>
            </div>
          )}
        </div>

        {/* Post-Seeding Status Banner */}
        {seedResult && (
          <div className="demo-seeding-success">
            <div className="seeding-success-header">
              <span className="seeding-check">✓</span>
              <div>
                <strong className="seeding-success-title">Demo Activity Seeded Successfully</strong>
                <div className="seeding-success-meta">
                  {seedResult.events_created} events created &bull; {seedResult.sessions_created} repeated task sessions &bull; Scenario: <code>{seedResult.scenario}</code>
                </div>
              </div>
            </div>
            <p className="seeding-success-note">
              Events are now stored in SQLite and visible below. Workflows have NOT been discovered yet.
              Proceed to Stage 2 to analyze patterns.
            </p>
            {onNavigateToDiscover && (
              <div className="seeding-nav-row">
                <button
                  type="button"
                  className="btn-analyze-activity"
                  onClick={onNavigateToDiscover}
                >
                  Analyze Discovered Activity &rarr;
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {error && <div className="events-error">{error}</div>}

      {events.length === 0 && !isLoading && !error && (
        <div className="events-empty">
          No activity events ingested yet. Click <strong>"⚡ Seed Demo Activity"</strong> above to populate sample events, or run the desktop agent with live window &amp; filesystem monitoring.
        </div>
      )}

      {events.length > 0 && (
        <div className="events-table-wrapper">
          <table className="events-table">
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Type</th>
                <th>Application</th>
                <th>Category</th>
                <th>Source</th>
                <th>Details / Metadata</th>
              </tr>
            </thead>
            <tbody>
              {events.map((evt) => {
                const isReal = evt.metadata && (
                  evt.metadata.collector === 'WindowsWindowCollector' ||
                  evt.metadata.collector === 'FileSystemCollector'
                );

                return (
                  <tr key={evt.event_id}>
                    <td className="timestamp-cell">
                      {new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                    <td>
                      <span className="event-type-tag">{evt.event_type}</span>
                    </td>
                    <td className="app-cell">
                      {evt.application ? (
                        <span className="app-tag">{evt.application}</span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td>
                      <span className={`origin-badge ${isReal ? 'origin-real' : 'origin-simulated'}`}>
                        {isReal ? 'Live OS' : evt.source === 'demo_seed' ? 'Synthetic Demo' : 'Simulated'}
                      </span>
                    </td>
                    <td className="source-cell">{evt.source}</td>
                    <td className="metadata-cell">
                      {evt.metadata && typeof evt.metadata.window_title === 'string' && evt.metadata.window_title && (
                        <div className="window-title-preview">
                          <strong>Title:</strong> {evt.metadata.window_title}
                        </div>
                      )}
                      {evt.metadata && typeof evt.metadata.file_name === 'string' && (
                        <div className="window-title-preview">
                          <strong>File:</strong> {evt.metadata.file_name}
                        </div>
                      )}
                      <details className="metadata-details">
                        <summary className="metadata-summary">Full JSON</summary>
                        <pre className="metadata-pre">
                          {JSON.stringify(evt.metadata, null, 2)}
                        </pre>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
