import React from 'react';
import { DiscoveryCandidate } from '../types/discovery';

interface DiscoveryViewProps {
  candidates: DiscoveryCandidate[];
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export const DiscoveryView: React.FC<DiscoveryViewProps> = ({
  candidates,
  isLoading,
  error,
  onRefresh,
}) => {
  return (
    <section className="discovery-section">
      <div className="discovery-header">
        <div>
          <div className="discovery-badge">Workflow Discovery Engine</div>
          <h2 className="section-title">Discovered Workflow Candidates</h2>
          <p className="discovery-subtitle">
            Deterministic sequence clustering and repetition detection across user activity sessions.
          </p>
        </div>
        <button
          className="refresh-button discovery-refresh-btn"
          onClick={onRefresh}
          disabled={isLoading}
        >
          {isLoading ? 'Analyzing...' : 'Run Discovery Analysis'}
        </button>
      </div>

      {error && <div className="events-error">{error}</div>}

      {candidates.length === 0 && !isLoading && !error && (
        <div className="discovery-empty">
          No recurring workflow candidates detected yet. Record repetitive activity sessions to discover patterns.
        </div>
      )}

      {candidates.length > 0 && (
        <div className="candidates-grid">
          {candidates.map((cand, idx) => {
            const similarityPercent = Math.round(cand.average_similarity_score * 100);

            return (
              <div key={cand.candidate_id} className="candidate-card">
                <div className="candidate-card-header">
                  <div className="candidate-title-group">
                    <span className="candidate-rank">#{idx + 1}</span>
                    <h3 className="candidate-name">Discovered Pattern Candidate</h3>
                  </div>
                  <div className="candidate-meta-badges">
                    <span className="candidate-badge occurrence-badge">
                      {cand.occurrences} Occurrences
                    </span>
                    <span className="candidate-badge similarity-badge">
                      {similarityPercent}% Similarity
                    </span>
                  </div>
                </div>

                <div className="candidate-sequence-diagram">
                  <div className="sequence-label">Representative Sequence:</div>
                  <div className="sequence-flow">
                    {cand.representative_sequence.map((step, sIdx) => (
                      <React.Fragment key={step.step_index}>
                        <div className="sequence-node">
                          <span className="node-step">Step {step.step_index}</span>
                          <span className="node-app">{step.application}</span>
                          <span className="node-action">{step.event_type}</span>
                        </div>
                        {sIdx < cand.representative_sequence.length - 1 && (
                          <span className="sequence-arrow">→</span>
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>

                <div className="candidate-signature">
                  <strong>Normalized Signature:</strong>
                  <code>{cand.normalized_signature}</code>
                </div>

                <div className="candidate-evidence-box">
                  <strong>Evidence & Explainability:</strong>
                  <p>{cand.evidence}</p>
                </div>

                <div className="candidate-footer">
                  <span>First Seen: {new Date(cand.first_seen).toLocaleTimeString()}</span>
                  <span>Last Seen: {new Date(cand.last_seen).toLocaleTimeString()}</span>
                  <span>Supporting Sessions: {cand.supporting_session_ids.length}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
