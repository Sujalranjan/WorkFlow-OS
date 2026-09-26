import React, { useState } from 'react';
import { WorkflowDNA } from '../types/dna';
import { InterpretationResponse, SemanticWorkflow } from '../types/semantic';

interface SemanticViewProps {
  dnaItems: WorkflowDNA[];
  interpretations: Record<string, InterpretationResponse>;
  isLoading: boolean;
  interpretingDnaId: string | null;
  onInterpret: (dnaId: string, providerType?: string) => Promise<void>;
}

export const SemanticView: React.FC<SemanticViewProps> = ({
  dnaItems,
  interpretations,
  isLoading,
  interpretingDnaId,
  onInterpret,
}) => {
  const [providerOverride, setProviderOverride] = useState<string>('default');

  if (dnaItems.length === 0) {
    return null;
  }

  return (
    <section className="semantic-section">
      <div className="semantic-header">
        <div>
          <div className="semantic-badge">Phase 5: AI Semantic Understanding</div>
          <h2 className="section-title">Semantic Workflow Interpretation</h2>
          <p className="semantic-subtitle">
            Translates deterministic Workflow DNA into human intent using LLM inference while rigorously grounding all claims in empirical evidence.
          </p>
        </div>

        <div className="semantic-controls">
          <select
            className="provider-select"
            value={providerOverride}
            onChange={(e) => setProviderOverride(e.target.value)}
            disabled={isLoading}
          >
            <option value="default">Provider: Auto (Gemini / Fallback)</option>
            <option value="mock">Provider: Mock LLM (Deterministic)</option>
            <option value="gemini">Provider: Live Gemini API</option>
          </select>
        </div>
      </div>

      <div className="semantic-workflows-container">
        {dnaItems.map((dna) => {
          const resp = interpretations[dna.dna_id];
          const isInterpretingThis = interpretingDnaId === dna.dna_id;
          const semWf: SemanticWorkflow | null = resp?.semantic_workflow || null;

          return (
            <div key={dna.dna_id} className="semantic-comparison-card">
              {/* Card Action Bar */}
              <div className="comparison-action-bar">
                <div className="comparison-title-meta">
                  <span className="source-dna-tag">Source DNA: <code>{dna.dna_id}</code></span>
                  <span className="status-pill-badge">
                    {semWf ? '✓ Semantic Interpretation Active' : 'Deterministic DNA Ready for AI Interpretation'}
                  </span>
                </div>
                <button
                  className="interpret-btn"
                  onClick={() => onInterpret(dna.dna_id, providerOverride === 'default' ? undefined : providerOverride)}
                  disabled={isLoading || isInterpretingThis}
                >
                  {isInterpretingThis
                    ? 'Interpreting with AI...'
                    : semWf
                    ? 'Re-Interpret with AI'
                    : 'Run AI Semantic Interpretation'}
                </button>
              </div>

              {resp?.status === 'fallback' && (
                <div className="semantic-fallback-banner">
                  <span className="fallback-icon">ℹ</span>
                  <div>
                    <strong>LLM Provider Fallback:</strong> {resp.message}
                    <div className="fallback-sub">
                      Deterministic WorkflowDNA is fully preserved. Set <code>GEMINI_API_KEY</code> in environment or switch provider to Mock LLM for offline testing.
                    </div>
                  </div>
                </div>
              )}

              {resp?.status === 'error' && (
                <div className="semantic-error-banner">
                  <span className="error-icon">⚠</span>
                  <div>
                    <strong>Semantic Interpretation Rejected:</strong> {resp.message}
                    {resp.validation_errors.length > 0 && (
                      <ul className="error-list">
                        {resp.validation_errors.map((err, eIdx) => (
                          <li key={eIdx}>{err}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}

              {/* Side-by-side / Dual Panel View */}
              <div className="comparison-dual-grid">
                {/* PANEL A: DETERMINISTIC / OBSERVED */}
                <div className="comparison-panel panel-deterministic">
                  <div className="panel-badge deterministic-badge">
                    <span>1. OBSERVED / DETERMINISTIC GROUND TRUTH</span>
                  </div>
                  <div className="panel-content">
                    <div className="sub-block">
                      <span className="sub-label">Observed Workflow Signature:</span>
                      <div className="seq-flow-compact">
                        {dna.invariant_steps.map((inv, sIdx) => (
                          <React.Fragment key={inv.step_key}>
                            <span className="compact-node">
                              <strong>{inv.application}</strong>
                              <small>{inv.event_type}</small>
                            </span>
                            {sIdx < dna.invariant_steps.length - 1 && <span className="arrow-sep">→</span>}
                          </React.Fragment>
                        ))}
                      </div>
                    </div>

                    <div className="sub-block">
                      <span className="sub-label">Structural Variable Parameters:</span>
                      <div className="structural-vars-list">
                        {dna.variable_parameters.map((v) => (
                          <div key={v.parameter_name} className="structural-var-tag">
                            <code>{v.parameter_name}</code>
                            <span className="source-note">({v.source_field})</span>
                            {v.pattern_template && (
                              <span className="pattern-note">Template: <code>{v.pattern_template}</code></span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="sub-block">
                      <span className="sub-label">Empirical Evidence:</span>
                      <p className="evidence-quote">"{dna.evidence.invariant_evidence}"</p>
                      <p className="evidence-quote">"{dna.evidence.variable_evidence}"</p>
                    </div>

                    <div className="sub-block">
                      <span className="sub-label">Precedence & Bounds:</span>
                      <div className="meta-compact">
                        <span>Sessions: {dna.boundaries.total_supporting_sessions}</span>
                        <span>Duration: {dna.boundaries.min_duration_seconds}s - {dna.boundaries.max_duration_seconds}s</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* PANEL B: AI INTERPRETATION */}
                <div className="comparison-panel panel-semantic">
                  <div className="panel-badge semantic-badge">
                    <span>2. AI INTERPRETATION (VALIDATED BY ENGINE)</span>
                  </div>
                  <div className="panel-content">
                    {!semWf ? (
                      <div className="semantic-placeholder">
                        <div className="placeholder-icon">✦</div>
                        <h4>No Semantic Interpretation Generated Yet</h4>
                        <p>
                          Click <strong>"Run AI Semantic Interpretation"</strong> to invoke the LLM semantic layer.
                          The LLM will infer business intent and map structural variables into semantic entities without modifying deterministic facts.
                        </p>
                      </div>
                    ) : (
                      <>
                        <div className="semantic-title-block">
                          <h3 className="wf-semantic-title">{semWf.title}</h3>
                          <div className="wf-semantic-intent">
                            <span className="intent-label">Operational Intent:</span>
                            <p>{semWf.intent}</p>
                          </div>
                          <p className="wf-semantic-summary">{semWf.summary}</p>
                        </div>

                        {/* Semantic Variable Mapping */}
                        <div className="sub-block">
                          <span className="sub-label">Semantic Variable Mappings:</span>
                          <div className="semantic-variables-grid">
                            {semWf.semantic_variables.map((sv) => (
                              <div key={sv.semantic_name} className="semantic-var-card">
                                <div className="var-mapping-header">
                                  <strong className="semantic-entity-name">{sv.semantic_name}</strong>
                                  <span className="mapping-arrow">←</span>
                                  <code className="source-param-name">{sv.source_parameter}</code>
                                </div>
                                <p className="var-reason">{sv.reason}</p>
                                <div className="var-meta-row">
                                  <span className="confidence-pill" title="Explicitly labeled as an LLM estimate, not ground truth">
                                    Model Confidence: {Math.round(sv.model_interpretation_confidence * 100)}% (LLM estimate)
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Semantic Steps */}
                        <div className="sub-block">
                          <span className="sub-label">Semantic Step Intent Breakdown:</span>
                          <div className="semantic-steps-list">
                            {semWf.semantic_steps.map((st, idx) => (
                              <div key={st.step_id} className="semantic-step-item">
                                <div className="step-num-badge">{idx + 1}</div>
                                <div className="step-body">
                                  <div className="step-act-row">
                                    <strong className="step-action-name">{st.action}</strong>
                                    <span className="step-app-pill">{st.application}</span>
                                    <code className="dna-ref-key">[{st.source_dna_step_key}]</code>
                                  </div>
                                  <p className="step-desc-text">{st.description}</p>
                                  <div className="step-citation">
                                    <span className="cite-icon">🔗</span>
                                    <span>{st.evidence_reference}</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Optional Steps if present */}
                        {semWf.optional_steps.length > 0 && (
                          <div className="sub-block">
                            <span className="sub-label">Optional Workflow Branches:</span>
                            {semWf.optional_steps.map((opt) => (
                              <div key={opt.step_id} className="semantic-opt-item">
                                <span className="opt-tag">Optional: {opt.application}</span>
                                <p><strong>Condition:</strong> {opt.condition_or_trigger}</p>
                                <p>{opt.description}</p>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Notes */}
                        <div className="sub-block notes-block">
                          <span className="sub-label">Interpretation Notes & Provenance:</span>
                          <p className="notes-text">{semWf.interpretation_notes}</p>
                          <div className="model-credit">Provider: {semWf.model_provider}</div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};
