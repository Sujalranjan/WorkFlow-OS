"""Deterministic Semantic Validation Layer (Phase 5).

Validates that LLM-generated SemanticWorkflow strictly adheres to the empirical
facts established by the underlying WorkflowDNA. Rejects hallucinations, invented
steps/actions, unknown variables, application mismatches, and ordering contradictions.
"""

from typing import Any, Dict, List, Set, Tuple
from app.models.dna import WorkflowDNA


class SemanticWorkflowValidator:
    """Enforces deterministic ground truth constraints on LLM semantic interpretations."""

    @staticmethod
    def validate(semantic_payload: Dict[str, Any], source_dna: WorkflowDNA) -> Tuple[bool, List[str]]:
        """Validate raw or parsed dictionary against source WorkflowDNA.

        Returns (is_valid, errors).
        """
        errors: List[str] = []

        # 1. Collect DNA ground truth sets
        invariant_step_map = {step.step_key: step for step in source_dna.invariant_steps}
        optional_step_map = {step.step_key: step for step in source_dna.optional_steps}
        all_dna_step_keys = set(invariant_step_map.keys()) | set(optional_step_map.keys())
        dna_apps: Set[str] = {step.application.lower() for step in source_dna.invariant_steps} | {
            step.application.lower() for step in source_dna.optional_steps
        }
        dna_var_names = {var.parameter_name for var in source_dna.variable_parameters}

        # 2. Validate Semantic Steps
        semantic_steps = semantic_payload.get("semantic_steps", [])
        if not isinstance(semantic_steps, list) or not semantic_steps:
            errors.append("Validation Error: 'semantic_steps' must be a non-empty list.")
        else:
            observed_sem_step_keys: List[str] = []
            for idx, step in enumerate(semantic_steps):
                source_key = step.get("source_dna_step_key")
                app_name = step.get("application")

                # Rule 1: Step validity - must reference an existing DNA step key
                if not source_key or source_key not in all_dna_step_keys:
                    errors.append(
                        f"Validation Error in step #{idx + 1}: Referenced source DNA step key "
                        f"'{source_key}' does not exist in WorkflowDNA. Invented steps are strictly rejected."
                    )
                    continue

                observed_sem_step_keys.append(source_key)

                # Rule 2: Application validity - application must match the underlying DNA step
                expected_dna_step = invariant_step_map.get(source_key) or optional_step_map.get(source_key)
                if expected_dna_step and app_name:
                    if app_name.strip().lower() != expected_dna_step.application.strip().lower():
                        errors.append(
                            f"Validation Error in step #{idx + 1}: Application mismatch. Semantic step claims "
                            f"'{app_name}', but DNA step '{source_key}' belongs to '{expected_dna_step.application}'."
                        )

                # Rule 3: Application existence in DNA
                if app_name and app_name.strip().lower() not in dna_apps:
                    errors.append(
                        f"Validation Error in step #{idx + 1}: Application '{app_name}' does not exist in source DNA."
                    )

            # Rule 4: Ordering validity - semantic step order must not contradict DNA ordering constraints
            # Check all ordering constraints where both predecessor and successor appear in semantic steps
            for constraint in source_dna.ordering_constraints:
                pred = constraint.predecessor
                succ = constraint.successor
                if pred in observed_sem_step_keys and succ in observed_sem_step_keys:
                    pred_idx = observed_sem_step_keys.index(pred)
                    succ_idx = observed_sem_step_keys.index(succ)
                    if pred_idx > succ_idx:
                        errors.append(
                            f"Validation Error: Ordering contradiction. DNA constraint requires '{pred}' "
                            f"to precede '{succ}', but semantic sequence placed '{pred}' at index {pred_idx} "
                            f"after '{succ}' at index {succ_idx}."
                        )

        # 3. Validate Semantic Variables
        semantic_variables = semantic_payload.get("semantic_variables", [])
        if isinstance(semantic_variables, list):
            for idx, var in enumerate(semantic_variables):
                source_param = var.get("source_parameter")
                # Rule 5: Variable validity - must reference an existing DNA parameter
                if not source_param or source_param not in dna_var_names:
                    errors.append(
                        f"Validation Error in variable #{idx + 1}: Source parameter '{source_param}' "
                        f"does not exist in WorkflowDNA variable parameters. Invented variables are strictly rejected."
                    )

        # 4. Validate Optional Steps
        optional_steps = semantic_payload.get("optional_steps", [])
        if isinstance(optional_steps, list):
            for idx, opt_step in enumerate(optional_steps):
                source_key = opt_step.get("source_dna_step_key")
                # Rule 6: Optional step validity - must correspond to an actual DNA optional step
                if not source_key or source_key not in optional_step_map:
                    errors.append(
                        f"Validation Error in optional step #{idx + 1}: '{source_key}' is not an optional "
                        f"step in WorkflowDNA."
                    )

        # 5. Validate Required High-Level Fields
        for req_field in ["title", "intent", "summary", "interpretation_notes"]:
            val = semantic_payload.get(req_field)
            if not val or not isinstance(val, str) or not val.strip():
                errors.append(f"Validation Error: High-level semantic field '{req_field}' must be a non-empty string.")

        is_valid = len(errors) == 0
        return is_valid, errors
