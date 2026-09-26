"""Deterministic Workflow DNA Extractor (Phase 4).

Transforms repeated DiscoveryCandidate patterns and their supporting TaskSessions
into explainable WorkflowDNA:
1. Invariants: Steps appearing in 100% of supporting sessions.
2. Optional Steps: Steps appearing in a minority subset of supporting sessions.
3. Variable Parameters: Dynamic fields (window titles, filenames, URLs) that change across executions.
4. Ordering Constraints: Pairwise before/after precedence rules consistently maintained.
5. Structural Preconditions: Required initiating and prerequisite step boundaries.
6. Boundaries: First/last steps and timing envelope.
7. Explainable Evidence: Measurable statistical provenance.
"""

from collections import defaultdict
import difflib
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.models.discovery import DiscoveryCandidate, TaskSession
from app.models.dna import (
    DNAEvidence,
    InvariantStep,
    OptionalStep,
    OrderingConstraint,
    VariableParameter,
    WorkflowBoundaries,
    WorkflowDNA,
)
from app.models.event import ActivityEvent


class WorkflowDNAExtractor:
    """Extracts deterministic WorkflowDNA from a DiscoveryCandidate and supporting TaskSessions."""

    def __init__(self, invariant_threshold: float = 1.0) -> None:
        self.invariant_threshold = invariant_threshold

    @staticmethod
    def _normalize_app_name(app_name: Optional[str]) -> str:
        if not app_name:
            return "unknown_app"
        return app_name.strip().lower()

    @classmethod
    def _get_step_key(cls, event: ActivityEvent) -> str:
        norm_app = cls._normalize_app_name(event.application)
        return f"{norm_app}:{event.event_type.value}"

    def extract_dna(
        self, candidate: DiscoveryCandidate, supporting_sessions: List[TaskSession]
    ) -> WorkflowDNA:
        """Extract Workflow DNA deterministically from a candidate and its supporting sessions."""
        total_sessions = len(supporting_sessions)
        if total_sessions == 0:
            raise ValueError("Cannot extract Workflow DNA without supporting sessions.")

        # 1. Extract Invariant and Optional Steps
        invariants, optionals = self._extract_step_classifications(candidate, supporting_sessions)

        # 2. Extract Variable Parameters
        variables = self._extract_variables(supporting_sessions, invariants)

        # 3. Extract Ordering Constraints & Preconditions
        ordering, preconditions = self._extract_ordering_and_preconditions(supporting_sessions, invariants)

        # 4. Extract Boundaries
        boundaries = self._extract_boundaries(supporting_sessions, invariants)

        # 5. Build Explainable Evidence
        evidence = self._build_evidence(
            total_sessions=total_sessions,
            invariants=invariants,
            optionals=optionals,
            variables=variables,
            ordering=ordering,
            boundaries=boundaries,
        )

        stats = {
            "total_supporting_sessions": total_sessions,
            "invariant_count": len(invariants),
            "optional_count": len(optionals),
            "variable_count": len(variables),
            "ordering_constraint_count": len(ordering),
            "average_similarity_score": candidate.average_similarity_score,
        }

        # Deterministic DNA ID based on candidate ID to preserve idempotency
        dna_id = f"dna-{candidate.candidate_id}"

        return WorkflowDNA(
            dna_id=dna_id,
            source_candidate_id=candidate.candidate_id,
            normalized_signature=candidate.normalized_signature,
            version="1.0.0",
            invariant_steps=invariants,
            variable_parameters=variables,
            optional_steps=optionals,
            ordering_constraints=ordering,
            preconditions=preconditions,
            boundaries=boundaries,
            evidence=evidence,
            statistics=stats,
        )

    def _extract_step_classifications(
        self, candidate: DiscoveryCandidate, sessions: List[TaskSession]
    ) -> Tuple[List[InvariantStep], List[OptionalStep]]:
        """Identify which steps occur across all sessions (invariants) vs subsets (optionals)."""
        total_sessions = len(sessions)

        # Map each step_key to the list of session_ids where it was observed
        step_session_map: Dict[str, Set[str]] = defaultdict(set)
        step_meta_map: Dict[str, Tuple[str, str]] = {}

        for sess in sessions:
            seen_in_this_session: Set[str] = set()
            for evt in sess.events:
                key = self._get_step_key(evt)
                seen_in_this_session.add(key)
                if key not in step_meta_map:
                    step_meta_map[key] = (evt.application or "Unknown", evt.event_type.value)

            for key in seen_in_this_session:
                step_session_map[key].add(sess.session_id)

        invariants: List[InvariantStep] = []
        optionals: List[OptionalStep] = []

        # Order steps according to the representative sequence if present
        rep_keys = [step.action_key for step in candidate.representative_sequence]
        all_observed_keys = list(step_session_map.keys())
        # Sort so representative steps come first in their representative order, followed by other observed keys
        ordered_keys = sorted(
            all_observed_keys,
            key=lambda k: (rep_keys.index(k) if k in rep_keys else 9999, k),
        )

        for key in ordered_keys:
            supporting_ids = sorted(list(step_session_map[key]))
            occurrences = len(supporting_ids)
            ratio = occurrences / total_sessions
            app, event_type = step_meta_map[key]

            if ratio >= self.invariant_threshold:
                invariants.append(
                    InvariantStep(
                        step_key=key,
                        application=app,
                        event_type=event_type,
                        occurrences=occurrences,
                        total_sessions=total_sessions,
                        occurrence_ratio=round(ratio, 3),
                        classification="invariant",
                    )
                )
            elif occurrences >= 1:
                optionals.append(
                    OptionalStep(
                        step_key=key,
                        application=app,
                        event_type=event_type,
                        occurrences=occurrences,
                        total_sessions=total_sessions,
                        occurrence_ratio=round(ratio, 3),
                        supporting_session_ids=supporting_ids,
                        classification="optional",
                    )
                )

        return invariants, optionals

    def _extract_variables(
        self, sessions: List[TaskSession], invariants: List[InvariantStep]
    ) -> List[VariableParameter]:
        """Analyze metadata values across supporting sessions to identify variable parameters."""
        invariant_keys = {inv.step_key for inv in invariants}
        total_sessions = len(sessions)

        # Collect metadata observations grouped by (step_key, field_name)
        # key: (step_key, field_name) -> list of observed string values
        observations: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        step_app_map: Dict[str, str] = {}

        for sess in sessions:
            for evt in sess.events:
                key = self._get_step_key(evt)
                if key not in invariant_keys:
                    continue

                step_app_map[key] = evt.application or "Unknown"

                # Check window_title in metadata
                title = evt.metadata.get("window_title") or evt.metadata.get("title")
                if title and isinstance(title, str) and title.strip():
                    observations[(key, "window_title")].append(title.strip())

                # Check file_name in metadata
                filename = evt.metadata.get("file_name") or evt.metadata.get("file")
                if filename and isinstance(filename, str) and filename.strip():
                    observations[(key, "file_name")].append(filename.strip())

                # Check url / tab_url in metadata
                url = evt.metadata.get("url") or evt.metadata.get("tab_url")
                if url and isinstance(url, str) and url.strip():
                    observations[(key, "url")].append(url.strip())

        variables: List[VariableParameter] = []
        var_counter = 1

        for (step_key, field_name), values in sorted(observations.items()):
            distinct_values = sorted(list(set(values)))
            total_obs = len(values)

            # A field is variable if more than 1 distinct value is observed across executions
            if len(distinct_values) > 1:
                variation_ratio = round(len(distinct_values) / total_obs, 3)
                pattern = self._derive_pattern_template(distinct_values, field_name)

                param_name = f"{field_name}_variable_{var_counter}"
                var_counter += 1

                variables.append(
                    VariableParameter(
                        parameter_name=param_name,
                        source_field=f"metadata.{field_name}",
                        associated_step_key=step_key,
                        associated_application=step_app_map.get(step_key, "Unknown"),
                        observed_values=distinct_values,
                        distinct_value_count=len(distinct_values),
                        total_observations=total_obs,
                        variation_ratio=variation_ratio,
                        pattern_template=pattern,
                    )
                )

        return variables

    @staticmethod
    def _derive_pattern_template(values: List[str], field_name: str) -> Optional[str]:
        """Derive a structural template for filenames or titles (e.g. 'invoice_{variable}.pdf')."""
        if len(values) < 2:
            return None

        if field_name == "file_name":
            # Check extension consistency
            exts = {os.path.splitext(v)[1] for v in values if os.path.splitext(v)[1]}
            if len(exts) == 1:
                common_ext = list(exts)[0]
                # Check common prefix
                basenames = [os.path.splitext(v)[0] for v in values]
                common_prefix = os.path.commonprefix(basenames)

                # If common_prefix ends with digits (e.g. 'invoice_10' when basenames are 'invoice_101', 'invoice_102'),
                # strip trailing digits so that whole tokens like '101', '102' are captured as {variable}
                if common_prefix and common_prefix[-1].isdigit():
                    idx = len(common_prefix) - 1
                    while idx >= 0 and common_prefix[idx].isdigit():
                        idx -= 1
                    if idx >= 0 and common_prefix[idx] in ("_", "-", " ", "."):
                        common_prefix = common_prefix[: idx + 1]
                    elif idx >= 0:
                        common_prefix = common_prefix[: idx + 1]

                if len(common_prefix) >= 1:
                    return f"{common_prefix}{{variable}}{common_ext}"
                return f"{{variable}}{common_ext}"

        # General prefix/suffix detection for titles
        common_prefix = os.path.commonprefix(values)
        reversed_values = [v[::-1] for v in values]
        common_suffix = os.path.commonprefix(reversed_values)[::-1]

        if len(common_prefix.strip()) >= 3 or len(common_suffix.strip()) >= 3:
            prefix_part = common_prefix if len(common_prefix.strip()) >= 3 else ""
            suffix_part = common_suffix if len(common_suffix.strip()) >= 3 else ""
            return f"{prefix_part}{{variable}}{suffix_part}"

        return None

    def _extract_ordering_and_preconditions(
        self, sessions: List[TaskSession], invariants: List[InvariantStep]
    ) -> Tuple[List[OrderingConstraint], List[str]]:
        """Identify strictly consistent precedence relationships between invariant steps."""
        if len(invariants) < 2:
            return [], []

        invariant_keys = [inv.step_key for inv in invariants]
        total_sessions = len(sessions)

        # For each pair of invariant steps (A, B), count how many sessions have first_index(A) < first_index(B)
        ordering_counts: Dict[Tuple[str, str], int] = defaultdict(int)

        for sess in sessions:
            step_first_index: Dict[str, int] = {}
            for idx, evt in enumerate(sess.events):
                k = self._get_step_key(evt)
                if k in invariant_keys and k not in step_first_index:
                    step_first_index[k] = idx

            for i in range(len(invariant_keys)):
                for j in range(len(invariant_keys)):
                    if i != j:
                        key_a = invariant_keys[i]
                        key_b = invariant_keys[j]
                        if key_a in step_first_index and key_b in step_first_index:
                            if step_first_index[key_a] < step_first_index[key_b]:
                                ordering_counts[(key_a, key_b)] += 1

        constraints: List[OrderingConstraint] = []
        preconditions: List[str] = []

        # Retain adjacent sequential invariant pairs with 100% precedence consistency
        for i in range(len(invariant_keys) - 1):
            step_a = invariant_keys[i]
            step_b = invariant_keys[i + 1]
            count = ordering_counts.get((step_a, step_b), 0)
            consistency = count / total_sessions if total_sessions > 0 else 0.0

            if consistency >= 1.0:
                desc = f"'{step_a}' consistently occurs before '{step_b}'"
                constraints.append(
                    OrderingConstraint(
                        predecessor=step_a,
                        successor=step_b,
                        consistency_ratio=consistency,
                        description=desc,
                    )
                )
                preconditions.append(f"Precondition: '{step_a}' must precede '{step_b}'.")

        # Global entry precondition
        first_inv = invariant_keys[0]
        preconditions.insert(0, f"Workflow execution begins with '{first_inv}'.")

        return constraints, preconditions

    def _extract_boundaries(
        self, sessions: List[TaskSession], invariants: List[InvariantStep]
    ) -> WorkflowBoundaries:
        """Derive timing and boundary parameters from supporting sessions."""
        durations = [s.duration_seconds for s in sessions]
        min_dur = min(durations) if durations else 0.0
        max_dur = max(durations) if durations else 0.0
        avg_dur = sum(durations) / len(durations) if durations else 0.0

        first_step = invariants[0].step_key if invariants else "unknown_start"
        last_step = invariants[-1].step_key if invariants else "unknown_end"

        return WorkflowBoundaries(
            first_step=first_step,
            last_step=last_step,
            min_duration_seconds=round(min_dur, 2),
            max_duration_seconds=round(max_dur, 2),
            average_duration_seconds=round(avg_dur, 2),
            total_supporting_sessions=len(sessions),
        )

    def _build_evidence(
        self,
        total_sessions: int,
        invariants: List[InvariantStep],
        optionals: List[OptionalStep],
        variables: List[VariableParameter],
        ordering: List[OrderingConstraint],
        boundaries: WorkflowBoundaries,
    ) -> DNAEvidence:
        """Compile explainable evidence for all DNA dimensions."""
        inv_str = ", ".join(f"'{i.step_key}' ({i.occurrences}/{total_sessions})" for i in invariants)
        inv_evidence = (
            f"Classified {len(invariants)} steps as invariant because each occurred in "
            f"100% of supporting sessions: {inv_str}."
        )

        if optionals:
            opt_str = ", ".join(f"'{o.step_key}' ({o.occurrences}/{total_sessions})" for o in optionals)
            opt_evidence = (
                f"Identified {len(optionals)} optional steps observed in a minority of executions: {opt_str}."
            )
        else:
            opt_evidence = "No optional steps detected; all supporting sessions adhered strictly to the core sequence."

        if variables:
            var_summaries = []
            for v in variables:
                tpl = f" (pattern: {v.pattern_template})" if v.pattern_template else ""
                var_summaries.append(
                    f"'{v.parameter_name}' from {v.source_field} in '{v.associated_step_key}' "
                    f"with {v.distinct_value_count} distinct values across {v.total_observations} observations{tpl}"
                )
            var_evidence = f"Extracted {len(variables)} dynamic variable candidates: " + "; ".join(var_summaries) + "."
        else:
            var_evidence = "No variable parameter variations detected across supporting metadata."

        ord_evidence = (
            f"Verified {len(ordering)} pairwise ordering constraints with 100% consistency across all {total_sessions} sessions."
        )

        boundary_evidence = (
            f"Workflow initiates at '{boundaries.first_step}' and terminates at '{boundaries.last_step}'. "
            f"Observed session duration ranges from {boundaries.min_duration_seconds}s to {boundaries.max_duration_seconds}s "
            f"(average: {boundaries.average_duration_seconds}s)."
        )

        return DNAEvidence(
            supporting_session_count=total_sessions,
            invariant_evidence=inv_evidence,
            variable_evidence=var_evidence,
            optional_step_evidence=opt_evidence,
            ordering_evidence=ord_evidence,
            boundary_evidence=boundary_evidence,
        )
