import React, { useState } from 'react';

interface DemoHeaderProps {
  eventCount: number;
  approvedSpecCount: number;
  simulatedPlanCount: number;
  verifiedExecutionCount: number;
  onRefreshAll: () => void;
  isLoading: boolean;
  isGuidedDemoOpen?: boolean;
  onToggleGuidedDemo?: () => void;
  onResetDemo?: () => void;
  isResetting?: boolean;
}

export const DemoHeader: React.FC<DemoHeaderProps> = ({
  eventCount,
  approvedSpecCount,
  simulatedPlanCount,
  verifiedExecutionCount,
  onRefreshAll,
  isLoading,
  isGuidedDemoOpen = false,
  onToggleGuidedDemo,
  onResetDemo,
  isResetting = false,
}) => {
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);

  const handleConfirmReset = () => {
    setShowResetConfirm(false);
    if (onResetDemo) {
      onResetDemo();
    }
  };

  return (
    <header className="demo-header-container">
      <div className="demo-header-top">
        <div className="demo-brand-col">
          <div className="demo-brand-badge">
            <span className="demo-brand-dot" />
            <span className="demo-brand-phase">Phase 15 — Submission Packaging &amp; Demo Polish</span>
          </div>
          <h1 className="demo-title">WorkFlowOS</h1>
          <p className="demo-tagline">
            Observe repetitive work <span className="tagline-arrow">→</span> understand the workflow{' '}
            <span className="tagline-arrow">→</span> approve automation{' '}
            <span className="tagline-arrow">→</span> execute safely{' '}
            <span className="tagline-arrow">→</span> verify <span className="tagline-arrow">→</span> learn
          </p>
        </div>

        <div className="demo-actions-col">
          <button
            type="button"
            className={`demo-guided-toggle-btn ${isGuidedDemoOpen ? 'active' : ''}`}
            onClick={onToggleGuidedDemo}
            title="Toggle Guided Hackathon Demonstration Mode"
          >
            <span className="guided-btn-icon">🧭</span>
            <span>{isGuidedDemoOpen ? 'Guided Demo: ON' : 'Start Guided Demo'}</span>
          </button>

          <button
            type="button"
            className="demo-refresh-btn"
            onClick={onRefreshAll}
            disabled={isLoading || isResetting}
            title="Refresh all pipeline data from backend"
          >
            <span className={`refresh-icon ${isLoading ? 'spinning' : ''}`}>↻</span>
            <span>{isLoading ? 'Syncing...' : 'Refresh Pipeline'}</span>
          </button>

          {onResetDemo && (
            <button
              type="button"
              className="demo-reset-btn"
              onClick={() => setShowResetConfirm(true)}
              disabled={isResetting || isLoading}
              title="Safely reset application demonstration state"
            >
              <span className="reset-btn-icon">🗑️</span>
              <span>{isResetting ? 'Resetting...' : 'Reset Demo State'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Demo Reset Confirmation Modal */}
      {showResetConfirm && (
        <div className="demo-confirm-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div className="demo-confirm-modal">
            <div className="demo-confirm-title">
              <span className="confirm-icon">⚠️</span>
              <h3 id="modal-title">Reset Demonstration State</h3>
            </div>
            <p className="demo-confirm-text">
              Reset demonstration state? This clears workflow/demo records but does not affect Gmail credentials or application configuration.
            </p>
            <div className="demo-confirm-actions">
              <button
                type="button"
                className="btn-modal-cancel"
                onClick={() => setShowResetConfirm(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-modal-reset"
                onClick={handleConfirmReset}
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Capability Transparency Banner */}
      <div className="capability-transparency-card">
        <div className="capability-header">
          <div className="capability-title-group">
            <span className="capability-shield-icon">🛡️</span>
            <span className="capability-heading">System Capability & Safety Transparency</span>
          </div>
          <span className="capability-audit-tag">Audited & Verified</span>
        </div>

        <div className="capability-grid">
          <div className="capability-column">
            <div className="capability-col-title verified-title">
              <span className="col-status-indicator active" />
              <span>Implemented Execution Engines</span>
            </div>
            <ul className="capability-list">
              <li>
                <strong>Controlled Local Sandbox:</strong> Allowlisted filesystem operations strictly isolated inside a safe local sandbox.
              </li>
              <li>
                <strong>Gmail API (Read-Only Search):</strong> Official Google OAuth 2.0 query execution under locked <code>gmail.readonly</code> scope.
              </li>
            </ul>
          </div>

          <div className="capability-column">
            <div className="capability-col-title safety-title">
              <span className="col-status-indicator locked" />
              <span>Enforced Safety Boundaries</span>
            </div>
            <ul className="capability-list muted">
              <li>
                <strong>Human-in-the-Loop Gate:</strong> Unapproved workflows cannot generate execution plans or execute actions.
              </li>
              <li>
                <strong>Zero External Mutations:</strong> No email sending, deleting, or modifications; no browser/OS input automation; no Slack/CRM.
              </li>
            </ul>
          </div>

          <div className="capability-column stats-column">
            <div className="capability-col-title stats-title">
              <span className="col-status-indicator live" />
              <span>Live Pipeline State</span>
            </div>
            <div className="capability-stats-row">
              <div className="stat-pill">
                <span className="stat-val">{eventCount}</span>
                <span className="stat-lbl">Events</span>
              </div>
              <div className="stat-pill">
                <span className="stat-val">{approvedSpecCount}</span>
                <span className="stat-lbl">Approved</span>
              </div>
              <div className="stat-pill">
                <span className="stat-val">{simulatedPlanCount}</span>
                <span className="stat-lbl">Simulated</span>
              </div>
              <div className="stat-pill">
                <span className="stat-val">{verifiedExecutionCount}</span>
                <span className="stat-lbl">Verified</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
