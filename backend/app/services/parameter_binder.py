"""Parameter Binding Service (Phase 6).

Responsible for:
1. Deterministically binding structural WorkflowDNA variable parameters to
   evidence-grounded semantic names proposed by SemanticWorkflow.
2. Inferring variable types using only deterministic metadata rules (NO LLM).
3. Preserving separate parameter bindings for distinct DNA parameters even when
   they share identical semantic names.
4. Enabling user customization of semantic names while guaranteeing that
   the underlying DNA source parameter remains immutable.
"""

import os
import re
from typing import Dict, List, Optional
from app.models.canonical import ParameterBinding, VariableType
from app.models.dna import VariableParameter, WorkflowDNA
from app.models.semantic import SemanticVariable, SemanticWorkflow

KNOWN_FILE_EXTENSIONS = {
    ".pdf", ".csv", ".xlsx", ".xls", ".doc", ".docx", ".txt",
    ".json", ".xml", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg"
}

KNOWN_APPLICATIONS = {
    "gmail", "slack", "crm", "salesforce", "hubspot", "chrome",
    "excel", "outlook", "teams", "whatsapp", "file system", "spotify"
}


class ParameterBinder:
    """Manages parameter binding and deterministic type inference."""

    @staticmethod
    def infer_type(
        source_field: str,
        observed_values: List[str],
        pattern_template: Optional[str] = None,
    ) -> VariableType:
        """Infer variable type deterministically from metadata field and observed values.

        Strictly deterministic. Returns VariableType.UNKNOWN if evidence is insufficient.
        """
        field_lower = source_field.lower()

        # 1. Filename inference
        if "file_name" in field_lower or "filename" in field_lower or "path" in field_lower:
            return VariableType.FILENAME

        if any(
            any(str(val).lower().endswith(ext) for ext in KNOWN_FILE_EXTENSIONS)
            for val in observed_values
        ):
            return VariableType.FILENAME

        if pattern_template and any(pattern_template.lower().endswith(ext) for ext in KNOWN_FILE_EXTENSIONS):
            return VariableType.FILENAME

        # 2. Timestamp inference
        if "timestamp" in field_lower or "date" in field_lower or "time" in field_lower:
            return VariableType.TIMESTAMP

        # Check ISO timestamp format: e.g. 2026-09-26T...
        iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
        if observed_values and all(isinstance(v, str) and iso_pattern.match(v.strip()) for v in observed_values):
            return VariableType.TIMESTAMP

        # 3. Application name inference
        if "application" in field_lower or "app_name" in field_lower:
            return VariableType.APPLICATION
        if observed_values and all(str(v).lower() in KNOWN_APPLICATIONS for v in observed_values):
            return VariableType.APPLICATION

        # 4. Identifier inference (names, customer IDs, ticket numbers, window title entities)
        if "window_title" in field_lower or "title" in field_lower:
            # Window titles with template prefix (e.g. 'CRM - Customer {var}' or '{var} - Replacement Request')
            return VariableType.IDENTIFIER

        if "id" in field_lower or "uuid" in field_lower or "ticket" in field_lower:
            return VariableType.IDENTIFIER

        # 5. String fallback if values exist and are non-empty text
        if observed_values and all(isinstance(v, str) and len(v.strip()) > 0 for v in observed_values):
            return VariableType.STRING

        return VariableType.UNKNOWN

    def bind_parameters(
        self,
        dna: WorkflowDNA,
        semantic_wf: SemanticWorkflow,
    ) -> List[ParameterBinding]:
        """Create explicit parameter bindings from DNA and SemanticWorkflow.

        CRITICAL REQUIREMENT:
        Do NOT merge different DNA variables merely because Gemini gave them the same semantic name.
        Each structural parameter in WorkflowDNA remains independently traceable.
        """
        # Map semantic variables by their source_parameter identifier
        semantic_var_map: Dict[str, SemanticVariable] = {
            sv.source_parameter: sv for sv in semantic_wf.semantic_variables
        }

        bindings: List[ParameterBinding] = []

        for dna_var in dna.variable_parameters:
            sem_var = semantic_var_map.get(dna_var.parameter_name)

            # Fallback semantic name if not mapped by LLM
            semantic_name = sem_var.semantic_name if sem_var else dna_var.parameter_name
            confidence = sem_var.model_interpretation_confidence if sem_var else 0.50

            inferred_type = self.infer_type(
                source_field=dna_var.source_field,
                observed_values=dna_var.observed_values,
                pattern_template=dna_var.pattern_template,
            )

            binding = ParameterBinding(
                source_parameter=dna_var.parameter_name,
                semantic_name=semantic_name,
                source_field=dna_var.source_field,
                associated_step_key=dna_var.associated_step_key,
                associated_application=dna_var.associated_application,
                observed_values=list(dna_var.observed_values),
                inferred_type=inferred_type,
                binding_status="bound",
                user_override=False,
                confidence=confidence,
            )
            bindings.append(binding)

        return bindings

    def update_binding_name(
        self,
        bindings: List[ParameterBinding],
        source_parameter: str,
        new_semantic_name: str,
    ) -> List[ParameterBinding]:
        """Update the human-readable semantic name for a parameter binding.

        Enforces:
        - The source_parameter remains completely unchanged.
        - Raises ValueError if source_parameter does not exist.
        - Sets user_override to True and status to 'user_modified'.
        """
        cleaned_name = new_semantic_name.strip()
        if not cleaned_name:
            raise ValueError("Semantic name cannot be empty.")

        updated = False
        new_bindings: List[ParameterBinding] = []

        for b in bindings:
            if b.source_parameter == source_parameter:
                new_bindings.append(
                    b.model_copy(
                        update={
                            "semantic_name": cleaned_name,
                            "user_override": True,
                            "binding_status": "user_modified",
                        }
                    )
                )
                updated = True
            else:
                new_bindings.append(b)

        if not updated:
            raise ValueError(f"Source parameter '{source_parameter}' not found in parameter bindings.")

        return new_bindings
