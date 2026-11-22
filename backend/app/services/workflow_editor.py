"""Workflow editor: change an existing workflow's steps and inputs, as a new version that a person
must approve again.

What can change: the title and description; which catalog steps run and in what order (remove,
reorder, or add any catalog action, also one never recorded); and for each step's inputs, where
the value comes from:
- upstream: a value an earlier step of the same run produced (`{message_id}`, `{slack_ts}`, ...)
- fixed:    a constant chosen here
- runtime:  asked for when the run starts
Optional inputs may also be left out (the executor's default, e.g. the property chosen in Settings).

Everything is checked here, deterministically, against the action catalog; nothing is guessed:
- only catalog actions and their declared parameters; every required input has a source;
- an upstream value must be produced by an earlier step, and so must everything a step `requires`
  (e.g. "reply in thread" needs an earlier "post to Slack");
- a value that changed between recorded runs (a customer's email, a message id) cannot be pinned to
  one of those recorded values: it would act on the wrong record in every later run.

Saving creates the next version (1.0.0 -> 1.1.0), keeps every earlier version, records who changed
what, and puts the workflow back to "requires review": nothing runs until it is approved again.
Non-executable context steps (e.g. window focus) are not part of an edited version; they stay
visible in the recorded version 1.0.0.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.canonical import (
    ApprovalMetadata,
    ApprovalState,
    CanonicalStep,
    CanonicalWorkflowSpec,
    StepParameter,
    StepParameterMode,
)
from app.services.action_catalog import CatalogAction, get_action

MAX_STEPS = 30
MAX_VALUE = 1000


class EditedStep(BaseModel):
    step_id: Optional[str] = Field(default=None, description="An existing step's id, or empty for a new step")
    catalog_action: str = Field(..., min_length=3, max_length=100)
    parameters: Dict[str, StepParameter] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    base_version: str = Field(..., min_length=1, max_length=20, description="The version this edit started from")
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    steps: List[EditedStep] = Field(..., min_length=1, max_length=MAX_STEPS)
    note: Optional[str] = Field(default=None, max_length=500, description="What changed and why")


class Issue(BaseModel):
    level: str  # "error" blocks saving; "warning" is shown but allowed
    message: str
    step: Optional[int] = None  # 0-based index in the edited steps
    parameter: Optional[str] = None


def _template_key(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text[1:-1] if len(text) > 2 and text.startswith("{") and text.endswith("}") else None


# ---------------------------------------------------------------- current state


def _derived_parameters(spec: CanonicalWorkflowSpec, step: CanonicalStep, catalog: CatalogAction) -> Dict[str, StepParameter]:
    """What the planner would use for a step that was never edited, as editor choices."""
    if step.parameters is not None:
        return dict(step.parameters)
    from app.services.execution_planner import ExecutionPlanner

    resolved = ExecutionPlanner().resolve_parameters(spec)
    values = ExecutionPlanner._catalog_step_parameters(catalog, step.source_dna_step_key, spec, resolved, {})
    out: Dict[str, StepParameter] = {}
    for p in catalog.parameters:
        if p.name not in values:
            continue
        value = values[p.name]
        key = _template_key(value)
        if key:
            out[p.name] = StepParameter(mode=StepParameterMode.UPSTREAM, value=key)
        elif value is None:
            out[p.name] = StepParameter(mode=StepParameterMode.RUNTIME)
        else:
            out[p.name] = StepParameter(mode=StepParameterMode.FIXED, value=str(value))
    return out


def current_definition(spec: CanonicalWorkflowSpec) -> Dict[str, Any]:
    """The workflow as the editor shows it: its runnable steps with each input's source."""
    steps, context = [], []
    for step in spec.steps:
        catalog = get_action(step.catalog_action)
        if catalog is None:
            context.append({"step_id": step.canonical_step_id, "application": step.application, "description": step.description})
            continue
        steps.append(
            {
                "step_id": step.canonical_step_id,
                "catalog_action": catalog.action_id,
                "parameters": {k: v.model_dump(mode="json") for k, v in _derived_parameters(spec, step, catalog).items()},
            }
        )
    return {
        "workflow_id": spec.workflow_id,
        "version": spec.version,
        "approval_state": spec.approval_state.state.value,
        "title": spec.title,
        "description": spec.description,
        "steps": steps,
        "context_steps": context,
    }


def recorded_values(spec: CanonicalWorkflowSpec) -> Dict[Tuple[str, str], List[str]]:
    """(step key, parameter) -> the values seen in recordings, for parameters that changed between runs."""
    from app.services.execution_planner import _catalog_param_name

    out: Dict[Tuple[str, str], List[str]] = {}
    for b in spec.variables:
        name = _catalog_param_name(b.source_field)
        if name and len(set(b.observed_values)) > 1:
            out[(b.associated_step_key, name)] = list(b.observed_values)
    return out


# ------------------------------------------------------------------- validation


def validate(spec: CanonicalWorkflowSpec, definition: WorkflowDefinition) -> List[Issue]:
    issues: List[Issue] = []

    def err(message: str, step: Optional[int] = None, parameter: Optional[str] = None) -> None:
        issues.append(Issue(level="error", message=message, step=step, parameter=parameter))

    def warn(message: str, step: Optional[int] = None, parameter: Optional[str] = None) -> None:
        issues.append(Issue(level="warning", message=message, step=step, parameter=parameter))

    if definition.base_version != spec.version:
        err(f"This workflow is now version {spec.version}; your changes start from {definition.base_version}. Reload it.")

    existing = {s.canonical_step_id: s for s in spec.steps}
    varied = recorded_values(spec)
    seen_ids = set()
    available: Dict[str, str] = {}  # run value -> label of the step that produces it

    for i, edited in enumerate(definition.steps):
        catalog = get_action(edited.catalog_action)
        if catalog is None:
            err(f"'{edited.catalog_action}' is not an action WorkFlowOS can run.", i)
            continue
        label = f"{catalog.application}: {catalog.description}"
        if edited.step_id:
            base = existing.get(edited.step_id)
            if base is None or base.catalog_action != catalog.action_id:
                err("This step does not belong to this workflow.", i)
            elif edited.step_id in seen_ids:
                err("The same step appears twice; add a new step instead.", i)
            seen_ids.add(edited.step_id)
        else:
            if catalog.requires_confirmation:
                warn(f"New high-risk step ({catalog.risk_reason}) Every run of it needs confirmation.", i)

        for needed in catalog.requires:
            if needed not in available:
                err(f"This step needs '{needed}' from an earlier step. Put the step that provides it before this one.", i)

        declared = {p.name: p for p in catalog.parameters}
        for name in edited.parameters:
            if name not in declared:
                err(f"'{name}' is not an input of this action.", i, name)
        step_key = catalog.step_key
        for p in catalog.parameters:
            choice = edited.parameters.get(p.name)
            if choice is None:
                if p.required:
                    err(f"Choose where '{p.name}' comes from.", i, p.name)
                continue
            value = (choice.value or "").strip()
            if choice.mode == StepParameterMode.UPSTREAM:
                if not value:
                    err(f"Choose which earlier value '{p.name}' uses.", i, p.name)
                elif value not in available:
                    err(f"'{value}' is not produced by any earlier step.", i, p.name)
            elif choice.mode == StepParameterMode.FIXED:
                if not value:
                    err(f"Enter a value for '{p.name}', or choose another source.", i, p.name)
                elif len(value) > MAX_VALUE:
                    err(f"'{p.name}' is too long (at most {MAX_VALUE} characters).", i, p.name)
                elif _template_key(value):
                    err(f"To use an earlier step's value for '{p.name}', choose 'From an earlier step'.", i, p.name)
                elif value in varied.get((step_key, p.name), []):
                    err(
                        f"'{value}' is from one recorded run, and '{p.name}' was different in each run. "
                        "Fixing it would act on that same record every time: take it from an earlier step or ask at run time.",
                        i,
                        p.name,
                    )
            elif choice.mode == StepParameterMode.RUNTIME and p.required:
                warn(f"'{p.name}' must be given when a run starts; email triggers cannot supply it.", i, p.name)

        for key in catalog.produces:
            available.setdefault(key, label)

    return issues


# ------------------------------------------------------------------------ apply


def next_version(version: str) -> str:
    parts = (version or "1.0.0").split(".")
    try:
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return f"{version}.1"
    return f"{major}.{minor + 1}.0"


def apply(spec: CanonicalWorkflowSpec, definition: WorkflowDefinition, actor: str) -> CanonicalWorkflowSpec:
    """The edited spec (call validate() first; this assumes no errors)."""
    from app.services.canonical_factory import CanonicalWorkflowFactory
    from app.services.risk_analyzer import RiskAnalyzer

    existing = {s.canonical_step_id: s for s in spec.steps}
    used_ids = set(existing)
    steps: List[CanonicalStep] = []
    for edited in definition.steps:
        catalog = get_action(edited.catalog_action)
        params = {k: StepParameter(mode=v.mode, value=(v.value or "").strip() or None) for k, v in edited.parameters.items()}
        if edited.step_id and edited.step_id in existing:
            steps.append(existing[edited.step_id].model_copy(update={"parameters": params}))
            continue
        n = 1
        while f"can-step-e{n}" in used_ids:
            n += 1
        step_id = f"can-step-e{n}"
        used_ids.add(step_id)
        steps.append(
            CanonicalStep(
                canonical_step_id=step_id,
                source_semantic_step_id="workflow-editor",
                source_dna_step_key=catalog.step_key,
                application=catalog.application,
                event_type="added_in_editor",
                action=catalog.action,
                description=catalog.description,
                input_variables=[p.name for p in catalog.parameters],
                output_variables=list(catalog.produces),
                evidence_reference=f"Added in the workflow editor by {actor} (not recorded)",
                risk=CanonicalWorkflowFactory.catalog_step_risk(step_id, catalog),
                occurrence_ratio=0.0,
                classification="added",
                catalog_action=catalog.action_id,
                parameters=params,
            )
        )

    now = datetime.now(timezone.utc).isoformat()
    note = (definition.note or "").strip()
    return spec.model_copy(
        update={
            "title": definition.title.strip(),
            "description": definition.description.strip(),
            "steps": steps,
            "optional_steps": [],
            "risk_assessment": RiskAnalyzer().aggregate_step_risks([s.risk for s in steps]),
            "version": next_version(spec.version),
            "updated_at": now,
            "approval_state": ApprovalMetadata(
                state=ApprovalState.REQUIRES_REVIEW,
                comments=f"Edited by {actor}" + (f": {note}" if note else ""),
            ),
        }
    )


# ------------------------------------------------------------------------- diff


def _label(step: Dict[str, Any]) -> str:
    catalog = get_action(step.get("catalog_action"))
    return f"{catalog.application}: {catalog.description}" if catalog else str(step.get("catalog_action"))


def _source(choice: Optional[Dict[str, Any]]) -> str:
    if not choice:
        return "default"
    mode, value = choice.get("mode"), choice.get("value")
    return {"upstream": f"from earlier step ({value})", "fixed": f"fixed '{value}'", "runtime": "asked at run time"}.get(mode, str(mode))


def changes_between(old: CanonicalWorkflowSpec, new: CanonicalWorkflowSpec) -> List[Dict[str, Any]]:
    """Human-readable step-level differences between two versions."""
    a, b = current_definition(old), current_definition(new)
    out: List[Dict[str, Any]] = []
    if a["title"] != b["title"]:
        out.append({"kind": "title", "text": f"Title changed to '{b['title']}'"})
    if a["description"] != b["description"]:
        out.append({"kind": "description", "text": "Description changed"})
    old_steps = {s["step_id"]: s for s in a["steps"]}
    new_ids = [s["step_id"] for s in b["steps"]]
    for s in a["steps"]:
        if s["step_id"] not in new_ids:
            out.append({"kind": "removed", "text": f"Removed: {_label(s)}"})
    common_old = [s["step_id"] for s in a["steps"] if s["step_id"] in new_ids]
    common_new = [i for i in new_ids if i in old_steps]
    for pos, s in enumerate(b["steps"], 1):
        before = old_steps.get(s["step_id"])
        if before is None:
            out.append({"kind": "added", "text": f"Added step {pos}: {_label(s)}"})
            continue
        if common_old.index(s["step_id"]) != common_new.index(s["step_id"]):
            out.append({"kind": "moved", "text": f"Moved to step {pos}: {_label(s)}"})
        for name in sorted(set(before["parameters"]) | set(s["parameters"])):
            was, now = before["parameters"].get(name), s["parameters"].get(name)
            if was != now:
                out.append({"kind": "input", "text": f"{_label(s)}: '{name}' {_source(was)} -> {_source(now)}"})
    if a["context_steps"] and not b["context_steps"]:
        out.append({"kind": "context", "text": f"{len(a['context_steps'])} recorded context step(s) are not part of this version"})
    return out
