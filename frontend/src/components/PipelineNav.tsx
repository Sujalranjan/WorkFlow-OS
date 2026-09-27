import React from 'react';

export type PipelineStageId =
  | 'observe'
  | 'discover'
  | 'understand'
  | 'approve'
  | 'dry_run'
  | 'execute'
  | 'verify'
  | 'learn';

export type StageState = 'completed' | 'current' | 'pending' | 'blocked';

export interface StageInfo {
  id: PipelineStageId;
  number: number;
  label: string;
  subtitle: string;
  state: StageState;
  stateDetail?: string;
  badge?: string;
}

interface PipelineNavProps {
  stages: StageInfo[];
  activeStage: PipelineStageId;
  onSelectStage: (stageId: PipelineStageId) => void;
}

export const PipelineNav: React.FC<PipelineNavProps> = ({
  stages,
  activeStage,
  onSelectStage,
}) => {
  return (
    <nav className="pipeline-nav-container" aria-label="Workflow Pipeline Progression">
      <div className="pipeline-nav-track">
        {stages.map((stage, idx) => {
          const isSelected = activeStage === stage.id;
          const isCompleted = stage.state === 'completed';
          const isBlocked = stage.state === 'blocked';
          const isCurrent = stage.state === 'current';

          return (
            <React.Fragment key={stage.id}>
              <button
                type="button"
                onClick={() => onSelectStage(stage.id)}
                className={`pipeline-stage-btn ${isSelected ? 'active' : ''} ${stage.state}`}
                title={`Stage ${stage.number}: ${stage.label} — ${stage.stateDetail || stage.state}`}
              >
                <div className="stage-indicator-wrapper">
                  <div className={`stage-badge-circle ${stage.state}`}>
                    {isCompleted ? (
                      <span className="stage-check-icon">✓</span>
                    ) : isBlocked ? (
                      <span className="stage-blocked-icon">✕</span>
                    ) : (
                      <span className="stage-number">{stage.number}</span>
                    )}
                  </div>
                  {isCurrent && <span className="stage-pulse-ring" />}
                </div>

                <div className="stage-content">
                  <div className="stage-label-row">
                    <span className="stage-label">{stage.label}</span>
                    {stage.badge && (
                      <span className="stage-mini-badge">{stage.badge}</span>
                    )}
                  </div>
                  <span className="stage-subtitle">
                    {stage.stateDetail || stage.subtitle}
                  </span>
                </div>
              </button>

              {idx < stages.length - 1 && (
                <div
                  className={`pipeline-divider ${
                    isCompleted && stages[idx + 1].state !== 'pending' ? 'completed' : ''
                  }`}
                  aria-hidden="true"
                >
                  <span className="divider-arrow">→</span>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </nav>
  );
};
