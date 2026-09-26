import React from 'react';
import { ActivityEvent } from '../types/event';

interface EventListProps {
  events: ActivityEvent[];
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export const EventList: React.FC<EventListProps> = ({
  events,
  isLoading,
  error,
  onRefresh,
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
          disabled={isLoading}
        >
          {isLoading ? 'Refreshing...' : 'Refresh Events'}
        </button>
      </div>

      {error && <div className="events-error">{error}</div>}

      {events.length === 0 && !isLoading && !error && (
        <div className="events-empty">
          No activity events ingested yet. Switch active windows or add files in watch_folder.
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
                        {isReal ? 'Live OS' : 'Simulated'}
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
