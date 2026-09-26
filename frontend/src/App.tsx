import React, { useEffect, useState, useCallback } from 'react';
import { ActivityEvent } from './types/event';
import { DiscoveryCandidate } from './types/discovery';
import { WorkflowDNA } from './types/dna';
import { InterpretationResponse } from './types/semantic';
import { EventList } from './components/EventList';
import { DiscoveryView } from './components/DiscoveryView';
import { DNAView } from './components/DNAView';
import { SemanticView } from './components/SemanticView';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export const App: React.FC = () => {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [dnaItems, setDnaItems] = useState<WorkflowDNA[]>([]);
  const [interpretations, setInterpretations] = useState<Record<string, InterpretationResponse>>({});
  const [isEventsLoading, setIsEventsLoading] = useState<boolean>(false);
  const [isDiscoveryLoading, setIsDiscoveryLoading] = useState<boolean>(false);
  const [isDnaLoading, setIsDnaLoading] = useState<boolean>(false);
  const [interpretingDnaId, setInterpretingDnaId] = useState<string | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [dnaError, setDnaError] = useState<string | null>(null);

  const fetchEvents = useCallback(async () => {
    setIsEventsLoading(true);
    setEventsError(null);
    try {
      const response = await fetch(`${API_BASE}/api/events?limit=100`);
      if (!response.ok) {
        throw new Error(`Failed to fetch events: HTTP ${response.status}`);
      }
      const data: ActivityEvent[] = await response.json();
      setEvents(data);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setEventsError(err.message);
      } else {
        setEventsError('An unexpected error occurred while fetching events');
      }
    } finally {
      setIsEventsLoading(false);
    }
  }, []);

  const fetchDiscoveryCandidates = useCallback(async () => {
    setIsDiscoveryLoading(true);
    setDiscoveryError(null);
    try {
      const response = await fetch(`${API_BASE}/api/discovery/candidates?limit=500&inactivity_timeout=120&min_occurrences=2`);
      if (!response.ok) {
        throw new Error(`Failed to fetch discovery candidates: HTTP ${response.status}`);
      }
      const data = await response.json();
      setCandidates(data.candidates || []);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setDiscoveryError(err.message);
      } else {
        setDiscoveryError('An unexpected error occurred while running discovery');
      }
    } finally {
      setIsDiscoveryLoading(false);
    }
  }, []);

  const fetchWorkflowDNA = useCallback(async () => {
    setIsDnaLoading(true);
    setDnaError(null);
    try {
      const response = await fetch(`${API_BASE}/api/workflows/dna?limit=500&inactivity_timeout=120&min_occurrences=2&similarity_threshold=0.65`);
      if (!response.ok) {
        throw new Error(`Failed to fetch Workflow DNA: HTTP ${response.status}`);
      }
      const data = await response.json();
      setDnaItems(data.dna_items || []);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setDnaError(err.message);
      } else {
        setDnaError('An unexpected error occurred while extracting Workflow DNA');
      }
    } finally {
      setIsDnaLoading(false);
    }
  }, []);

  const handleInterpret = useCallback(async (dnaId: string, providerType?: string) => {
    setInterpretingDnaId(dnaId);
    try {
      const params = new URLSearchParams({
        similarity_threshold: '0.65',
        min_occurrences: '2',
        inactivity_timeout: '120.0',
        force_refresh: 'true',
      });
      if (providerType) {
        params.append('provider_type', providerType);
      }
      const response = await fetch(`${API_BASE}/api/workflows/${dnaId}/interpret?${params.toString()}`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(`Interpretation request failed: HTTP ${response.status}`);
      }
      const data: InterpretationResponse = await response.json();
      setInterpretations((prev) => ({
        ...prev,
        [dnaId]: data,
      }));
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Unknown interpretation error';
      setInterpretations((prev) => ({
        ...prev,
        [dnaId]: {
          status: 'error',
          semantic_workflow: null,
          source_dna: dnaItems.find((d) => d.dna_id === dnaId)!,
          message: errMsg,
          validation_passed: false,
          validation_errors: [errMsg],
        },
      }));
    } finally {
      setInterpretingDnaId(null);
    }
  }, [dnaItems]);

  const refreshAll = useCallback(() => {
    fetchEvents();
    fetchDiscoveryCandidates();
    fetchWorkflowDNA();
  }, [fetchEvents, fetchDiscoveryCandidates, fetchWorkflowDNA]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  return (
    <div className="app-container">
      <header className="navbar">
        <div className="nav-brand">
          <div className="brand-icon">W</div>
          <span className="brand-title">WorkFlowOS</span>
        </div>
        <div className="nav-phase-badge">Phase 5: Semantic Understanding</div>
      </header>

      <main className="main-content">
        <section className="hero-section">
          <div className="hero-subtitle">Desktop Automation Intelligence</div>
          <h1 className="hero-title">
            WorkFlowOS<br />
            AI-Powered Workflow Automation
          </h1>
          <p className="hero-description">
            Observes routine desktop tasks, identifies repetitive patterns, understands user intent,
            and converts actions into automatable workflows.
          </p>
        </section>

        <section className="status-grid">
          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Discovery Engine</h2>
              <div className="indicator" title="Pattern Discovery Ready"></div>
            </div>
            <p className="card-text">
              Noise-tolerant sequence clustering and normalized signature matching across sessions.
            </p>
            <div className="card-meta">Phase 3: Repeated Sequence Discovery</div>
          </div>

          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Workflow DNA</h2>
              <div className="indicator" title="Workflow DNA Active"></div>
            </div>
            <p className="card-text">
              Deterministic extraction of invariant steps, variable parameters, optional steps, and precedence.
            </p>
            <div className="card-meta">Phase 4: Invariants, Variables & Evidence</div>
          </div>

          <div className="status-card">
            <div className="card-header">
              <h2 className="card-title">Semantic Understanding</h2>
              <div className="indicator" title="Semantic Intent Active"></div>
            </div>
            <p className="card-text">
              Evidence-grounded LLM translation of structural DNA into validated semantic workflow intent.
            </p>
            <div className="card-meta">Phase 5: AI Intent Translation</div>
          </div>
        </section>

        {/* Phase 5 Semantic Understanding & Intent Translation View */}
        <SemanticView
          dnaItems={dnaItems}
          interpretations={interpretations}
          isLoading={interpretingDnaId !== null}
          interpretingDnaId={interpretingDnaId}
          onInterpret={handleInterpret}
        />

        {/* Phase 4 Workflow DNA View */}
        <DNAView
          dnaItems={dnaItems}
          isLoading={isDnaLoading}
          error={dnaError}
          onRefresh={fetchWorkflowDNA}
        />

        {/* Phase 3 Discovered Workflow Candidates View */}
        <DiscoveryView
          candidates={candidates}
          isLoading={isDiscoveryLoading}
          error={discoveryError}
          onRefresh={fetchDiscoveryCandidates}
        />

        {/* Live Event Stream View */}
        <EventList
          events={events}
          isLoading={isEventsLoading}
          error={eventsError}
          onRefresh={fetchEvents}
        />
      </main>

      <footer className="footer">
        WorkFlowOS &mdash; Phase 5 AI Semantic Understanding & Intent Translation
      </footer>
    </div>
  );
};

export default App;
