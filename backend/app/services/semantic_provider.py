"""Semantic Model Provider Abstraction & Implementations (Phase 5).

Provides an abstract interface for LLM semantic interpretation with:
1. SemanticModelProvider (Abstract Base Class)
2. GeminiSemanticProvider (Google Gemini API integration with structured JSON)
3. MockSemanticProvider (Deterministic, fully controllable provider for tests)
4. RuleBasedSemanticProvider (Offline default: describes workflows from DNA + ActionCatalog only)
"""

from abc import ABC, abstractmethod
import json
import logging
import os
from typing import Any, Dict, List, Optional
import httpx

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.models.dna import WorkflowDNA
from app.services.action_catalog import get_action

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
                "catalog_action": inv.catalog_action,
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
10. Executable Steps: Every invariant step with a non-null 'catalog_action' MUST appear in 'semantic_steps'. For those steps set 'action' to the part of 'catalog_action' after the dot (e.g. 'gmail.search_email' -> 'search_email'). Steps with a null 'catalog_action' are observational context; describe them but do not invent actions for them.

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
        model_name: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", GEMINI_MODEL)
        self.timeout_seconds = timeout_seconds

    def interpret_workflow_dna(self, dna: WorkflowDNA) -> Dict[str, Any]:
        """Invoke Gemini API to generate structured semantic workflow JSON."""
        if not self.api_key:
            raise ProviderUnavailableError(
                "Gemini API key not configured. Set the GEMINI_API_KEY environment variable."
            )

        prompt = build_semantic_interpretation_prompt(dna)

        # Gemini REST API with JSON output mode. The API key travels in a header, not the URL,
        # so it never appears in logs or exception messages.
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                res = client.post(url, json=payload, headers={"x-goog-api-key": self.api_key})
        except httpx.HTTPError as http_err:
            raise ProviderUnavailableError(f"Failed to reach Gemini API: {type(http_err).__name__}") from http_err

        if res.status_code != 200:
            raise ProviderUnavailableError(
                f"Gemini API returned status {res.status_code} for model '{self.model_name}': {res.text[:200]}"
            )
        try:
            text_content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(_strip_code_fences(text_content))
        except (KeyError, IndexError, TypeError, ValueError) as parse_err:
            raise ProviderUnavailableError(f"Gemini API returned an unparseable response: {parse_err}") from parse_err

        parsed["source_dna_id"] = dna.dna_id
        parsed["boundaries"] = dna.boundaries.model_dump()
        parsed["model_provider"] = f"gemini/{self.model_name}"
        parsed["status"] = "interpreted"
        return parsed


def _strip_code_fences(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


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
            catalog = get_action(inv.catalog_action)
            if catalog:
                action_desc = catalog.action
            elif "gmail" in app.lower():
                action_desc = "Review and open customer replacement request email"
            elif "file" in app.lower():
                if "open" in inv.event_type.lower():
                    action_desc = "read_file"
                elif "create" in inv.event_type.lower():
                    action_desc = "generate_report"
                elif "download" in inv.event_type.lower() or "save" in inv.event_type.lower():
                    action_desc = "save_file"
                else:
                    action_desc = "process_downloaded_file"
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

        is_local_file_wf = all("file" in inv.application.lower() for inv in dna.invariant_steps)
        if is_local_file_wf:
            title = "Local Transaction Reconciliation and Report Generation"
            intent = "Read local transaction files, generate reconciliation reports inside the sandbox, and save archive artifacts."
            summary = "End-to-end deterministic local file processing routine executed strictly within the secure sandbox."
            preconditions = [
                "Local transaction batch files are accessible in file system.",
                "Isolated sandbox storage directory is prepared.",
            ]
        else:
            title = "Customer Replacement Request Processing"
            intent = "Receive incoming customer replacement request, process invoice attachment, update CRM customer record, and send team notification."
            summary = "End-to-end customer support routine transitioning from Gmail to CRM and Slack with optional auxiliary spreadsheet logging."
            preconditions = [
                "User has customer request email received in Gmail.",
                "CRM application session is accessible.",
            ]

        return {
            "source_dna_id": dna.dna_id,
            "title": title,
            "intent": intent,
            "summary": summary,
            "semantic_steps": semantic_steps,
            "semantic_variables": semantic_vars,
            "optional_steps": optional_steps,
            "preconditions": preconditions,
            "boundaries": dna.boundaries.model_dump(),
            "evidence_mapping": {
                "invariants": dna.evidence.invariant_evidence,
                "variables": dna.evidence.variable_evidence,
            },
            "interpretation_notes": "All semantic steps map 100% to observed invariant events in WorkflowDNA. Variable customer_name is inferred with 0.92 confidence based on recurring window title patterns.",
            "model_provider": "mock-semantic-provider",
            "status": "interpreted",
        }


def _humanize(token: str) -> str:
    text = token.replace("_", " ").replace(".", " ").strip()
    return text[:1].upper() + text[1:]


class RuleBasedSemanticProvider(SemanticModelProvider):
    """Offline interpreter used when no LLM is configured.

    Everything it writes is derived from the WorkflowDNA and the ActionCatalog: step wording comes
    from catalog descriptions, names from observed parameters, and the title from the apps involved.
    It never invents business context the observation does not contain.
    """

    def interpret_workflow_dna(self, dna: WorkflowDNA) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        actions = []
        for idx, inv in enumerate(dna.invariant_steps, 1):
            catalog = get_action(inv.catalog_action)
            if catalog:
                action, description = catalog.action, catalog.description
                actions.append(catalog)
            elif "file" in inv.application.lower():
                event = inv.event_type.lower()
                action = (
                    "read_file" if "open" in event
                    else "generate_report" if "create" in event
                    else "save_file" if ("download" in event or "save" in event)
                    else "process_downloaded_file"
                )
                description = f"{_humanize(inv.event_type)} in the local file system."
            else:
                action = inv.event_type
                description = f"{_humanize(inv.event_type)} in {inv.application} (observed context)."
            steps.append(
                {
                    "step_id": f"sem-step-{idx}",
                    "source_dna_step_key": inv.step_key,
                    "application": inv.application,
                    "action": action,
                    "description": description,
                    "input_variables": [],
                    "output_variables": [],
                    "evidence_reference": (
                        f"Occurred in {inv.occurrences}/{inv.total_sessions} supporting sessions "
                        f"({round(inv.occurrence_ratio * 100)}%)."
                    ),
                }
            )

        variables: List[Dict[str, Any]] = []
        for var in dna.variable_parameters:
            field = var.source_field
            if field.startswith("action."):
                name = field.split(".", 1)[1]
            elif "title" in field:
                name = "window_title"
            elif "file" in field:
                name = "file_name"
            else:
                name = var.parameter_name
            variables.append(
                {
                    "source_parameter": var.parameter_name,
                    "semantic_name": name,
                    "source_field": field,
                    "observed_values": var.observed_values,
                    "reason": (
                        f"{var.distinct_value_count} different values across {var.total_observations} "
                        f"observations of {var.associated_application}."
                    ),
                    "model_interpretation_confidence": 1.0,
                }
            )

        optional = [
            {
                "step_id": f"sem-opt-{i}",
                "source_dna_step_key": opt.step_key,
                "application": opt.application,
                "condition_or_trigger": f"Seen in {opt.occurrences} of {opt.total_sessions} sessions.",
                "description": f"{_humanize(opt.event_type)} in {opt.application}, done only sometimes.",
            }
            for i, opt in enumerate(dna.optional_steps, 1)
        ]

        apps: List[str] = []
        for inv in dna.invariant_steps:
            if inv.application not in apps:
                apps.append(inv.application)
        action_apps = [a.application for a in actions]
        title_apps = [a for a in apps if a in action_apps] or apps
        title = f"{' → '.join(title_apps)} routine"
        if actions:
            intent = "; then ".join(a.description[:1].lower() + a.description[1:] for a in actions)
            intent = intent[:1].upper() + intent[1:] + "."
        else:
            intent = f"Repeated activity across {', '.join(apps)}."
        sessions = dna.boundaries.total_supporting_sessions
        summary = (
            f"Repeated {sessions} times. {len(actions)} of {len(steps)} observed steps can be automated "
            f"through {', '.join(dict.fromkeys(a.application for a in actions)) or 'no integration yet'}."
        )

        return {
            "source_dna_id": dna.dna_id,
            "title": title,
            "intent": intent,
            "summary": summary,
            "semantic_steps": steps,
            "semantic_variables": variables,
            "optional_steps": optional,
            "preconditions": [f"{app} is reachable." for app in dict.fromkeys(a.application for a in actions)],
            "boundaries": dna.boundaries.model_dump(),
            "evidence_mapping": {
                "invariants": dna.evidence.invariant_evidence,
                "variables": dna.evidence.variable_evidence,
            },
            "interpretation_notes": "Described by built-in rules from observed steps and the action catalog (no LLM).",
            "model_provider": "rule-based",
            "status": "interpreted",
        }
