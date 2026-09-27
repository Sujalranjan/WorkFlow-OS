import React from 'react';
import { WorkflowDNA } from '../types/dna';

interface DNAViewProps {
  dnaItems: WorkflowDNA[];
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  selectedDnaId?: string | null;
  onSelectDnaId?: (dnaId: string) => void;
  onNavigateToSemantic?: (dnaId: string) => void;
}

export const DNAView: React.FC<DNAViewProps> = ({
  dnaItems,
  isLoading,
  error,
  onRefresh,
  selectedDnaId,
  onSelectDnaId,
  onNavigateToSemantic,
}) => {
  return (
    <section className="dna-section">
      <div className="dna-header">
        <div>
          <div className="dna-badge">Phase 4: Workflow DNA Extraction</div>
          <h2 className="section-title">Workflow DNA Analysis</h2>
          <p className="dna-subtitle">
            Deterministic extraction of invariants, variable parameters, optional steps, ordering constraints, and evidence.
          </p>
        </div>
        <button
          className="refresh-button dna-refresh-btn"
          onClick={onRefresh}
          disabled={isLoading}
        >
          {isLoading ? 'Extracting DNA...' : 'Extract Workflow DNA'}
        </button>
      </div>

      {error && <div className="events-error">{error}</div>}

      {dnaItems.length === 0 && !isLoading && !error && (
        <div className="dna-empty">
          No Workflow DNA extracted yet. Ensure repeated discovery candidates exist and run DNA extraction.
        </div>
      )}

      {dnaItems.length > 0 && (
        <div className="dna-grid">
          {dnaItems.map((dna, idx) => {
            const isSelected = selectedDnaId === dna.dna_id;

            return (
              <div
                key={dna.dna_id}
                id={`dna-card-${dna.dna_id}`}
                className={`dna-card ${isSelected ? 'selected-dna-card' : ''}`}
                onClick={() => onSelectDnaId?.(dna.dna_id)}
                style={{ cursor: 'pointer' }}
              >
                {/* Header */}
                <div className="dna-card-header">
                  <div className="dna-title-group">
                    <span className="dna-helix-icon" role="img" aria-label="DNA">🧬</span>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <h3 className="dna-title">Workflow DNA #{idx + 1}</h3>
                        {isSelected && (
                          <span className="dna-badge-pill pill-selected">
                            Selected Workflow DNA
                          </span>
                        )}
                      </div>
                      <span className="dna-id-subtext">{dna.dna_id} &bull; v{dna.version}</span>
                    </div>
                  </div>
                  <div className="dna-meta-badges">
                    <button
                      type="button"
                      className="btn-dna-to-semantic"
                      onClick={(e) => {
                        e.stopPropagation();
                        onNavigateToSemantic?.(dna.dna_id);
                      }}
                    >
                      Interpret with Gemini &rarr;
                    </button>
                    <span className="dna-badge-pill pill-sessions">
                      {dna.boundaries.total_supporting_sessions} Sessions
                    </span>
                    <span className="dna-badge-pill pill-invariants">
                      {dna.invariant_steps.length} Invariants
                    </span>
                    <span className="dna-badge-pill pill-variables">
                      {dna.variable_parameters.length} Variables
                    </span>
                    {dna.optional_steps.length > 0 && (
                      <span className="dna-badge-pill pill-optionals">
                        {dna.optional_steps.length} Optional
                      </span>
                    )}
                  </div>
                </div>

                <div className="dna-body-grid">
                  {/* 1. Core / Invariant Steps */}
                  <div className="dna-panel panel-invariants">
                    <div className="panel-header">
                      <span className="panel-icon">✓</span>
                      <h4>Core / Invariant Steps</h4>
                    </div>
                    <ul className="dna-list invariant-list">
                      {dna.invariant_steps.map((inv) => (
                        <li key={inv.step_key} className="invariant-item">
                          <span className="check-icon">✓</span>
                          <span className="step-name">{inv.application}</span>
                          <span className="step-type">({inv.event_type})</span>
                          <span className="occurrence-ratio">
                            {inv.occurrences}/{inv.total_sessions} ({Math.round(inv.occurrence_ratio * 100)}%)
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 2. Variable Parameters */}
                  <div className="dna-panel panel-variables">
                    <div className="panel-header">
                      <span className="panel-icon">⚲</span>
                      <h4>Variable Parameters</h4>
                    </div>
                    {dna.variable_parameters.length === 0 ? (
                      <div className="panel-empty-text">No variable variations detected across executions.</div>
                    ) : (
                      <div className="variable-list">
                        {dna.variable_parameters.map((param) => (
                          <div key={param.parameter_name} className="variable-item">
                            <div className="var-top-row">
                              <span className="var-bullet">•</span>
                              <strong className="var-name">{param.parameter_name}</strong>
                              <span className="var-source">{param.source_field}</span>
                            </div>
                            {param.pattern_template && (
                              <div className="var-pattern">
                                Pattern: <code>{param.pattern_template}</code>
                              </div>
                            )}
                            <div className="var-values">
                              <span className="var-values-label">Observed ({param.distinct_value_count}):</span>
                              <div className="var-tag-cloud">
                                {param.observed_values.map((val) => (
                                  <span key={val} className="var-tag" title={val}>
                                    {val}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 3. Optional Steps */}
                  <div className="dna-panel panel-optionals">
                    <div className="panel-header">
                      <span className="panel-icon">?</span>
                      <h4>Optional Steps</h4>
                    </div>
                    {dna.optional_steps.length === 0 ? (
                      <div className="panel-empty-text">No optional steps; executions adhered strictly to core steps.</div>
                    ) : (
                      <ul className="dna-list optional-list">
                        {dna.optional_steps.map((opt) => (
                          <li key={opt.step_key} className="optional-item">
                            <span className="opt-bullet">•</span>
                            <span className="step-name">{opt.application}</span>
                            <span className="step-type">({opt.event_type})</span>
                            <span className="opt-ratio">
                              {opt.occurrences}/{opt.total_sessions} ({Math.round(opt.occurrence_ratio * 100)}%)
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* 4. Ordering Precedence Flow */}
                  <div className="dna-panel panel-ordering">
                    <div className="panel-header">
                      <span className="panel-icon">➔</span>
                      <h4>Ordering Precedence</h4>
                    </div>
                    <div className="ordering-flow">
                      {dna.invariant_steps.map((inv, sIdx) => (
                        <React.Fragment key={inv.step_key}>
                          <div className="order-node">
                            <span className="order-app">{inv.application}</span>
                            <span className="order-type">{inv.event_type}</span>
                          </div>
                          {sIdx < dna.invariant_steps.length - 1 && (
                            <span className="order-arrow">→</span>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                    <div className="constraints-list">
                      {dna.ordering_constraints.map((oc, cIdx) => (
                        <div key={cIdx} className="constraint-item">
                          <code>{oc.description}</code>
                          <span className="constraint-consistency">
                            100% consistent
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Preconditions & Boundaries */}
                <div className="dna-boundaries-box">
                  <div className="boundaries-header">
                    <strong>Preconditions & Structural Boundaries</strong>
                  </div>
                  <div className="preconditions-list">
                    {dna.preconditions.map((prec, pIdx) => (
                      <div key={pIdx} className="precondition-item">
                        <span className="prec-bullet">↳</span>
                        <span>{prec}</span>
                      </div>
                    ))}
                  </div>
                  <div className="boundaries-metrics">
                    <span>Boundary: <code>{dna.boundaries.first_step}</code> → <code>{dna.boundaries.last_step}</code></span>
                    <span>Duration: Min {dna.boundaries.min_duration_seconds}s | Avg {dna.boundaries.average_duration_seconds}s | Max {dna.boundaries.max_duration_seconds}s</span>
                  </div>
                </div>

                {/* Evidence & Explainability */}
                <div className="dna-evidence-box">
                  <div className="evidence-header">
                    <strong>Evidence & Explainability ({dna.evidence.supporting_session_count} supporting sessions)</strong>
                  </div>
                  <div className="evidence-grid">
                    <div className="evidence-card">
                      <span className="evidence-label">Invariants:</span>
                      <p>{dna.evidence.invariant_evidence}</p>
                    </div>
                    <div className="evidence-card">
                      <span className="evidence-label">Variables:</span>
                      <p>{dna.evidence.variable_evidence}</p>
                    </div>
                    <div className="evidence-card">
                      <span className="evidence-label">Optional Steps:</span>
                      <p>{dna.evidence.optional_step_evidence}</p>
                    </div>
                    <div className="evidence-card">
                      <span className="evidence-label">Ordering & Timing:</span>
                      <p>{dna.evidence.ordering_evidence} {dna.evidence.boundary_evidence}</p>
                    </div>
                  </div>
                </div>

                {/* Transition Action to Stage 3 */}
                <div className="dna-card-action-bar">
                  <div className="dna-card-action-meta">
                    <span className="dna-ready-icon">✦</span>
                    <span>
                      Deterministic DNA extracted ({dna.invariant_steps.length} core invariants, {dna.variable_parameters.length} variable parameters). Ready for AI Semantic Understanding.
                    </span>
                  </div>
                  <button
                    type="button"
                    className="btn-dna-action-semantic"
                    onClick={(e) => {
                      e.stopPropagation();
                      onNavigateToSemantic?.(dna.dna_id);
                    }}
                  >
                    Interpret with Gemini &rarr;
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
