"""Deterministic Workflow Discovery Engine identifying recurring candidate patterns."""

import hashlib
from collections import defaultdict
from difflib import SequenceMatcher
from typing import List, Optional, Set, Tuple
from app.models.discovery import DiscoveryCandidate, NormalizedStep, TaskSession
from app.models.event import ActivityEvent


class WorkflowDiscoveryEngine:
    """Discovers recurring workflow candidate patterns from segmented TaskSessions.

    Differentiators:
    1. Signature Normalization: Encodes (application, event_type) into a canonical key.
    2. Noise Filtering: Identifies and strips transient/incidental events (e.g. background apps)
       that occur rarely or outside the core pattern.
    3. Sequence Similarity: Deterministic sequence similarity using Python SequenceMatcher ratio to evaluate
       structural alignment rather than strict string equality.
    4. Deterministic Explainability: Records exact occurrence counts, similarity metrics,
       and explainable evidence for each discovered candidate.
    """

    def __init__(
        self,
        min_occurrences: int = 2,
        similarity_threshold: float = 0.70,
        incidental_applications: Optional[Set[str]] = None,
    ) -> None:
        self.min_occurrences = min_occurrences
        self.similarity_threshold = similarity_threshold
        # Applications known to be incidental background interruptions if configured
        self.incidental_applications = {app.lower() for app in (incidental_applications or set())}

    @staticmethod
    def normalize_app_name(app_name: Optional[str]) -> str:
        """Produce a lowercase, normalized application identifier."""
        if not app_name:
            return "unknown_app"
        return app_name.strip().lower()

    def event_to_token(self, event: ActivityEvent) -> str:
        """Convert an ActivityEvent into a normalized step token (e.g. 'google chrome:window_focused')."""
        norm_app = self.normalize_app_name(event.application)
        return f"{norm_app}:{event.event_type.value}"

    def extract_core_sequence(self, session: TaskSession) -> List[Tuple[str, ActivityEvent]]:
        """Extract a filtered sequence of (token, original_event) removing known incidental noise."""
        result: List[Tuple[str, ActivityEvent]] = []
        for evt in session.events:
            app_norm = self.normalize_app_name(evt.application)
            if app_norm in self.incidental_applications:
                continue
            token = self.event_to_token(evt)
            # Suppress consecutive identical tokens inside a single session
            if result and result[-1][0] == token:
                continue
            result.append((token, evt))
        return result

    @staticmethod
    def sequence_similarity(seq_a: List[str], seq_b: List[str]) -> float:
        """Calculate deterministic sequence similarity ratio using SequenceMatcher (0.0 to 1.0)."""
        if not seq_a and not seq_b:
            return 1.0
        if not seq_a or not seq_b:
            return 0.0
        matcher = SequenceMatcher(None, seq_a, seq_b)
        return matcher.ratio()

    def discover_candidates(self, sessions: List[TaskSession]) -> List[DiscoveryCandidate]:
        """Analyze segmented sessions and group similar sequences into DiscoveryCandidates."""
        if len(sessions) < self.min_occurrences:
            return []

        # Prepare tokens for each session
        session_tokens: List[Tuple[TaskSession, List[str], List[ActivityEvent]]] = []
        for sess in sessions:
            core = self.extract_core_sequence(sess)
            if len(core) >= 2:  # Workflows must have at least 2 distinct transitions
                tokens = [t[0] for t in core]
                events = [t[1] for t in core]
                session_tokens.append((sess, tokens, events))

        if not session_tokens:
            return []

        # Cluster sessions by sequence similarity
        # Each cluster: list of (TaskSession, tokens, events, similarity_to_rep)
        clusters: List[List[Tuple[TaskSession, List[str], List[ActivityEvent], float]]] = []

        for sess, tokens, events in session_tokens:
            best_cluster_idx: Optional[int] = None
            best_sim = 0.0

            for idx, cluster in enumerate(clusters):
                rep_tokens = cluster[0][1]
                sim = self.sequence_similarity(tokens, rep_tokens)
                if sim >= self.similarity_threshold and sim > best_sim:
                    best_sim = sim
                    best_cluster_idx = idx

            if best_cluster_idx is not None:
                clusters[best_cluster_idx].append((sess, tokens, events, best_sim))
            else:
                clusters.append([(sess, tokens, events, 1.0)])

        candidates: List[DiscoveryCandidate] = []

        for cluster in clusters:
            if len(cluster) < self.min_occurrences:
                continue

            # Pick representative sequence (the most common or the representative first member)
            rep_sess, rep_tokens, rep_events, _ = cluster[0]

            # Calculate average similarity score across cluster members
            avg_sim = sum(item[3] for item in cluster) / len(cluster)

            # Build canonical signature
            canonical_signature = " -> ".join(rep_tokens)

            # Collect metadata across supporting sessions
            all_sessions = [item[0] for item in cluster]
            supporting_ids = [s.session_id for s in all_sessions]
            first_seen = min(s.start_time for s in all_sessions)
            last_seen = max(s.end_time for s in all_sessions)

            distinct_apps: List[str] = []
            distinct_event_types: List[str] = []

            for s in all_sessions:
                for app in s.applications_involved:
                    if app and app not in distinct_apps:
                        distinct_apps.append(app)
                for evt in s.events:
                    et = evt.event_type.value
                    if et not in distinct_event_types:
                        distinct_event_types.append(et)

            # Build representative sequence steps
            rep_steps: List[NormalizedStep] = []
            for step_idx, (tok, evt) in enumerate(zip(rep_tokens, rep_events)):
                rep_steps.append(
                    NormalizedStep(
                        step_index=step_idx + 1,
                        application=evt.application or "Unknown",
                        event_type=evt.event_type.value,
                        action_key=tok,
                        is_optional=False,
                    )
                )

            evidence_text = (
                f"Discovered across {len(cluster)} sessions with {avg_sim * 100:.1f}% "
                f"average sequence similarity. Consistent transitions: {canonical_signature}."
            )

            cand_hash = hashlib.sha256(canonical_signature.encode("utf-8")).hexdigest()[:12]
            cand_id = f"cand-{cand_hash}"

            candidates.append(
                DiscoveryCandidate(
                    candidate_id=cand_id,
                    normalized_signature=canonical_signature,
                    occurrences=len(cluster),
                    first_seen=first_seen,
                    last_seen=last_seen,
                    applications=distinct_apps,
                    event_types=distinct_event_types,
                    representative_sequence=rep_steps,
                    average_similarity_score=round(avg_sim, 3),
                    supporting_session_ids=supporting_ids,
                    evidence=evidence_text,
                    metadata={
                        "total_supporting_events": sum(s.event_count for s in all_sessions),
                        "cluster_size": len(cluster),
                        "similarity_threshold_used": self.similarity_threshold,
                    },
                )
            )

        # Sort candidates by occurrence count descending, then similarity descending
        candidates.sort(key=lambda c: (c.occurrences, c.average_similarity_score), reverse=True)
        return candidates
