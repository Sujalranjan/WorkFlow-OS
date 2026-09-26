"""Semantic Model Provider Abstraction & Implementations (Phase 5).

Provides an abstract interface for LLM semantic interpretation with:
1. SemanticModelProvider (Abstract Base Class)
2. GeminiSemanticProvider (Google Gemini API integration with structured JSON)
3. MockSemanticProvider (Deterministic, fully controllable provider for tests and offline modes)
"""

from abc import ABC, abstractmethod
import json
import logging
import os
from typing import Any, Dict, List, Optional
from app.models.dna import WorkflowDNA

logger = logging.getLogger(__name__)


class ProviderUnavailableError(Exception):
    """Raised when the LLM provider is unavailable (missing credentials, network failure, timeout)."""
    pass


class SemanticModelProvider(ABC):
    """Abstract interface for LLM semantic workflow interpreters."""

    @abstractmethod
    def interpret_workflow_dna(self, dna: WorkflowDNA) -> Dict[str, Any]:
        """Translate structural WorkflowDNA into raw structured semantic dictionary.

        Must raise ProviderUnavailableError if service cannot be reached or credentials missing.
        """
        pass


def build_semantic_interpretation_prompt(dna: WorkflowDNA) -> str:
    """Constructs a strict, structured prompt enclosing only WorkflowDNA ground truth."""
    dna_summary = {
        "dna_id": dna.dna_id,
        "normalized_signature": dna.normalized_signature,
        "invariant_steps": [
            {
                "step_key": inv.step_key,
                "application": inv.application,
                "event_type": inv.event_type,
                "occurrence_ratio": inv.occurrence_ratio,
            }
            for inv in dna.invariant_steps
        ],
        "variable_parameters": [
            {
                "parameter_name": var.parameter_name,
                "source_field": var.source_field,
                "associated_step_key": var.associated_step_key,
                "associated_application": var.associated_application,
                "observed_values": var.observed_values,
                "pattern_template": var.pattern_template,
                "variation_ratio": var.variation_ratio,
            }
            for var in dna.variable_parameters
        ],
        "optional_steps": [
            {
                "step_key": opt.step_key,
                "application": opt.application,
                "event_type": opt.event_type,
                "occurrence_ratio": opt.occurrence_ratio,
            }
            for opt in dna.optional_steps
        ],
        "ordering_constraints": [
            {
                "predecessor": oc.predecessor,
                "successor": oc.successor,
                "consistency_ratio": oc.consistency_ratio,
                "description": oc.description,
            }
            for oc in dna.ordering_constraints
        ],
        "preconditions": dna.preconditions,
        "boundaries": dna.boundaries.model_dump(),
        "evidence": dna.evidence.model_dump(),
    }

    prompt = f"""You are a desktop workflow semantics interpreter in WorkFlowOS.

INPUT DATA (Deterministic WorkflowDNA Ground Truth):
{json.dumps(dna_summary, indent=2)}

TASK:
Translate this structural, deterministic WorkflowDNA into a human-understandable semantic workflow representation.

RULES:
1. Ground Truth Adherence: Use ONLY information contained in the supplied WorkflowDNA.
2. NO Invented Steps: Every item in 'semantic_steps' must have 'source_dna_step_key' matching an existing DNA invariant step.
3. NO Invented Applications: 'application' must exactly match the application in the corresponding DNA step.
4. Ordering Preservation: Do NOT violate ordering constraints. If Step A precedes Step B in DNA, preserve that sequence.
5. Evidence-Grounded Variables: Map each structural parameter (e.g. 'window_title_variable_1') to a semantic name (e.g. 'customer_name') ONLY when observed values and patterns support it. If uncertain, use a generic name like 'record_identifier'.
6. Preserve Structural IDs: In 'semantic_variables', keep 'source_parameter' exactly matching the original parameter name.
7. Optional Steps: Every optional step in 'optional_steps' must map to an observed DNA optional step.
8. NO Automation Code: Do NOT produce executable code, browser automation, click coordinates, or shell scripts.
9. Confidence: Assign 'model_interpretation_confidence' (0.0 to 1.0) explicitly as an LLM estimate.

REQUIRED JSON OUTPUT FORMAT (Strict JSON only, no markdown formatting, no code block fences):
{{
  "title": "<High-level human-readable title>",
  "intent": "<Operational business intent of the routine>",
  "summary": "<Multi-step executive summary>",
  "semantic_steps": [
    {{
      "step_id": "sem-step-1",
      "source_dna_step_key": "<must match an invariant step_key in input>",
      "application": "<must match application in input>",
      "action": "<short semantic action>",
      "description": "<detailed intent description>",
      "input_variables": ["<semantic variable names>"],
      "output_variables": ["<semantic variable names>"],
      "evidence_reference": "<citation of occurrence ratio and DNA evidence>"
    }}
  ],
  "semantic_variables": [
    {{
      "source_parameter": "<must match parameter_name in input>",
      "semantic_name": "<evidence-grounded entity name>",
      "source_field": "<must match source_field in input>",
      "observed_values": ["<copied from input>"],
      "reason": "<grounded explanation why this name was chosen>",
      "model_interpretation_confidence": 0.90
    }}
  ],
  "optional_steps": [
    {{
      "step_id": "sem-opt-1",
      "source_dna_step_key": "<must match an optional step_key in input>",
      "application": "<application name>",
      "condition_or_trigger": "<trigger context>",
      "description": "<optional step description>"
    }}
  ],
  "preconditions": [
    "<precondition 1>",
    "<precondition 2>"
  ],
  "evidence_mapping": {{
    "invariants": "<reference to DNA evidence>",
    "variables": "<reference to DNA evidence>"
  }},
  "interpretation_notes": "<notes regarding confidence, assumptions, or reasoning>"
}}
"""
    return prompt


class GeminiSemanticProvider(SemanticModelProvider):
    """Google Gemini LLM provider for semantic interpretation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-1.5-flash",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self.timeout_seconds = timeout_seconds

    def interpret_workflow_dna(self, dna: WorkflowDNA) -> Dict[str, Any]:
        """Invoke Gemini API to generate structured semantic workflow JSON."""
        if not self.api_key:
            raise ProviderUnavailableError(
                "Gemini API key not configured. Set the GEMINI_API_KEY environment variable."
            )

        prompt = build_semantic_interpretation_prompt(dna)

        # Attempt 1: Using google.generativeai if available
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config={"response_mime_type": "application/json"},
            )
            response = model.generate_content(prompt)
            raw_text = response.text.strip()
            # Strip markdown fences if present
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed = json.loads(raw_text.strip())
            parsed["source_dna_id"] = dna.dna_id
            parsed["boundaries"] = dna.boundaries.model_dump()
            parsed["model_provider"] = f"gemini/{self.model_name}"
            parsed["status"] = "interpreted"
            return parsed
        except ImportError:
            pass
        except Exception as err:
            logger.warning(f"google.generativeai SDK call failed, attempting HTTP fallback: {err}")

        # Attempt 2: Direct REST call via httpx
        try:
            import httpx

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
            with httpx.Client(timeout=self.timeout_seconds) as client:
                res = client.post(url, json=payload)
                if res.status_code != 200:
                    raise ProviderUnavailableError(
                        f"Gemini API returned status {res.status_code}: {res.text[:200]}"
                    )
                data = res.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text_content.strip())
                parsed["source_dna_id"] = dna.dna_id
                parsed["boundaries"] = dna.boundaries.model_dump()
                parsed["model_provider"] = f"gemini/{self.model_name}"
                parsed["status"] = "interpreted"
                return parsed
        except Exception as http_err:
            raise ProviderUnavailableError(
                f"Failed to communicate with Gemini API: {http_err}"
            ) from http_err


class MockSemanticProvider(SemanticModelProvider):
    """Configurable mock provider for deterministic offline testing and fallbacks."""

    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode

    def interpret_workflow_dna(self, dna: WorkflowDNA) -> Dict[str, Any]:
        if self.mode == "unavailable":
            raise ProviderUnavailableError("Simulated LLM service unavailable.")

        if self.mode == "malformed_json":
            return {"corrupted": True}

        # Step generation grounded in DNA invariants
        semantic_steps: List[Dict[str, Any]] = []
        for idx, inv in enumerate(dna.invariant_steps, 1):
            app = inv.application
            if self.mode == "app_mismatch" and idx == 1:
                app = "NonExistentApp"

            step_key = inv.step_key
            if self.mode == "invalid_step" and idx == 1:
                step_key = "non_existent_app:action_fictional"

            # Derive meaningful action description based on application
            action_desc = f"Execute {inv.event_type} in {app}"
            if "gmail" in app.lower():
                action_desc = "Review and open customer replacement request email"
            elif "file" in app.lower():
                action_desc = "Process downloaded invoice document"
            elif "crm" in app.lower():
                action_desc = "Locate customer record and update replacement details"
            elif "slack" in app.lower():
                action_desc = "Notify operations team with status and customer details"

            semantic_steps.append(
                {
                    "step_id": f"sem-step-{idx}",
                    "source_dna_step_key": step_key,
                    "application": app,
                    "action": action_desc,
                    "description": f"Standardized operation in {app} satisfying routine requirement.",
                    "input_variables": ["customer_name"] if idx > 1 else [],
                    "output_variables": ["customer_name"] if idx == 1 else [],
                    "evidence_reference": f"Occurred in {inv.occurrences}/{inv.total_sessions} supporting sessions (100%).",
                }
            )

        if self.mode == "ordering_contradiction" and len(semantic_steps) >= 2:
            # Swap steps 0 and 1 to create an ordering violation
            semantic_steps[0], semantic_steps[1] = semantic_steps[1], semantic_steps[0]

        # Variable generation grounded in DNA variable parameters
        semantic_vars: List[Dict[str, Any]] = []
        for v_idx, var in enumerate(dna.variable_parameters, 1):
            param_name = var.parameter_name
            if self.mode == "invalid_variable" and v_idx == 1:
                param_name = "fictional_unobserved_variable"

            sem_name = "record_identifier"
            reason = "Variable changes between sessions representing an identifier."
            if "title" in var.source_field:
                sem_name = "customer_name"
                reason = "Observed titles consistently feature customer names prefixed before replacement request text."
            elif "file" in var.source_field:
                sem_name = "invoice_document"
                reason = "Observed filenames follow invoice document pattern across executions."

            semantic_vars.append(
                {
                    "source_parameter": param_name,
                    "semantic_name": sem_name,
                    "source_field": var.source_field,
                    "observed_values": var.observed_values,
                    "reason": reason,
                    "model_interpretation_confidence": 0.92,
                }
            )

        # Optional step generation
        optional_steps: List[Dict[str, Any]] = []
        for o_idx, opt in enumerate(dna.optional_steps, 1):
            optional_steps.append(
                {
                    "step_id": f"sem-opt-{o_idx}",
                    "source_dna_step_key": opt.step_key,
                    "application": opt.application,
                    "condition_or_trigger": "Executed when audit logging or secondary reporting is required.",
                    "description": f"Optional supplementary action in {opt.application}.",
                }
            )

        return {
            "source_dna_id": dna.dna_id,
            "title": "Customer Replacement Request Processing",
            "intent": "Receive incoming customer replacement request, process invoice attachment, update CRM customer record, and send team notification.",
            "summary": "End-to-end customer support routine transitioning from Gmail to CRM and Slack with optional auxiliary spreadsheet logging.",
            "semantic_steps": semantic_steps,
            "semantic_variables": semantic_vars,
            "optional_steps": optional_steps,
            "preconditions": [
                "User has customer request email received in Gmail.",
                "CRM application session is accessible.",
            ],
            "boundaries": dna.boundaries.model_dump(),
            "evidence_mapping": {
                "invariants": dna.evidence.invariant_evidence,
                "variables": dna.evidence.variable_evidence,
            },
            "interpretation_notes": "All semantic steps map 100% to observed invariant events in WorkflowDNA. Variable customer_name is inferred with 0.92 confidence based on recurring window title patterns.",
            "model_provider": "mock-semantic-provider",
            "status": "interpreted",
        }
